from enum import Enum


class QueryIntentEnum(str, Enum):
    """查询意图类型枚举"""
    PRECISE_SEARCH = "precise_search"
    SPECIFIC_TYPE = "specific_type"
    ANOMALY_DETECTION = "anomaly_detection"
