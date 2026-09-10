#!/usr/bin/env python3
"""Skill 侧公共：定位 NL2SQL 仓库根、读/写 runtime_settings，不改 nl2sql_core。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
_CONFIG_PATH = _SCRIPTS_DIR / "config.json"


def _looks_like_repo(root: Path) -> bool:
    return (root / "nl2sql_core").is_dir() and (root / "configs").is_dir()


def _default_repo_root() -> Path:
    # 仓内布局：<repo>/opencode_plugin/skills/nl2sql/scripts -> parents[4] == repo
    return Path(__file__).resolve().parents[4]


def _load_config() -> dict[str, Any]:
    if not _CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        raise SystemExit(f"无法读取 {_CONFIG_PATH}: {e}") from e


def resolve_pkg_root() -> Path:
    """优先级：环境变量 NL2SQL_ROOT > scripts/config.json 的 nl2sql_root > 默认 parents[4]。"""
    env = (os.environ.get("NL2SQL_ROOT") or "").strip()
    if env:
        root = Path(env).expanduser().resolve()
        if not _looks_like_repo(root):
            raise SystemExit(
                f"NL2SQL_ROOT={root} 不像 NL2SQL 仓库根（缺少 nl2sql_core/ 或 configs/）"
            )
        return root

    cfg = _load_config()
    raw = cfg.get("nl2sql_root")
    if isinstance(raw, str) and raw.strip():
        root = Path(raw.strip()).expanduser().resolve()
        if not _looks_like_repo(root):
            raise SystemExit(
                f"config.json nl2sql_root={root} 不像 NL2SQL 仓库根（缺少 nl2sql_core/ 或 configs/）"
            )
        return root

    root = _default_repo_root().resolve()
    if not _looks_like_repo(root):
        raise SystemExit(
            "未找到 NL2SQL 仓库根。请任选其一：\n"
            f"  1) 复制 {_SCRIPTS_DIR / 'config.example.json'} 为 config.json，"
            "设置 nl2sql_root 为含 nl2sql_core/ 的绝对路径\n"
            "  2) export NL2SQL_ROOT=/path/to/NL2SQL-Agent\n"
            "  3) 将本 skill 保持在仓库内 opencode_plugin/skills/nl2sql/（默认相对路径）\n"
            f"当前默认推断: {root}"
        )
    return root


PKG_ROOT = resolve_pkg_root()
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

# 后续 import / 读写配置都相对仓库根
os.chdir(PKG_ROOT)

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
