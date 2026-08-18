import asyncio
import logging
import multiprocessing
from src.worker.base import BaseWorker
from src.service.process import ProcessHandler
from src.enum.task import TaskStatusEnum
from src.sqlite.manager.task import TaskManager


logger = logging.getLogger(__name__)
# 使用 spawn 启动方式，确保跨平台兼容性
multiprocessing_context = multiprocessing.get_context('spawn')


class TaskService:
    """任务服务类"""
    @staticmethod
    async def update_running_tasks_to_pending_tasks():
        """将所有运行中的任务状态更新为待处理，避免因服务重启导致的任务状态不一致问题"""
        task_models = await TaskManager.get_tasks_by_status([TaskStatusEnum.RUNNING])
        for task_model in task_models:
            await ProcessHandler.remove_task(task_model.task_id)
        await TaskManager.update_running_tasks_to_pending_tasks()

    @staticmethod
    async def process_successful_or_failed_tasks():
        """处理所有成功或失败的任务"""
        tasks = await TaskManager.get_tasks_by_status([TaskStatusEnum.SUCCESSFUL_PENDING_REMOVE, TaskStatusEnum.FAILED_PENDING_REMOVE])
        for task in tasks:
            try:
                await ProcessHandler.remove_task(task.task_id)
                logger.info(f"任务 {task.task_id} 处理完成并移除")
            except Exception as e:
                logger.error(f"处理任务 {task.task_id} 时出错: {e}")
            if task.status == TaskStatusEnum.SUCCESSFUL_PENDING_REMOVE.value:
                await TaskManager.update_task_by_id(task.task_id, {"status": TaskStatusEnum.SUCCESSFUL.value})
            elif task.status == TaskStatusEnum.FAILED_PENDING_REMOVE.value:
                await TaskManager.update_task_by_id(task.task_id, {"status": TaskStatusEnum.FAILED.value})
        return []  # 修正：将return移出循环，否则只处理第一个任务就返回

    @staticmethod
    async def process_pending_tasks():
        """处理所有待处理任务"""
        tasks = await TaskManager.get_tasks_by_status([TaskStatusEnum.PENDING])
        for task in tasks:
            try:
                result = await BaseWorker.run(task.task_id)
                if not result:
                    continue  # 修正：使用continue而非break，避免处理一个失败就停止所有任务
            except Exception as e:
                logger.error(f"处理任务 {task.task_id} 时出错: {e}")

    @staticmethod
    async def listen_and_process_tasks():
        """监听并处理任务的主循环"""
        logger.info("[TaskService] listen_and_process_tasks 启动")
        while True:
            try:
                await TaskService.process_successful_or_failed_tasks()
                await TaskService.process_pending_tasks()
            except Exception as e:
                logger.error(f"[TaskService] 任务处理主循环出错: {e}")
                import traceback
                traceback.print_exc()
            await asyncio.sleep(2)  # 每隔2秒检查一次任务

    @staticmethod
    def _run_async_loop():
        """独立的静态方法：启动异步事件循环（解决pickle序列化问题）"""
        logger.info("[TaskService] _run_async_loop 启动")
        try:
            # 创建并运行异步事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(TaskService.listen_and_process_tasks())
        except KeyboardInterrupt:
            logger.info("[TaskService] 任务监听进程被手动终止")
        except Exception as e:
            logger.error(f"[TaskService] 任务监听进程运行出错: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # 确保事件循环正确关闭
            loop.close()

    @staticmethod
    def run_task_listener_in_process():
        """在独立进程中运行任务监听循环"""
        logger.info("[TaskService] run_task_listener_in_process 被调用")
        # 创建子进程（使用提前创建的context）
        listener_process = multiprocessing_context.Process(
            target=TaskService._run_async_loop,  # 指向类的静态方法
            name="TaskListenerProcess",  # 给进程命名，方便调试
        )

        # 启动进程
        listener_process.start()
        logger.info(f"[TaskService] 任务监听进程已启动，进程ID: {listener_process.pid}")
        print(f"任务监听进程已启动，进程ID: {listener_process.pid}")

        # 返回进程对象，方便外部管理
        return listener_process
