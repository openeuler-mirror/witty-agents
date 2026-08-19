import os
from datetime import datetime
import json
import uuid
from src.sqlite.manager.task import TaskManager
from src.schemas.task import TaskModel, TaskRelatedParamsModel
from src.schemas.log import LogModel, LogParseResultModel
from src.worker.base import BaseWorker
from src.enum.task import TaskTypeEnum, TaskStatusEnum
from src.enum.log import LogLevelEnum, LogTypeEnum
from src.sqlite.manager.log_parse_result import LogParseResultManager
from src.config.config import Config


class LogTaskHandleService:
    @staticmethod
    async def create_log_parse_task(
        task_type: TaskTypeEnum | None, 
        query: str, file_path_list: list[str], 
        max_anomaly_log_count: int, 
        anomaly_keywords: list[str],
        time_start: str | None = None,
        time_end: str | None = None,
        enable_deduplication: bool = False,
        deduplication_threshold: float = 0.8) -> str:
        """创建日志解析任务"""
        if task_type is None:
            task_type = Config().get_config().log_parse_method
        file_path_existed_list = []
        for file_path in file_path_list:
            if os.path.exists(file_path):
                file_path_existed_list.append(file_path)
        file_path_list = file_path_existed_list
        # 生成一个新的文件目录，用于存储当前任务的相关文件
        task_model = TaskModel(
            task_name=f"{task_type.value} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            task_type=task_type.value,
            completion_precent=0.0,
            status=TaskStatusEnum.PENDING.value,
            task_related_params=json.dumps({
                "query": query,
                "file_path_list": file_path_list,
                "max_anomaly_log_count": max_anomaly_log_count,
                "anomaly_keywords": anomaly_keywords,
                "time_start": time_start,
                "time_end": time_end,
                "enable_deduplication": enable_deduplication,
                "deduplication_threshold": deduplication_threshold
            })
        )
        flag = await TaskManager.create_task(task_model)
        if not flag:
            raise Exception("创建任务失败")
        return task_model.task_id

    @staticmethod
    async def stop_task(task_id: str) -> bool:
        """停止日志解析任务"""
        flag = await BaseWorker.stop(task_id)
        return flag

    @staticmethod
    async def get_task_message(task_id: str) -> TaskModel:
        """获取任务信息"""
        task_model = await TaskManager.get_task_by_id(task_id)
        return task_model

    @staticmethod
    async def get_task_result(task_id: str, limit: int | None = None, offset: int | None = None, is_anomalous: bool | None = None) -> tuple[int, list[LogParseResultModel]]:
        """获取任务结果"""
        total, log_parse_result_models = await LogParseResultManager.get_log_parse_results_by_task_id(task_id, limit, offset, is_anomalous)
        return total, log_parse_result_models

    @staticmethod
    async def delete_task(task_id: str) -> bool:
        """删除指定的任务"""
        # 先尝试停止任务（如果任务正在运行）
        await BaseWorker.stop(task_id)
        # 删除关联的日志解析结果
        await LogParseResultManager.delete_log_parse_results_by_task_id(task_id)
        # 然后从数据库中删除任务记录
        success = await TaskManager.delete_task_by_id(task_id)
        return success
        
    @staticmethod
    async def get_all_tasks() -> list[TaskModel]:
        """获取所有任务"""
        return await TaskManager.get_all_tasks()
