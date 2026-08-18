from src.enum.task import TaskStatusEnum
from src.schemas.task import TaskModel
from src.sqlite.sqlite import AsyncSQLiteSingleton


class TaskManager:
    """任务管理类"""
    @staticmethod
    async def get_task_by_id(task_id: str) -> TaskModel | None:
        """根据任务ID获取任务信息"""
        sql_str = """
            SELECT task_id, pid, task_name, task_type, completion_precent, status, task_related_params, created_at
            FROM task_table
            WHERE task_id = :task_id
        """
        params = {"task_id": task_id}
        results = await AsyncSQLiteSingleton().execute_query(sql_str, params)
        if results:
            return TaskModel(**results[0])
        return None

    @staticmethod
    async def get_tasks_by_ids(task_ids: list[str]) -> list[TaskModel]:
        """根据任务ID列表获取多个任务信息"""
        if not task_ids:
            return []
        placeholders = ', '.join(['?'] * len(task_ids))
        sql_str = f"""
            SELECT task_id, pid, task_name, task_type, completion_precent, status, task_related_params, created_at
            FROM task_table
            WHERE task_id IN ({placeholders})
        """
        results = await AsyncSQLiteSingleton().execute_query(sql_str, tuple(task_ids))
        return [TaskModel(**result) for result in results]

    @staticmethod
    async def get_tasks_by_status(status: list[TaskStatusEnum]) -> list[TaskModel]:
        """根据任务状态获取任务列表"""
        if not status:
            return []
        placeholders = ', '.join(['?'] * len(status))
        sql_str = f"""
            SELECT task_id, pid, task_name, task_type, completion_precent, status, task_related_params, created_at
            FROM task_table
            WHERE status IN ({placeholders})
        """
        tmp_tuple = tuple(s.value for s in status)
        results = await AsyncSQLiteSingleton().execute_query(sql_str, tmp_tuple)
        return [TaskModel(**result) for result in results]

    @staticmethod
    async def update_task_by_id(task_id: str, update_data: dict) -> bool:
        """根据任务ID更新任务信息"""
        set_clauses = []
        params = {"task_id": task_id}
        for key, value in update_data.items():
            set_clauses.append(f"{key} = :{key}")
            params[key] = value
        set_clause_str = ", ".join(set_clauses)

        sql_str = f"""
            UPDATE task_table
            SET {set_clause_str}
            WHERE task_id = :task_id
        """
        result = await AsyncSQLiteSingleton().execute_modify(sql_str, params)
        return result

    @staticmethod
    async def update_running_tasks_to_pending_tasks():
        """将所有正在运行的任务状态更新为待执行（用于服务重启后恢复任务状态）"""
        sql_str = """
            UPDATE task_table
            SET status = :pending_status
            WHERE status = :running_status
        """
        params = {"pending_status": TaskStatusEnum.PENDING.value,
                  "running_status": TaskStatusEnum.RUNNING.value}
        result = await AsyncSQLiteSingleton().execute_modify(sql_str, params)
        return result

    @staticmethod
    async def create_task(task: TaskModel) -> bool:
        """创建新任务"""
        sql_str = """
            INSERT INTO task_table (task_id, pid, task_name, task_type, completion_precent, status, task_related_params, created_at)
            VALUES (:task_id, :pid, :task_name, :task_type, :completion_precent, :status, :task_related_params, :created_at)
        """
        result = await AsyncSQLiteSingleton().execute_modify(sql_str, task.model_dump(exclude_none=False, by_alias=True))
        return result

    @staticmethod
    async def delete_task_by_id(task_id: str) -> bool:
        """根据任务ID删除任务"""
        sql_str = """
            DELETE FROM task_table
            WHERE task_id = :task_id
        """
        params = {"task_id": task_id}
        result = await AsyncSQLiteSingleton().execute_modify(sql_str, params)
        return result

    @staticmethod
    async def delete_tasks_by_ids(task_ids: list[str]) -> bool:
        """根据任务ID列表删除多个任务"""
        if not task_ids:
            return False
        placeholders = ', '.join(['?'] * len(task_ids))
        sql_str = f"""
            DELETE FROM task_table
            WHERE task_id IN ({placeholders})
        """
        result = await AsyncSQLiteSingleton().execute_modify(sql_str, tuple(task_ids))
        return result

    @staticmethod
    async def delete_tasks_by_status(status: str) -> bool:
        """根据任务状态删除任务"""
        sql_str = """
            DELETE FROM task_table
            WHERE status = :status
        """
        params = {"status": status}
        result = await AsyncSQLiteSingleton().execute_modify(sql_str, params)
        return result

    @staticmethod
    async def get_all_tasks() -> list[TaskModel]:
        """获取所有任务"""
        sql_str = """
            SELECT task_id, pid, task_name, task_type, completion_precent, status, task_related_params, created_at
            FROM task_table
            ORDER BY created_at DESC
        """
        results = await AsyncSQLiteSingleton().execute_query(sql_str)
        return [TaskModel(**result) for result in results]
