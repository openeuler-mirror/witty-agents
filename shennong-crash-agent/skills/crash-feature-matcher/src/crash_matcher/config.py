"""全局配置 — 从 TOML 文件加载, Pydantic 校验."""

import os
import tomllib
from pathlib import Path

from .config_models import SkillConfig

_DEFAULT_CONFIG_PATH = Path(__file__).with_name("settings.toml")


def _overlay_env(data: dict) -> dict:
    """允许通过环境变量覆盖 TOML 中的关键配置."""
    env_map = {
        "RAG_BASE_URL": ("rag", "base_url"),
        "CRASH_KNOWLEDGE_KB_ID": ("rag", "knowledge_kb_id"),
        "CRASH_CASES_KB_ID": ("rag", "cases_kb_id"),
        "LINUX_COMMUNITY_KB_ID": ("rag", "linux_community_kb_id"),
        "OPENEULER_COMMUNITY_KB_ID": ("rag", "openeuler_community_kb_id"),
        "RAG_ACCESS_KEY": ("rag", "access_key"),
    }
    for env_key, (section, key) in env_map.items():
        value = os.environ.get(env_key)
        if value is not None:
            data.setdefault(section, {})[key] = value
    return data


class Config:
    """Skill configuration singleton.

    读取 TOML 配置文件; 当环境变量 ``CRASH_MATCHER_CONFIG`` 设置时优先使用该路径,
    否则使用默认 ``src/crash_matcher/settings.toml``.
    """

    _instance: "Config" = None
    _config: SkillConfig

    def __new__(cls) -> "Config":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        config_file = os.environ.get("CRASH_MATCHER_CONFIG")
        if config_file is None:
            config_path = _DEFAULT_CONFIG_PATH
        else:
            config_path = Path(config_file)
        with config_path.open("rb") as f:
            data = tomllib.load(f)
        data = _overlay_env(data)
        self._config = SkillConfig.model_validate(data)

    def get(self) -> SkillConfig:
        return self._config


def get_config() -> SkillConfig:
    """获取配置实例 (便于外部调用)."""
    return Config().get()
