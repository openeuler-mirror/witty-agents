import asyncio
import json
import logging
import os
import re
from datetime import datetime
import random
from typing import Tuple, List, Any
from pydantic import BaseModel, Field
from src.prompt.log_detection import DETECT_LOG_PROMPT
from src.worker.base import BaseWorker
from src.service.embedding import Embedding
from src.service.llm import LLMService
from src.parser.parser import LogParser
from src.sqlite.manager.task import TaskManager
from src.schemas.task import TaskRelatedParamsModel
from src.enum.task import TaskTypeEnum, TaskStatusEnum
from src.schemas.log import LogModel
from src.config.config import Config

logger = logging.getLogger(__name__)


class LogDetectionBasedOnLLMWorker(BaseWorker):
    """
    基于LLM的日志检测Worker
    """

    name = TaskTypeEnum.LOG_DETECTION_BASE_ON_LLM.value

    class LogDetectionResultModel(BaseModel):
        anomaly_score: float = Field(default=0.0, description="日志异常分数，0-100")
        anomaly_reason: str = Field(
            default="", description="日志异常原因，如果日志不异常，则返回空字符串"
        )
        anomaly_keywords: list[str] = Field(
            default_factory=list,
            description="日志异常关键词列表，如果日志不异常，则返回空列表",
        )

    @staticmethod
    def _extract_json_from_llm_response(llm_response: str) -> dict:
        """从 LLM 响应中提取 JSON 对象，兼容 markdown 代码块和纯文本"""
        # 去除 markdown 代码块标记
        cleaned = re.sub(r"^```json\s*", "", llm_response.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        # 尝试直接解析
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 尝试从第一个 { 到最后一个 } 提取
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass

        return {}

    @staticmethod
    async def handle_single_log_model(
        query: str, log_model: LogModel, llm: LLMService
    ) -> LogModel:
        """处理单个日志模型的逻辑"""
        log_content = log_model.content
        prompt = DETECT_LOG_PROMPT.format(query=query, log_content=log_content)
        llm_response = await llm.nostream(
            [],
            prompt,
            "请直接返回JSON格式的字符串，包含anomaly_score（异常分数，0-100）和anomaly_reason（异常原因）两个字段",
            st_str="{",
            en_str="}",
        )
        response_dict = LogDetectionBasedOnLLMWorker._extract_json_from_llm_response(llm_response)
        try:
            log_detection_result = LogDetectionBasedOnLLMWorker.LogDetectionResultModel(
                **response_dict
            )
            log_model.anomaly_score = log_detection_result.anomaly_score
            log_model.anomaly_reason = log_detection_result.anomaly_reason
            log_model.anomaly_keywords = log_detection_result.anomaly_keywords
        except Exception:
            log_model.anomaly_score = 0.0
            log_model.anomaly_reason = f"LLM返回的结果无法解析: {llm_response[:100]}"

    @staticmethod
    async def handle_single_log_file(
        file_path: str,
        max_anomaly_log_count: int,
        query: str,
        llm: LLMService,
        time_start: str,
        time_end: str,
        task_id: str,
        base_progress: float,
        phase_progress: float,
    ) -> tuple[list[Any], list[Any]]:
        """处理单个日志文件的逻辑，带进度更新"""
        # 阶段1：解析日志文件
        log_models: list[LogModel] = await LogParser.parse_log_file(
            file_path=file_path,
            time_start=time_start,
            time_end=time_end,
            chunk_size=max(2048, min(8192, llm.max_tokens // 3 * 2)),
        )
        progress = base_progress + phase_progress * 1
        logger.info(f"[进度更新] task_id={task_id}, total={progress:.1f}%")
        await TaskManager.update_task_by_id(
            task_id, {"completion_precent": min(progress, 95)}
        )

        # 阶段2：处理日志模型，调用LLM进行分析
        for i in range(0, len(log_models), llm.batch_size):
            batch_log_models = log_models[i : i + llm.batch_size]
            handle_tasks = []
            for log_model in batch_log_models:
                handle_tasks.append(
                    LogDetectionBasedOnLLMWorker.handle_single_log_model(
                        query, log_model, llm
                    )
                )
            await asyncio.gather(*handle_tasks)

        progress = base_progress + phase_progress * 2
        logger.info(f"[进度更新] task_id={task_id}, total={progress:.1f}%")
        await TaskManager.update_task_by_id(
            task_id, {"completion_precent": min(progress, 95)}
        )
        keywords_dict = {}
        for log_model in log_models:
            for keyword in log_model.anomaly_keywords:
                if keyword not in keywords_dict:
                    keywords_dict[keyword] = []
                keywords_dict[keyword].append(log_model)
        for keyword in keywords_dict:
            keywords_dict[keyword].sort(key=lambda x: x.anomaly_score, reverse=True)
        # 每个关键字取的异常日志的数量是max_anomaly_log_count // len(keywords_dict)，保证总的异常日志数量不超过max_anomaly_log_count
        existed_log_model_ids = set()
        candidate_unnormal_log_models = []
        keywords_and_max_scores = [
            (keyword, keywords_dict[keyword][0].anomaly_score)
            for keyword in keywords_dict
        ]
        keywords_and_max_scores.sort(key=lambda x: x[1], reverse=True)
        if len(keywords_and_max_scores):
            take_num = max(1, max_anomaly_log_count // len(keywords_and_max_scores))
            for keyword, _ in keywords_and_max_scores:
                keyword_log_models = keywords_dict[keyword]
                for i in range(min(take_num, len(keyword_log_models))):
                    log_model = keyword_log_models[i]
                    if log_model.anomaly_score == 0.0:
                        break
                    if log_model.id not in existed_log_model_ids:
                        candidate_unnormal_log_models.append(log_model)
                        existed_log_model_ids.add(log_model.id)
                    if len(candidate_unnormal_log_models) >= max_anomaly_log_count:
                        break
                if len(candidate_unnormal_log_models) >= max_anomaly_log_count:
                    break
        if len(candidate_unnormal_log_models) < max_anomaly_log_count:
            log_models.sort(key=lambda x: x.anomaly_score, reverse=True)
            for log_model in log_models:
                if log_model.anomaly_score == 0.0:
                    break
                if log_model.id not in existed_log_model_ids:
                    candidate_unnormal_log_models.append(log_model)
                    existed_log_model_ids.add(log_model.id)
                if len(candidate_unnormal_log_models) >= max_anomaly_log_count:
                    break

        progress = base_progress + phase_progress * 3
        logger.info(f"[进度更新] task_id={task_id}, total={progress:.1f}%")
        await TaskManager.update_task_by_id(
            task_id, {"completion_precent": min(progress, 95)}
        )

        return log_models, candidate_unnormal_log_models

    @staticmethod
    async def run(task_id: str) -> None:
        """日志检测服务"""
        try:
            task_entity = await TaskManager.get_task_by_id(task_id)
            if task_entity is None:
                await TaskManager.update_task_by_id(
                    task_id, {"status": TaskStatusEnum.FAILED.value}
                )
                raise ValueError(f"任务 {task_id} 不存在")
            task_related_params_js = json.loads(task_entity.task_related_params)
            if (
                "time_start" in task_related_params_js
                and task_related_params_js["time_start"]
            ):
                task_related_params_js["time_start"] = datetime.strptime(
                    task_related_params_js["time_start"], "%Y-%m-%d %H:%M"
                )
            else:
                task_related_params_js["time_start"] = None
            if (
                "time_end" in task_related_params_js
                and task_related_params_js["time_end"]
            ):
                task_related_params_js["time_end"] = datetime.strptime(
                    task_related_params_js["time_end"], "%Y-%m-%d %H:%M"
                )
            else:
                task_related_params_js["time_end"] = None
            task_related_params_model = TaskRelatedParamsModel(**task_related_params_js)
            query = task_related_params_model.query
            query_embedding = await Embedding.get_embedding(query)
            file_path_list = task_related_params_model.file_path_list
            max_anomaly_log_count = task_related_params_model.max_anomaly_log_count
            anomaly_keywords: list[str] = task_related_params_model.anomaly_keywords
            time_start = task_related_params_model.time_start
            time_end = task_related_params_model.time_end

            # 阶段1：准备工作 (5%)
            log_models = []
            candidate_unnormal_log_models: list[LogModel] = []
            file_path_list = await BaseWorker.get_files_from_file_path_list(
                file_path_list
            )
            await TaskManager.update_task_by_id(task_id, {"completion_precent": 5.0})

            # 阶段2：处理文件 (90%)
            batch_size = 8
            llm = LLMService(
                openai_api_key=Config().get_config().llm_model.api_key,
                openai_api_base=Config().get_config().llm_model.end_point,
                model_name=Config().get_config().llm_model.model_name,
                max_tokens=Config().get_config().llm_model.max_tokens,
                batch_size=Config().get_config().llm_model.batch_size,
            )
            await llm.test_connection()
            await Embedding.test_connection()

            n_files = len(file_path_list)
            # 每个文件分为3个阶段，总共有90%的进度用于文件处理
            total_file_process_percent = 90.0
            phase_progress = (
                total_file_process_percent / (n_files * 3) if n_files > 0 else 0
            )

            for i in range(0, len(file_path_list), batch_size):
                batch_file_path_list = file_path_list[i : i + batch_size]

                # 批量处理文件
                for file_idx, file_path in enumerate(batch_file_path_list):
                    file_base_progress = 5.0 + (i + file_idx) * 3 * phase_progress
                    log_model_list, candidate_unnormal_log_model_list = (
                        await LogDetectionBasedOnLLMWorker.handle_single_log_file(
                            file_path,
                            max_anomaly_log_count,
                            query,
                            llm,
                            time_start,
                            time_end,
                            task_id,
                            file_base_progress,
                            phase_progress,
                        )
                    )
                    log_models.extend(log_model_list)
                    candidate_unnormal_log_models.extend(
                        candidate_unnormal_log_model_list
                    )

            # 阶段3：最终处理 (5%)
            candidate_unnormal_log_models.sort(
                key=lambda x: x.anomaly_score, reverse=True
            )
            candidate_unnormal_log_models = candidate_unnormal_log_models[
                :max_anomaly_log_count
            ]
            await TaskManager.update_task_by_id(task_id, {"completion_precent": 97.5})

            enable_deduplication = task_related_params_model.enable_deduplication
            deduplication_threshold = task_related_params_model.deduplication_threshold
            await LogDetectionBasedOnLLMWorker.add_log_parse_results(
                candidate_unnormal_log_models, log_models, task_id,
                enable_deduplication=enable_deduplication,
                deduplication_threshold=deduplication_threshold
            )

            await TaskManager.update_task_by_id(
                task_id,
                {
                    "completion_precent": 100.0,
                    "status": TaskStatusEnum.SUCCESSFUL_PENDING_REMOVE.value,
                },
            )
            logger.info(f"[进度更新] task_id={task_id}, total=100.0%")
        except ValueError as e:
            await TaskManager.update_task_by_id(
                task_id, {"status": TaskStatusEnum.FAILED.value}
            )
            raise e
        except Exception as e:
            await TaskManager.update_task_by_id(
                task_id, {"status": TaskStatusEnum.FAILED_PENDING_REMOVE.value}
            )
            raise e
