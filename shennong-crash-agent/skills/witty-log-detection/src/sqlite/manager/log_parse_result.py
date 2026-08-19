from src.schemas.log import LogParseResultModel
from src.sqlite.sqlite import AsyncSQLiteSingleton


class LogParseResultManager:
    """日志解析结果管理类"""
    @staticmethod
    async def delete_log_parse_results_by_task_id(task_id: str) -> bool:
        """根据任务ID删除关联的日志解析结果"""
        sql_str = """
            DELETE FROM log_parse_result_table
            WHERE task_id = :task_id
        """
        params = {"task_id": task_id}
        result = await AsyncSQLiteSingleton().execute_modify(sql_str, params)
        return result

    @staticmethod
    async def get_log_parse_results_by_task_id(
        task_id: str,
        limit: int | None = None,
        offset: int | None = None,
        is_anomalous: bool | None = None
    ) -> tuple[int, list[LogParseResultModel]]:
        """根据任务ID获取日志解析结果列表（分类讨论版，修复所有问题）"""
        # ========== 1. 统计符合条件的总数 ==========
        count_sql = """
            SELECT COUNT(*) as count
            FROM log_parse_result_table
            WHERE task_id = :task_id
        """
        count_params: dict[str, str | int | bool] = {"task_id": task_id}

        if is_anomalous is not None:
            count_sql += " AND is_anomalous = :is_anomalous"
            count_params["is_anomalous"] = is_anomalous

        count_result = await AsyncSQLiteSingleton().execute_query(count_sql, count_params)
        total_count = count_result[0]["count"] if count_result else 0

        # ========== 2. 分页参数预处理（解决假值/边界问题） ==========
        # 处理limit：区分「传了0/负数」和「没传」，统一为有效数值
        has_limit = limit is not None
        final_limit = limit if (has_limit and limit > 0) else 999999999
        # 处理offset：区分「传了负数」和「没传」，0是合法值；超出总数则返回空
        has_offset = offset is not None
        final_offset = offset if (has_offset and offset >= 0) else 0
        if final_offset >= total_count:
            final_offset = total_count  # 超出范围时返回空

        # ========== 3. 分类讨论构建SQL（核心：所有分支都加排序+合法分页） ==========
        # 基础SQL（所有分支共用）
        base_sql = """
            SELECT id, file_path, offset, is_anomalous, task_id, content, anomaly_reason, anomaly_score, duplicate_count
            FROM log_parse_result_table
            WHERE task_id = :task_id
        """
        params: dict[str, str | int | bool] = {"task_id": task_id}

        # 添加异常状态过滤（所有分支共用）
        if is_anomalous is not None:
            base_sql += " AND is_anomalous = :is_anomalous"
            params["is_anomalous"] = is_anomalous

        # 所有分支都必须加排序（保证分页结果稳定）
        base_sql += " ORDER BY anomaly_score DESC, file_path ASC, offset ASC, id ASC"

        # 分支1：同时传了limit和offset（注意：offset=0也算传了）
        if has_limit and has_offset:
            sql = base_sql + " LIMIT :limit OFFSET :offset"
            params["limit"] = final_limit
            params["offset"] = final_offset
        # 分支2：只传了limit（没传offset）
        elif has_limit:
            sql = base_sql + " LIMIT :limit"
            params["limit"] = final_limit
        # 分支3：只传了offset（没传limit）→ 强制加LIMIT（解决语法问题）
        elif has_offset:
            sql = base_sql + " LIMIT :limit OFFSET :offset"
            params["limit"] = final_limit  # 设为极大值，等效于取所有
            params["offset"] = final_offset
        # 分支4：都没传 → 加LIMIT极大值（兼容语法，等效于取所有）
        else:
            sql = base_sql + " LIMIT :limit"
            params["limit"] = final_limit

        # ========== 4. 执行查询并处理结果 ==========
        results = await AsyncSQLiteSingleton().execute_query(sql, params)

        # 转换为模型（数据库已排序，无需内存再排序）
        log_results = [LogParseResultModel(**result) for result in results]
        log_results.sort(key=lambda x: (x.file_path, x.offset))
        return total_count, log_results

    @staticmethod
    async def add_log_parse_results(log_parse_result_models: list[LogParseResultModel]) -> bool:
        """批量添加日志解析结果"""
        if not log_parse_result_models:
            return False
        # 每次插入 1024 条数据，避免一次性插入过多数据导致性能问题
        batch_size = 1024
        for i in range(0, len(log_parse_result_models), batch_size):
            batch_models = log_parse_result_models[i:i + batch_size]
            sql_str = """
                INSERT INTO log_parse_result_table (id, file_path, offset, is_anomalous, task_id, content, anomaly_reason, anomaly_score, duplicate_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = [(model.id, model.file_path, model.offset, model.is_anomalous, model.task_id,
                       model.content, model.anomaly_reason, model.anomaly_score, model.duplicate_count) for model in batch_models]
            result = await AsyncSQLiteSingleton().execute_modify(sql_str, params)
            if not result:
                return False
        return result
