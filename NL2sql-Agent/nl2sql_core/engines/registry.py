from __future__ import annotations

from typing import Any

from nl2sql_core.engines.elasticsearch_engine import ElasticsearchEngine
from nl2sql_core.engines.hbase_engine import HBaseEngine
from nl2sql_core.engines.kafka_engine import KafkaEngine
from nl2sql_core.engines.mock_engine import MockEngine


_REGISTRY: dict[str, Any] = {
    "elasticsearch": ElasticsearchEngine(),
    "hbase": HBaseEngine(),
    "kafka": KafkaEngine(),
    "mock": MockEngine(),
}


def get_engine(engine_type: str):
    key = (engine_type or "").lower().strip()
    if key not in _REGISTRY:
        raise KeyError(f"未知引擎类型: {engine_type}；可用: {sorted(_REGISTRY)}")
    return _REGISTRY[key]


def list_engines() -> list[str]:
    return sorted(_REGISTRY.keys())
