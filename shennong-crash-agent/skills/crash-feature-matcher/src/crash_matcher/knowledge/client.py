"""euler-copilot-rag HTTP 客户端"""

import asyncio
import logging
from typing import Optional

import httpx

from ..config import Config
from ..config_models import SearchConfig, Expression, LogicalExpression
from ..models import CrashIssue, CrashCase, CommunityCase

logger = logging.getLogger(__name__)


class RAGClient:
    """euler-copilot-rag JSON 知识库客户端"""

    def __init__(self, base_url="", knowledge_kb_id="", cases_kb_id="", access_key="",
                 linux_kb_id="", openeuler_kb_id="", timeout: float = 0):
        rag_cfg = Config().get().rag
        self.base_url = (base_url or rag_cfg.base_url).rstrip("/")
        self.knowledge_kb_id = knowledge_kb_id or rag_cfg.knowledge_kb_id
        self.cases_kb_id = cases_kb_id or rag_cfg.cases_kb_id
        self.access_key = access_key or rag_cfg.access_key
        self.linux_kb_id = linux_kb_id or rag_cfg.linux_community_kb_id
        self.openeuler_kb_id = openeuler_kb_id or rag_cfg.openeuler_community_kb_id
        self.timeout = timeout or rag_cfg.timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout,
                headers={"access-key": self.access_key, "Content-Type": "application/json"},
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ============================================================
    # 通用搜索: 一次 POST 多个 config, 返回 {result_N: [dict]}
    # ============================================================

    async def search_configs(self, configs: list[SearchConfig]) -> list[dict]:
        """POST /json/search, 返回 RAG json 文档列表 (每个 item 的 content 字段)"""
        url = "/json/search"
        payload = {"search_json_configs": [c.to_dict() for c in configs], "need_trace": False}
        try:
            resp = await self.client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result", data)
            jsons = result.get("jsons", result.get("results", [])) if isinstance(result, dict) else []
            # 提取 content
            items = []
            for j in jsons:
                c = j.get("content", j)
                if isinstance(c, dict):
                    items.append(c)
            return items
        except Exception as e:
            logger.error(f"RAG 搜索失败: {e}")
            return []

    # ============================================================
    # Issue 搜索 (crash_knowledge)
    # ============================================================

    async def search_issues_semantic(self, query_text: str, bug_type: str = "", top_k: int = 5) -> list[CrashIssue]:
        expressions = [
            Expression(field="source", type="string", operator="eq", value="issue"),
        ]
        if bug_type:
            expressions.append(Expression(field="bug_type", type="string", operator="eq", value=bug_type))
        cfg = SearchConfig(
            kb_id=self.knowledge_kb_id, query=query_text, top_k=top_k,
            logical_expression=LogicalExpression(operator="and", expressions=expressions),
            semantic_keys=[["call_trace_text"], ["bug_summary"], ["root_cause"]],
            ratio=0.3,
        )
        items = await self.search_configs([cfg])
        return [_to_issue(item) for item in items if _to_issue(item)]

    async def search_issues_by_rip_function(
        self, rip_function: str, bug_type: str = "", top_k: int = 5
    ) -> list[CrashIssue]:
        expressions = [
            Expression(field="source", type="string", operator="eq", value="issue"),
            Expression(field="rip_function", type="string", operator="like", value=rip_function),
        ]
        if bug_type:
            expressions.append(Expression(field="bug_type", type="string", operator="eq", value=bug_type))
        cfg = SearchConfig(
            kb_id=self.knowledge_kb_id, query="", top_k=top_k,
            logical_expression=LogicalExpression(operator="and", expressions=expressions),
            semantic_keys=[], ratio=0.3,
        )
        items = await self.search_configs([cfg])
        return [_to_issue(item) for item in items if _to_issue(item)]

    # ============================================================
    # Case 搜索 (crash_cases)
    # ============================================================

    async def search_cases_by_knowledge_id(self, knowledge_id: str, limit: int = 10) -> list[CrashCase]:
        cfg = SearchConfig(
            kb_id=self.cases_kb_id, query="", top_k=limit,
            logical_expression=LogicalExpression(operator="and", expressions=[
                Expression(field="source", type="string", operator="eq", value="case"),
                Expression(field="knowledge_id", type="string", operator="eq", value=knowledge_id),
            ]),
            semantic_keys=[],
        )
        items = await self.search_configs([cfg])
        return [_to_case(item) for item in items if _to_case(item)]

    async def search_cases_semantic(self, query_text: str, limit: int = 5) -> list[CrashCase]:
        cfg = SearchConfig(
            kb_id=self.cases_kb_id, query=query_text, top_k=limit,
            logical_expression=LogicalExpression(operator="and", expressions=[
                Expression(field="source", type="string", operator="eq", value="case"),
            ]),
            semantic_keys=[["call_trace"], ["bug"]], ratio=0.3,
        )
        items = await self.search_configs([cfg])
        return [_to_case(item) for item in items if _to_case(item)]

    # ============================================================
    # 社区案例搜索 (L1/L2/L3)
    # ============================================================

    async def search_community_cases(
        self, kb_id: str, query_text: str, kernel_version: str = "",
        source: str = "", top_k: int = 5, semantic_keys: list[list[str]] = None
    ) -> list[CommunityCase]:
        """在社区 KB 中基于 source 逻辑过滤 + content 语义检索, kernel_version 在检索后本地过滤"""
        if not kb_id:
            return []
        expressions: list[Expression] = []
        if source:
            expressions.append(Expression(field="source", type="string", operator="eq", value=source))
        # kernel_version 不再作为 RAG 逻辑表达式, 改为检索后本地过滤 (empty OR >=)

        cfg = SearchConfig(
            kb_id=kb_id,
            query=query_text,
            top_k=top_k,
            logical_expression=LogicalExpression(operator="and", expressions=expressions) if expressions else None,
            semantic_keys=semantic_keys or [["content"], ["title"], ["phenomenon"]],
            ratio=0.3,
        )
        items = await self.search_configs([cfg])
        return [_to_community_case(item, kb_id) for item in items if _to_community_case(item, kb_id)]

    async def search_community_cases_multi(
        self,
        kb_id: str,
        queries: list[str],
        kernel_version: str = "",
        source: str = "",
        top_k: int = 5,
        semantic_keys: list[list[str]] = None,
    ) -> list[CommunityCase]:
        """Multi-query fusion: search several query variants and merge via RRF."""
        if not kb_id or not queries:
            return []

        # Run all variants concurrently
        results_per_query = await asyncio.gather(*[
            self.search_community_cases(
                kb_id, q, kernel_version, source, top_k, semantic_keys
            )
            for q in queries
        ])

        # Reciprocal Rank Fusion (RRF), k=60
        k = 60
        scores: dict[str, float] = {}
        cases_by_id: dict[str, CommunityCase] = {}
        for case_list in results_per_query:
            for rank, case in enumerate(case_list, start=1):
                cid = case.id or case.json_id or case.title
                if not cid:
                    continue
                scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
                # Keep the case object (first occurrence)
                if cid not in cases_by_id:
                    cases_by_id[cid] = case

        # Sort by RRF score descending and return top_k
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        return [cases_by_id[cid] for cid in sorted_ids[:top_k]]

    async def search_linux_community_cases(
        self, query_text: str, kernel_version: str = "", top_k: int = 5,
        queries: list[str] = None
    ) -> list[CommunityCase]:
        """检索 Linux 社区案例；支持多查询融合。"""
        search_queries = queries or ([query_text] if query_text else [])
        return await self.search_community_cases_multi(
            self.linux_kb_id, search_queries, kernel_version,
            source="Linux社区", top_k=top_k
        )

    async def search_openeuler_community_cases(
        self, query_text: str, kernel_version: str = "", top_k: int = 5,
        queries: list[str] = None
    ) -> list[CommunityCase]:
        """检索 openEuler 社区案例；支持多查询融合。"""
        search_queries = queries or ([query_text] if query_text else [])
        return await self.search_community_cases_multi(
            self.openeuler_kb_id, search_queries, kernel_version,
            source="openEuler社区", top_k=top_k
        )

    # ============================================================
    # 写入
    # ============================================================

    async def create_issue(self, issue: CrashIssue) -> str:
        data = issue.model_dump()
        data["source"] = "issue"
        return await self._create_json(self.knowledge_kb_id, data)

    async def create_case(self, case: CrashCase) -> str:
        data = case.model_dump()
        data["source"] = "case"
        return await self._create_json(self.cases_kb_id, data)

    async def _create_json(self, kb_id: str, content: dict) -> str:
        url = f"/json/{kb_id}"
        payload = {"name": content.get("knowledge_id", content.get("case_id", "unknown")), "content": content, "is_imediate": True}
        try:
            resp = await self.client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result", data)
            return result.get("json_id", "") if isinstance(result, dict) else ""
        except Exception as e:
            logger.error(f"RAG 创建失败: {e}")
            return ""


def _to_issue(data: dict) -> Optional[CrashIssue]:
    if isinstance(data, CrashIssue):
        return data
    if not isinstance(data, dict):
        return None
    try:
        # 兼容旧 signature → fingerprints 迁移
        if "signature" in data and "fingerprints" not in data:
            data = dict(data)
            data["fingerprints"] = [data.pop("signature")]
        return CrashIssue(**data)
    except Exception:
        return None


def _to_case(data: dict) -> Optional[CrashCase]:
    if isinstance(data, CrashCase):
        return data
    if not isinstance(data, dict):
        return None
    try:
        return CrashCase(**data)
    except Exception:
        return None


def _to_community_case(data: dict, kb_id: str = "") -> Optional[CommunityCase]:
    if isinstance(data, CommunityCase):
        return data
    if not isinstance(data, dict):
        return None
    try:
        d = dict(data)
        d["kb_id"] = kb_id
        d["json_id"] = d.get("json_id", "")
        # 兼容 OSClinic CrashIssue 格式
        if not d.get("title") and d.get("bug_summary"):
            d["title"] = d["bug_summary"]
        if not d.get("id") and d.get("knowledge_id"):
            d["id"] = d["knowledge_id"]
        if not d.get("phenomenon") and d.get("call_trace_text"):
            d["phenomenon"] = d["call_trace_text"]
        if not d.get("content"):
            d["content"] = "\n".join([
                d.get("bug_summary", ""),
                d.get("root_cause", ""),
                d.get("solution", ""),
                d.get("call_trace_text", ""),
            ]).strip()
        # kernel_versions(list) -> kernel_version(string)
        kvs = d.get("kernel_versions")
        if kvs and not d.get("kernel_version"):
            d["kernel_version"] = kvs[0] if isinstance(kvs, list) else str(kvs)
        # source_url -> source_file (shennong 对齐)
        if not d.get("source_file") and d.get("source_url"):
            d["source_file"] = d["source_url"]
        # match_score: score/100 (shennong 对齐, 0-1 归一化)
        if not d.get("match_score") and d.get("score"):
            d["match_score"] = round(float(d["score"]) / 100.0, 4)
        return CommunityCase(**d)
    except Exception:
        return None
