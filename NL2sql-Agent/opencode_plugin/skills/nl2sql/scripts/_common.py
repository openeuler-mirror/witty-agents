#!/usr/bin/env python3
"""Skill 侧公共：定位仓库根、读/写 runtime_settings，不改 nl2sql_core。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# .../opencode_plugin/skills/nl2sql/scripts -> 仓库根为 parents[4]
PKG_ROOT = Path(__file__).resolve().parents[4]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from nl2sql_core.config import (  # noqa: E402
    LLMSettings,
    ensure_data_dir,
    load_rag_settings,
    merge_datasource_config,
)
from nl2sql_core.llm.client import LLMClient  # noqa: E402

SETTINGS_FILE = ensure_data_dir() / "runtime_settings.json"


def load_runtime() -> dict[str, Any]:
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    return {}


def save_runtime(data: dict[str, Any]) -> None:
    ensure_data_dir()
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def llm_client() -> LLMClient:
    runtime = load_runtime()
    base = LLMSettings()
    return LLMClient(
        LLMSettings(
            base_url=runtime.get("llm_base_url") or base.base_url,
            api_key=runtime.get("llm_api_key") or base.api_key,
            model=runtime.get("llm_model") or base.model,
        )
    )


def merge_ds(ds: dict[str, Any]) -> dict[str, Any]:
    return merge_datasource_config(ds, load_runtime())


def dump(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def read_json_arg(path_or_dash: str) -> Any:
    if path_or_dash == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path_or_dash).read_text(encoding="utf-8"))
