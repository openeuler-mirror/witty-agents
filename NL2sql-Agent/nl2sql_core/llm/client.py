from __future__ import annotations

from typing import Any, Optional

from openai import AsyncOpenAI

from nl2sql_core.config import LLMSettings


class LLMClient:
    def __init__(self, settings: Optional[LLMSettings] = None):
        self.settings = settings or LLMSettings()
        self._client = AsyncOpenAI(
            api_key=self.settings.api_key or "EMPTY",
            base_url=self.settings.base_url,
        )

    async def chat(self, system: str, user: str, *, temperature: float = 0.0) -> str:
        resp = await self._client.chat.completions.create(
            model=self.settings.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # DashScope / Qwen3 非流式必须关闭 thinking，否则 400
            extra_body={"enable_thinking": False},
        )
        return (resp.choices[0].message.content or "").strip()
