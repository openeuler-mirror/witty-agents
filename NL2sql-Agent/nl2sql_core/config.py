from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "configs"
DATA_DIR = ROOT / "data"


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIGS / name
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class LLMSettings(BaseSettings):
    base_url: str = Field(default="https://api.openai.com/v1", alias="NL2SQL_LLM_BASE_URL")
    api_key: str = Field(default="", alias="NL2SQL_LLM_API_KEY")
    model: str = Field(default="gpt-4o-mini", alias="NL2SQL_LLM_MODEL")

    model_config = {"env_file": str(ROOT / ".env"), "extra": "ignore", "populate_by_name": True}


class AppSettings(BaseModel):
    name: str = "NL2SQL"
    host: str = "0.0.0.0"
    port: int = 8199
    debug: bool = True
    kg_enabled: bool = False
    clarify_enabled: bool = True
    readonly: bool = True
    max_size: int = 100
    timeout_sec: int = 30
    max_query_attempts: int = 3
    retry_on_empty: bool = True
    rules_top_k: int = 100


class RagSettings(BaseModel):
    base_url: str = "http://127.0.0.1:19988"
    access_key: str = "debug-access-key"
    default_kb_id: str = ""
    timeout_sec: int = 60


def load_app_settings() -> AppSettings:
    raw = _load_yaml("app.yaml")
    app = raw.get("app", {})
    safety = raw.get("safety", {})
    kg = raw.get("kg", {})
    clarify = raw.get("clarify", {})
    pipeline = raw.get("pipeline", {})
    port = int(os.getenv("NL2SQL_WEB_PORT", app.get("port", 8199)))
    host = os.getenv("NL2SQL_WEB_HOST", app.get("host", "0.0.0.0"))
    return AppSettings(
        name=app.get("name", "NL2SQL"),
        host=host,
        port=port,
        debug=bool(app.get("debug", True)),
        kg_enabled=bool(kg.get("enabled", False)),
        clarify_enabled=bool(clarify.get("enabled", True)),
        readonly=bool(safety.get("readonly", True)),
        max_size=int(safety.get("max_size", 100)),
        timeout_sec=int(safety.get("timeout_sec", 30)),
        max_query_attempts=int(pipeline.get("max_query_attempts", 3)),
        retry_on_empty=bool(pipeline.get("retry_on_empty", True)),
        rules_top_k=max(1, min(int(pipeline.get("rules_top_k", 100)), 200)),
    )


def load_rag_settings() -> RagSettings:
    raw = _load_yaml("rag_core.yaml")
    runtime: dict[str, Any] = {}
    runtime_path = DATA_DIR / "runtime_settings.json"
    if runtime_path.exists():
        try:
            import json

            runtime = json.loads(runtime_path.read_text(encoding="utf-8")) or {}
        except Exception:
            runtime = {}
    return RagSettings(
        base_url=os.getenv(
            "NL2SQL_RAG_BASE_URL",
            runtime.get("rag_base_url") or raw.get("base_url", "http://127.0.0.1:19988"),
        ),
        access_key=os.getenv(
            "NL2SQL_RAG_ACCESS_KEY",
            runtime.get("rag_access_key") or raw.get("access_key", "debug-access-key"),
        ),
        default_kb_id=os.getenv(
            "NL2SQL_RAG_KB_ID",
            runtime.get("rag_kb_id") or raw.get("default_kb_id", "") or "",
        ),
        timeout_sec=int(raw.get("timeout_sec", 60)),
    )


def load_datasources() -> dict[str, Any]:
    return _load_yaml("datasources.yaml").get("datasources", {})


def load_runtime_settings() -> dict[str, Any]:
    path = DATA_DIR / "runtime_settings.json"
    if not path.exists():
        return {}
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def merge_datasource_config(ds: dict[str, Any], runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    """运行时设置只补缺省，不覆盖 datasources.yaml 已写项。"""
    cfg = dict(ds or {})
    runtime = runtime if runtime is not None else load_runtime_settings()
    t = str(cfg.get("type") or "").lower()
    if t in ("elasticsearch", "es"):
        if not cfg.get("hosts") and runtime.get("es_hosts"):
            cfg["hosts"] = runtime["es_hosts"]
        if not (cfg.get("username") or "").strip() and "es_username" in runtime:
            cfg["username"] = runtime.get("es_username") or ""
            cfg["password"] = runtime.get("es_password") or ""
        if not cfg.get("default_index") and runtime.get("es_default_index"):
            cfg["default_index"] = runtime["es_default_index"]
        cfg.setdefault("verify_certs", False)
    elif t in ("opengauss", "postgres", "postgresql"):
        if not cfg.get("host") and runtime.get("og_host"):
            cfg["host"] = runtime["og_host"]
        if not cfg.get("port") and runtime.get("og_port"):
            cfg["port"] = runtime["og_port"]
        if not cfg.get("database") and runtime.get("og_database"):
            cfg["database"] = runtime["og_database"]
        if not (cfg.get("username") or "").strip() and runtime.get("og_username"):
            cfg["username"] = runtime.get("og_username") or ""
            cfg["password"] = runtime.get("og_password") or ""
        elif not (cfg.get("password") or "").strip() and runtime.get("og_password"):
            cfg["password"] = runtime.get("og_password") or ""
    elif t == "hbase":
        if not cfg.get("host") and runtime.get("hbase_host"):
            cfg["host"] = runtime["hbase_host"]
        if not cfg.get("rest_port") and runtime.get("hbase_rest_port"):
            cfg["rest_port"] = runtime["hbase_rest_port"]
        if not cfg.get("thrift_port") and runtime.get("hbase_thrift_port"):
            cfg["thrift_port"] = runtime["hbase_thrift_port"]
        if not cfg.get("rest_url") and runtime.get("hbase_rest_url"):
            cfg["rest_url"] = runtime["hbase_rest_url"]
    return cfg


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
