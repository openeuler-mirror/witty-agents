# Copyright (c) Huawei Technologies Co., Ltd. 2023-2025. All rights reserved.
"""配置文件处理模块"""

import os
from copy import deepcopy
from pathlib import Path
import toml
from src.schemas.config import ConfigModel


class Config:
    """配置文件读取和使用Class"""

    _config: ConfigModel
    _default_config_path = Path(__file__).parent.parent / "common" / "config.toml"
    _user_config_dir = Path.home() / ".config" / "shennong-crash-agent"
    _user_config_path = _user_config_dir / "witty-log-detection-config.toml"

    def __init__(self) -> None:
        """读取配置文件；当PROD环境变量设置时，配置文件将在读取后删除"""
        config_file = os.getenv("CONFIG")
        if config_file is not None:
            base_data = toml.load(config_file)
        else:
            base_data = toml.load(self._default_config_path)

        # 用户自定义配置始终作为最终覆盖层生效
        if self._user_config_path.exists():
            user_data = toml.load(self._user_config_path)
            base_data = self._deep_merge(base_data, user_data)

        self._config = ConfigModel.model_validate(base_data)

    @classmethod
    def _deep_merge(cls, base: dict, override: dict) -> dict:
        """递归合并两个字典，override 优先级更高"""
        result = deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = cls._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @classmethod
    def get_user_config_path(cls) -> Path:
        """获取用户自定义配置文件路径"""
        return cls._user_config_path

    @classmethod
    def save_user_config(cls, embedding: dict, llm: dict) -> None:
        """保存用户自定义配置到 ~/.config/shennong-crash-agent/witty-log-detection-config.toml"""
        cls._user_config_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "EMBEDDING_MODEL": {
                "EMBEDDING_PROVIDER": embedding.get("provider", "openai"),
                "EMBEDDING_END_POINT": embedding.get("end_point", ""),
                "EMBEDDING_API_KEY": embedding.get("api_key", ""),
                "EMBEDDING_MODEL_NAME": embedding.get("model_name", ""),
                "EMBEDDING_BATCH_SIZE": embedding.get("batch_size", 64),
            },
            "LLM_MODEL": {
                "LLM_PROVIDER": llm.get("provider", "openai"),
                "LLM_END_POINT": llm.get("end_point", ""),
                "LLM_API_KEY": llm.get("api_key", ""),
                "LLM_MODEL_NAME": llm.get("model_name", ""),
                "LLM_MAX_TOKENS": llm.get("max_tokens", 32000),
                "LLM_BATCH_SIZE": llm.get("batch_size", 32),
            },
        }
        with cls._user_config_path.open("w", encoding="utf-8") as f:
            toml.dump(data, f)

    def get_config(self) -> ConfigModel:
        """获取配置文件内容"""
        return deepcopy(self._config)

    @staticmethod
    def _is_valid_credential(value: str | None) -> bool:
        """判断 API Key 是否已有效配置"""
        if not value:
            return False
        stripped = value.strip()
        placeholder_values = {"your_api_key", "your api key", "未配置", "placeholder", "sk-xxxx"}
        return stripped and stripped.lower() not in placeholder_values and len(stripped) > 4

    def is_embedding_configured(self) -> bool:
        """Embedding 配置是否已就绪"""
        cfg = self._config.embedding_model
        return self._is_valid_credential(cfg.api_key) and bool(cfg.end_point) and bool(cfg.model_name)

    def is_llm_configured(self) -> bool:
        """LLM 配置是否已就绪"""
        cfg = self._config.llm_model
        return self._is_valid_credential(cfg.api_key) and bool(cfg.end_point) and bool(cfg.model_name)

    @classmethod
    def build_config_prompt(cls) -> str:
        """构建首次使用的配置提示信息"""
        user_config_path = cls.get_user_config_path()
        return f"""日志检测 MCP 尚未配置 Embedding / LLM 模型密钥。

请在首次使用前完成以下配置（二选一）：

方式 1：调用 setup_log_detection_config 工具设置配置
方式 2：手动创建配置文件：{user_config_path}

示例配置内容：

[EMBEDDING_MODEL]
EMBEDDING_PROVIDER = "openai"
EMBEDDING_END_POINT = "https://api.siliconflow.cn/v1/embeddings"
EMBEDDING_API_KEY = "your-api-key"
EMBEDDING_MODEL_NAME = "BAAI/bge-m3"
EMBEDDING_BATCH_SIZE = 64

[LLM_MODEL]
LLM_PROVIDER = "openai"
LLM_END_POINT = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_API_KEY = "your-api-key"
LLM_MODEL_NAME = "qwen3-max"
LLM_MAX_TOKENS = 32000
LLM_BATCH_SIZE = 32

配置完成后重新调用日志检测任务即可。
"""
