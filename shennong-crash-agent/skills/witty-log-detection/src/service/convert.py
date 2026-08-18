from src.schemas.log import LogModel, LogParseResultModel


class ConvertService:
    @staticmethod
    async def log_models_to_log_parse_result_models(log_models: list[LogModel], task_id: str) -> list[LogParseResultModel]:
        """将LogModel列表转换为LogParseResultModel列表"""
        log_parse_result_models = []
        for log_model in log_models:
            log_parse_result_model = LogParseResultModel(
                id=log_model.id,
                file_path=log_model.file_path,
                task_id=task_id,
                offset=log_model.offset,
                content=log_model.content,
                is_anomalous=log_model.is_anomalous,
                anomaly_score=log_model.anomaly_score,
                anomaly_reason=log_model.anomaly_reason,
                duplicate_count=log_model.duplicate_count,
            )
            log_parse_result_models.append(log_parse_result_model)
        return log_parse_result_models
