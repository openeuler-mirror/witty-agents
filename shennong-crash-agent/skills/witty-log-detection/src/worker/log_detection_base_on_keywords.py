import asyncio
import json
import jieba
import re
from datetime import datetime
from src.worker.base import BaseWorker
from src.parser.parser import LogParser
from src.parser.log_feature_loader import log_feature_class_mapping
from src.sqlite.manager.task import TaskManager
from src.schemas.task import TaskRelatedParamsModel
from src.enum.log import LogTypeEnum
from src.enum.task import TaskTypeEnum, TaskStatusEnum
from src.schemas.log import LogModel
import logging
import math

_logger = logging.getLogger(__name__)
class LogDetectionBasedOnKeywordsWorker(BaseWorker):
    """
    基于关键词的日志检测Worker
    """
    name = TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS.value

    @staticmethod
    async def cal_keyword_similarity(str1: str, keywords: list[str]) -> float:
        """计算关键词匹配分数，使用ln型曲线：命中1个及格(60分)，命中越多分数越高，趋近100分"""
        words = list(jieba.cut(str1))
        words_set = set(words)
        keywords_set = set(keywords)
        # 统计匹配到的关键词数量（不去重，每个关键词单独算）
        matched_count = 0
        for keyword in keywords_set:
            keyword_parts = set(jieba.cut(keyword))
            if words_set & keyword_parts:
                matched_count += 1
        
        if matched_count == 0:
            return 0.0
        
        # ln型曲线：命中1个=60分，命中5个趋近100分
        return min(100.0, 60.0 + 40.0 * math.log(matched_count) / math.log(5))

    @staticmethod
    async def cal_sentiment_score(log_type: LogTypeEnum, log_content: str) -> float:
        """计算日志的情感分数"""
        log_class = log_feature_class_mapping.get(log_type, None)
        if log_class is None:
            return 0.0
        sum = 0.0
        score = 0.0
        for anomalous_keywords, _ in log_class.keywords_regex_and_scores["anomalous"].items():
            sum += _
            if re.search(anomalous_keywords, log_content):
                score += _
        return score/sum * 100 if sum > 0 else 0.0

    @staticmethod
    async def handle_single_log_file(file_path: str, max_anomaly_log_count: int, anomaly_keywords: list[str], time_start: str, time_end: str) -> list[LogModel]:
        """处理单个日志文件的逻辑"""
        log_models: list[LogModel] = await LogParser.parse_log_file(file_path=file_path, need_split_by_regex=True, time_start=time_start, time_end=time_end)
        for log_model in log_models:
            log_type = log_model.log_type
            log_content = log_model.content
            sentiment_score = await LogDetectionBasedOnKeywordsWorker.cal_sentiment_score(log_type, log_content)
            keyword_similarity = await LogDetectionBasedOnKeywordsWorker.cal_keyword_similarity(log_content, anomaly_keywords)
            final_score = 0.2*sentiment_score + 0.8*keyword_similarity
            log_model.anomaly_score = final_score
        candidate_unnormal_log_models = sorted(
            log_models, key=lambda x: x.anomaly_score, reverse=True)[:max_anomaly_log_count]
        return log_models, candidate_unnormal_log_models

    @staticmethod
    async def run(task_id: str) -> None:
        """日志检测服务"""
        try:
            task_entity = await TaskManager.get_task_by_id(task_id)
            if task_entity is None:
                await TaskManager.update_task_by_id(task_id, {"status": TaskStatusEnum.FAILED.value})
                raise ValueError(f"任务 {task_id} 不存在")
            task_related_params_js = json.loads(
                task_entity.task_related_params)
            if "time_start" in task_related_params_js and task_related_params_js["time_start"]:
                task_related_params_js["time_start"] = datetime.strptime(task_related_params_js["time_start"],
                                                                         '%Y-%m-%d %H:%M')
            else:
                task_related_params_js["time_start"] = None
            if "time_end" in task_related_params_js and task_related_params_js["time_end"]:
                task_related_params_js["time_end"] = datetime.strptime(task_related_params_js["time_end"],
                                                                       '%Y-%m-%d %H:%M')
            else:
                task_related_params_js["time_end"] = None
            task_related_params_model = TaskRelatedParamsModel(
                **task_related_params_js)
            _logger.info(f"任务 {task_id} 相关参数: {task_related_params_model}")
            
            query = task_related_params_model.query
            file_path_list = task_related_params_model.file_path_list
            max_anomaly_log_count = task_related_params_model.max_anomaly_log_count
            anomaly_keywords: list[str] = task_related_params_model.anomaly_keywords
            time_start = task_related_params_model.time_start
            time_end = task_related_params_model.time_end
            # 异常日志候选列表
            log_models = []
            candidate_unnormal_log_models: list[LogModel] = []
            batch_size = 8
            file_path_list = await BaseWorker.get_files_from_file_path_list(file_path_list)
            _logger.info(f"任务 {task_id} 处理文件路径列表: {file_path_list}")
            total_files = len(file_path_list)
            processed_files = 0
            # 更新任务进度为0%
            progress = 0.0
            _logger.info(f"[进度更新] task_id={task_id}, total={progress:.1f}%")
            await TaskManager.update_task_by_id(task_id, {"completion_precent": progress})
            for i in range(0, len(file_path_list), batch_size):
                batch_file_path_list = file_path_list[i:i + batch_size]
                handle_tasks = []
                for file_path in batch_file_path_list:
                    handle_tasks.append(LogDetectionBasedOnKeywordsWorker.handle_single_log_file(
                        file_path, max_anomaly_log_count, anomaly_keywords, time_start, time_end))
                batch_results = await asyncio.gather(*handle_tasks)
                for log_model_list, candidate_unnormal_log_model_list in batch_results:
                    log_models.extend(log_model_list)
                    candidate_unnormal_log_models.extend(
                        candidate_unnormal_log_model_list)
                processed_files += len(batch_file_path_list)
                # 更新任务进度
                progress = (processed_files / total_files) * 95
                _logger.info(f"[进度更新] task_id={task_id}, total={progress:.1f}%")
                await TaskManager.update_task_by_id(task_id, {"completion_precent": min(progress, 95)})
            candidate_unnormal_log_models.sort(
                key=lambda x: x.anomaly_score, reverse=True)
            candidate_unnormal_log_models = candidate_unnormal_log_models[:max_anomaly_log_count]
            enable_deduplication = task_related_params_model.enable_deduplication
            deduplication_threshold = task_related_params_model.deduplication_threshold
            await LogDetectionBasedOnKeywordsWorker.add_log_parse_results(
                candidate_unnormal_log_models, log_models, task_id,
                enable_deduplication=enable_deduplication,
                deduplication_threshold=deduplication_threshold
            )
            # 任务完成，更新进度为100%
            progress = 100.0
            _logger.info(f"[进度更新] task_id={task_id}, total={progress:.1f}%")
            await TaskManager.update_task_by_id(task_id, {"completion_precent": progress, "status": TaskStatusEnum.SUCCESSFUL_PENDING_REMOVE.value})
        except Exception as e:
            await TaskManager.update_task_by_id(task_id, {"status": TaskStatusEnum.FAILED_PENDING_REMOVE.value})
            raise e
