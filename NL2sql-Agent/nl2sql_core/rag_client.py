from __future__ import annotations

from typing import Any, Optional

import httpx

from nl2sql_core.config import RagSettings, load_rag_settings


class RagClient:
    """调用本目录 vendor/rag_core 暴露的 HTTP API。"""

    def __init__(self, settings: Optional[RagSettings] = None):
        self.settings = settings or load_rag_settings()

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.access_key}",
        }

    async def health(self) -> dict[str, Any]:
        url = f"{self.settings.base_url.rstrip('/')}/kb/list"
        async with httpx.AsyncClient(timeout=self.settings.timeout_sec) as client:
            try:
                r = await client.post(url, headers=self._headers(), json={"page_num": 1, "page_size": 1})
                return {"ok": r.status_code < 500, "status_code": r.status_code, "body": r.text[:500]}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    async def list_kb(self, *, name: str | None = None, page_size: int = 50) -> list[dict[str, Any]]:
        url = f"{self.settings.base_url.rstrip('/')}/kb/list"
        payload: dict[str, Any] = {"page_num": 1, "page_size": page_size}
        if name:
            payload["name"] = name
        async with httpx.AsyncClient(timeout=self.settings.timeout_sec) as client:
            r = await client.post(url, headers=self._headers(), json=payload)
            r.raise_for_status()
            data = r.json()
            result = data.get("result") or {}
            return list(result.get("knowledge_bases") or [])

    async def ensure_json_kb(self, name: str, description: str = "") -> str:
        for kb in await self.list_kb(name=name, page_size=100):
            if kb.get("name") == name and kb.get("meta_data_type") == "json":
                return str(kb.get("id") or "")
        return await self.create_json_kb(name, description)

    async def create_json_kb(self, name: str, description: str = "") -> str:
        url = f"{self.settings.base_url.rstrip('/')}/kb"
        payload = {
            "name": name,
            "description": description,
            "meta_data_type": "json",
        }
        async with httpx.AsyncClient(timeout=self.settings.timeout_sec) as client:
            r = await client.post(url, headers=self._headers(), json=payload)
            r.raise_for_status()
            data = r.json()
            return data.get("result", {}).get("kb_id") or data.get("kb_id") or ""

    async def upsert_rule(self, kb_id: str, name: str, content: dict[str, Any], *, immediate: bool = True) -> Any:
        url = f"{self.settings.base_url.rstrip('/')}/json/{kb_id}"
        payload = {
            "name": name,
            "content": content,
            "is_imediate": immediate,  # rag-core 源码拼写
        }
        async with httpx.AsyncClient(timeout=max(self.settings.timeout_sec, 120)) as client:
            r = await client.post(url, headers=self._headers(), json=payload)
            r.raise_for_status()
            return r.json()

    async def search_rules(
        self,
        kb_id: str,
        query: str = "",
        *,
        database_id: str | None = None,
        rule_type: str | None = None,
        scope: str | None = None,
        dialects: list[str] | None = None,
        top_k: int = 10,
    ) -> Any:
        expressions: list[dict[str, Any]] = []
        if database_id:
            expressions.append(
                {"field": ["database_id"], "operator": "eq", "value": database_id}
            )
        if rule_type:
            expressions.append(
                {"field": ["rule_type"], "operator": "eq", "value": rule_type}
            )
        if scope:
            expressions.append(
                {"field": ["scope"], "operator": "eq", "value": scope}
            )
        if dialects:
            if len(dialects) == 1:
                expressions.append(
                    {"field": ["dialect"], "operator": "eq", "value": dialects[0]}
                )
            else:
                expressions.append(
                    {"field": ["dialect"], "operator": "in", "value": list(dialects)}
                )
        logical = None
        if expressions:
            logical = {"operator": "and", "expressions": expressions}

        config: dict[str, Any] = {
            "kb_id": kb_id,
            "query": query,
            "top_k": top_k,
            "ratio": 0.45,
            "semantic_keys": [
                ["description"],
                ["query"],
                ["table"],
                ["col"],
                ["sql"],
                ["ddl"],
                ["rule_type"],
                ["scope"],
                ["dialect"],
            ],
        }
        if logical:
            config["logical_expression"] = logical

        url = f"{self.settings.base_url.rstrip('/')}/json/search"
        async with httpx.AsyncClient(timeout=self.settings.timeout_sec) as client:
            r = await client.post(
                url,
                headers=self._headers(),
                json={"search_json_configs": [config]},
            )
            r.raise_for_status()
            return r.json()
