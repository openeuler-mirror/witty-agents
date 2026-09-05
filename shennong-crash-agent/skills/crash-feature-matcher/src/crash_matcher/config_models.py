"""Pydantic models for skill configuration and RAG search configs."""

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class Expression(BaseModel):
    """RAG JSON search logical expression leaf."""

    field: str
    type: str
    operator: str
    value: Any


class LogicalExpression(BaseModel):
    """RAG JSON search logical expression node."""

    operator: str
    expressions: list[Expression]


class SearchConfig(BaseModel):
    """RAG /json/search payload item."""

    kb_id: str
    query: str
    top_k: int
    logical_expression: Optional[LogicalExpression] = None
    semantic_keys: list[list[str]] = Field(default_factory=list)
    ratio: float = 0.3

    def to_dict(self) -> dict:
        d = {
            "kb_id": self.kb_id,
            "query": self.query,
            "top_k": self.top_k,
            "semantic_keys": self.semantic_keys,
            "ratio": self.ratio,
        }
        if self.logical_expression is not None:
            d["logical_expression"] = {
                "operator": self.logical_expression.operator,
                "expressions": [
                    {
                        "field": e.field,
                        "type": e.type,
                        "operator": e.operator,
                        "value": e.value,
                    }
                    for e in self.logical_expression.expressions
                ],
            }
        return d


class L2SearchRule(BaseModel):
    """L2 search strategy rule."""

    bug_key_patterns: list[str]
    query_from: str
    search_mode: str
    ratio: float = 0.3
    semantic_keys: list[list[str]] = Field(default_factory=list)
    filter_bug_type: bool = True
    strategy: str = "stack_similarity"

    @field_validator("semantic_keys", mode="before")
    @classmethod
    def _ensure_list_of_lists(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [[v]]
        return list(v)


class RagConfig(BaseModel):
    """RAG service connection configuration."""

    base_url: str = "http://localhost:9988"
    knowledge_kb_id: str = ""
    cases_kb_id: str = ""
    linux_community_kb_id: str = ""
    openeuler_community_kb_id: str = ""
    access_key: str = ""
    timeout: float = 30.0


class MatcherConfig(BaseModel):
    """Crash matching engine configuration."""

    stack_similarity_threshold: float = 0.75
    dmesg_analysis_window_seconds: int = 180
    max_log_line_in_db: int = 300
    rip_fuzzy_offset: int = 8


class CommunityConfig(BaseModel):
    """Community case retrieval configuration."""

    score_threshold: int = 80  # 向后兼容，当前由 l1_threshold 接管
    top_k_final: int = 3
    l1_top_k: int = 5          # L1 每社区召回数，适当放大以提升准确率
    l3_top_k: int = 8          # L3 每社区召回数，扩大召回面

    scoring_mode: str = Field(default="keyword", description="keyword | llm | hybrid")

    # 分模式的 L1/L2 阈值：keyword 天然偏低，llm 偏高
    keyword_l1_threshold: int = Field(default=60, description="keyword 模式 L1 停止阈值")
    keyword_l2_threshold: int = Field(default=45, description="keyword 模式 L2 进入阈值")
    llm_l1_threshold: int = Field(default=75, description="llm 模式 L1 停止阈值")
    llm_l2_threshold: int = Field(default=55, description="llm 模式 L2 进入阈值")
    hybrid_l1_threshold: int = Field(default=70, description="hybrid 模式 L1 停止阈值")
    hybrid_l2_threshold: int = Field(default=50, description="hybrid 模式 L2 进入阈值")

    # 多查询融合：把原始 query 扩展成几个变体分别检索，再合并去重
    enable_query_expansion: bool = Field(default=True)
    expansion_variants: int = Field(default=3, description="扩展出的 query 变体数量")
    expansion_include_kernel: bool = Field(default=True, description="是否把 kernel_version 拼入 query")
    expansion_include_english: bool = Field(default=True, description="是否生成英文技术变体")

    # Advanced retrieval options
    advanced: dict = Field(default_factory=lambda: {
        "enable_iterative_retrieval": False,
        "max_iteration_rounds": 3,
        "enable_llm_query_generation": False,
        "logical_expression_strategy": "semantic_only",
    })
    commit_analysis: dict = Field(default_factory=lambda: {
        "enabled": True,
        "max_commits_to_analyze": 5,
        "confirmed_boost": 1.15,
        "irrelevant_penalty": 0.5,
    })
    # Online fallback: when community KBs are unconfigured or return nothing,
    # search upstream kernel commits via the lightweight REST commits API
    # (no git clone). Candidates get a baseline score and must pass the
    # first-hand diff verification (commit_analysis) before reaching the report.
    online_fallback: dict = Field(default_factory=lambda: {
        "enabled": True,
        "repo": "openeuler/kernel",
        "source": "gitcode",       # gitcode | gitee
        "max_pages": 5,
        "max_candidates": 8,
        "baseline_score": 50.0,
        "source_label": "openEuler社区",
        # LLM-generate Chinese phenomenon/root_cause/solution for verified
        # `confirmed` commits (RAG hits + online fallback; best-effort, English
        # content untouched on failure, already-Chinese docs skipped)
        "summarize_confirmed": True,
        # persist online-verified `confirmed` commits into the community KB
        # (dedup by commit sha) so future analyses hit them via RAG retrieval
        "persist_confirmed": True,
    })


class LLMScorerConfig(BaseModel):
    """LLM-based scorer configuration."""

    enabled: bool = Field(default=False)
    api_key: str = Field(default="")
    base_url: str = Field(default="https://api.siliconflow.cn/v1")
    model: str = Field(default="Qwen/Qwen2.5-7B-Instruct")
    timeout: float = Field(default=60.0)
    temperature: float = Field(default=0.1)
    max_tokens: int = Field(default=256)
    prompt_template: str = Field(default="", description="Scoring prompt template")
    # hybrid mode weight: final = keyword_weight * keyword_score + llm_weight * llm_score
    keyword_weight: float = Field(default=0.3)
    llm_weight: float = Field(default=0.7)


class SkillConfig(BaseModel):
    """Top-level skill configuration loaded from TOML."""

    rag: RagConfig = Field(default_factory=RagConfig)
    matcher: MatcherConfig = Field(default_factory=MatcherConfig)
    community: CommunityConfig = Field(default_factory=CommunityConfig)
    llm_scorer: LLMScorerConfig = Field(default_factory=LLMScorerConfig)
    l2_search_rules: list[L2SearchRule] = Field(default_factory=list)

    @field_validator("l2_search_rules", mode="before")
    @classmethod
    def _default_l2_rules(cls, v):
        if v:
            return v
        return [
            L2SearchRule(
                bug_key_patterns=[
                    "NULL pointer dereference",
                    "kernel paging request",
                    "page fault for address",
                    "general protection fault",
                    "stack guard page was hit",
                    "NX-protected page",
                    "execute userspace code",
                    "Corrupted page table",
                    "WARNING",
                ],
                query_from="rip_function",
                search_mode="like",
                strategy="exact_rip_with_bugkey",
            ),
            L2SearchRule(
                bug_key_patterns=["hard LOCKUP", "soft lockup"],
                query_from="rip_function",
                search_mode="like",
                strategy="fuzzy_rip_offset",
            ),
            L2SearchRule(
                bug_key_patterns=["invalid opcode"],
                query_from="rip_function",
                search_mode="like",
                strategy="exact_rip_with_bugkey",
            ),
            L2SearchRule(
                bug_key_patterns=["kernel BUG at"],
                query_from="call_trace_top",
                search_mode="like",
                strategy="match_bug_function",
            ),
            L2SearchRule(
                bug_key_patterns=["list_add corruption", "list_del corruption"],
                query_from="rip_function",
                search_mode="like",
                filter_bug_type=False,
                strategy="exact_rip_with_bugkey",
            ),
            L2SearchRule(
                bug_key_patterns=[
                    "Bad page map",
                    "Bad page state",
                    "KASAN:",
                    "KFENCE:",
                    "rcu_sched",
                    "rcu_preempt",
                    "blocked",
                    "double fault",
                ],
                query_from="call_trace_text",
                search_mode="semantic",
                semantic_keys=[["call_trace_text"]],
                strategy="stack_similarity",
            ),
            L2SearchRule(
                bug_key_patterns=["*"],
                query_from="call_trace_text",
                search_mode="semantic",
                semantic_keys=[["call_trace_text"]],
                strategy="stack_similarity",
            ),
        ]
