# Copyright (c) Huawei Technologies Co., Ltd. 2023-2024. All rights reserved.
import os
import signal
import uuid
import asyncio
import multiprocessing
import logging
from src.sqlite.manager.task import TaskManager
from src.enum.task import TaskStatusEnum
from src.config.config import Config
logger = logging.getLogger(__name__)

multiprocessing = multiprocessing.get_context('spawn')


class ProcessHandler:
    ''' 进程处理器类'''
    time_out = 10
    cpu_use_limit = Config().get_config().cpu_use_limit
    cpu_use_limit = min(max(cpu_use_limit, 1), os.cpu_count()//2) # type: ignore

    @staticmethod
    def subprocess_target(target, *args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(target(*args, **kwargs))
        finally:
            loop.close()

    @staticmethod
    async def add_task(task_id: str, target, *args, **kwargs):
        """添加任务到进程池"""
        # 当本机每个cpu使用率>=85%时，认为进程池已满，拒绝添加新任务
        # 计算cpu使用率
        task_running = await TaskManager.get_tasks_by_status([TaskStatusEnum.RUNNING])
        if len(task_running) >= ProcessHandler.cpu_use_limit:
            warning = f"当前运行的任务数 {len(task_running)} 已达到CPU使用限制 {ProcessHandler.cpu_use_limit}，无法添加新任务 {task_id}。"
            logger.warning("[ProcessHandler] %s", warning)
            return False
        task_model = await TaskManager.get_task_by_id(task_id)
        if task_model and task_model.status == TaskStatusEnum.PENDING.value:
            try:
                process = multiprocessing.Process(target=ProcessHandler.subprocess_target,
                                                  args=(target,) + args, kwargs=kwargs)
                process.start()
                await TaskManager.update_task_by_id(task_id, {"pid": process.pid})
                return True
            except Exception as e:
                error = f"添加任务 {task_id} 失败: {e}"
                logger.error("[ProcessHandler] %s", error)
                return False
        else:
            info = f"任务ID {task_id} 已存在，无法添加。"
            logger.info("[ProcessHandler] %s", info)
            return False

    @staticmethod
    async def remove_task(task_id: str):
        """从进程池中移除任务"""
        task_model = await TaskManager.get_task_by_id(task_id)
        
        if task_model and task_model.pid:
            try:
                pid = task_model.pid
                os.kill(pid, signal.SIGKILL)
                info = f"进程 {task_id} ({pid}) 被杀死。"
                logger.info("[ProcessHandler] %s", info)
            except Exception as e:
                warning = f"杀死进程 {task_id} 失败: {e}"
                logger.warning("[ProcessHandler] %s", warning)
        else:
            info = f"任务ID {task_id} 不存在或没有关联的进程，无法移除。"
            logger.info("[ProcessHandler] %s", info)
