from src.enum.log import LogLevelEnum, LogTypeEnum
from pydantic import BaseModel, Field
import uuid
from datetime import datetime


class LogModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="日ID")
    file_path: str = Field(..., description="日志文件路径")
    log_type: LogTypeEnum | None = Field(default=None, description="日志类型")
    offset: int = Field(..., description="日志偏移量")
    start_time: datetime | None = Field(default=None, description="日志开始时间")
    end_time: datetime | None = Field(default=None, description="日志结束时间")
    level: LogLevelEnum = Field(default=LogLevelEnum.UNKNOWN, description="日志级别")
    content: str = Field(..., description="日志消息内容")
    template: str | None = Field(default=None, description="日志模板内容")
    template_vector: list[float] | None = Field(
        default=None, description="日志的嵌入向量表示"
    )
    save_path: str | None = Field(default=None, description="日志存储路径")
    is_anomalous: bool = Field(default=False, description="日志是否异常")
    anomaly_reason: str = Field(
        default="", description="日志异常原因，如果日志不异常，则返回空字符串"
    )
    anomaly_score: float = Field(
        default=0.0, description="日志异常分数，如果日志不异常，则返回0.0"
    )
    anomaly_keywords: list[str] = Field(
        default_factory=list,
        description="日志异常关键词列表，如果日志不异常，则返回空列表",
    )
    duplicate_count: int = Field(
        default=1, description="该日志条目在结果中出现的次数（去重前）"
    )
    # 并查集参数
    parent_id: str | None = Field(default=None, description="并查集父节点ID")
    rank: int = Field(default=1, description="并查集秩")
    sz: int = Field(default=1, description="并查集大小")


class LogParseResultModel(BaseModel):
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()), description="日志解析结果ID"
    )
    offset: int | None = Field(default=None, description="日志偏移量")
    file_path: str | None = Field(default=None, description="日志文件路径")
    is_anomalous: bool = Field(default=False, description="日志是否异常")
    task_id: str | None = Field(default=None, description="日志解析任务ID")
    content: str | None = Field(default=None, description="日志内容")
    anomaly_reason: str = Field(
        default="", description="日志异常原因，如果日志不异常，则返回空字符串"
    )
    anomaly_score: float = Field(
        default=0.0, description="日志异常分数，如果日志不异常，则返回0.0"
    )
    duplicate_count: int = Field(
        default=1, description="该日志条目在结果中出现的次数（去重前）"
    )
