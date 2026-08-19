from enum import Enum


class TaskTypeEnum(str, Enum):
    BASE = "base"
    LOG_DETECTION_BASE_ON_KEYWORDS = "log_detection_base_on_keywords"
    LOG_DETECTION_BASE_ON_CLUSTERING = "log_detection_base_on_clustering"
    LOG_DETECTION_BASE_ON_LLM = "log_detection_base_on_llm"
    LOG_DETECTION_BASE_ON_EMBEDDING = "log_detection_base_on_embedding"


class TaskStatusEnum(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CANCLED = "cancled"
    SUCCESSFUL_PENDING_REMOVE = "successful_pending_remove"
    FAILED_PENDING_REMOVE = "failed_pending_remove"
    SUCCESSFUL = "successful"
    FAILED = "failed"
