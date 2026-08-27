"""社区案例检索 — Linux/openEuler 社区 L1/L2/L3"""

import logging
import re
from typing import Optional
from ..config import Config
from ..models import CommunityCase, CommunityMatchResult, ScoreDetails
from ..knowledge.client import RAGClient
from ..utils.text_similarity import (
    get_term_set, jaccard_similarity, exact_english_overlap
)
from .query_expansion import expand_query

logger = logging.getLogger(__name__)


def _community_cfg():
    return Config().get().community


def _llm_scorer():
    cfg = Config().get().llm_scorer
    if not cfg.enabled:
        return None
    from ..llm_scorer import LLMScorer
    return LLMScorer()


def _get_thresholds(cfg):
    """Return (l1_threshold, l2_threshold) for current scoring_mode."""
    mode = cfg.scoring_mode
    if mode == "llm":
        return cfg.llm_l1_threshold, cfg.llm_l2_threshold
    if mode == "hybrid":
        return cfg.hybrid_l1_threshold, cfg.hybrid_l2_threshold
    return cfg.keyword_l1_threshold, cfg.keyword_l2_threshold


async def retrieve_community_cases(
    query_text: str,
    kernel_version: str = "",
    rag: Optional[RAGClient] = None,
    anomaly_features: dict = None,
) -> CommunityMatchResult:
    """
    检索规则:
      - L1: Linux 社区 + openEuler 社区, 按 kernel_version 逻辑过滤, 各取 top_k。
      - L2: 对 L1 结果二次确认。
      - L3: 若 L2 未命中, 扩大召回, Linux + openEuler 社区各取更多 top_k, 返回分数最高 top3。

    改进点:
      - 使用 query_expansion 生成多个 query 变体, multi-query fusion (RRF) 提升召回准确率。
      - keyword / llm / hybrid 各自使用适配的 L1/L2 阈值。
      - L1/L3 top_k 可配置, 默认适度放大。
    """
    if not rag:
        return CommunityMatchResult(stop_reason="未配置 RAG 客户端")

    cfg = _community_cfg()
    scorer = _llm_scorer()
    l1_threshold, l2_threshold = _get_thresholds(cfg)
    candidates: list[CommunityCase] = []
    stop_reason = ""

    # Query expansion: 生成多个搜索变体
    queries = expand_query(query_text, kernel_version, anomaly_features)
    if len(queries) > 1:
        logger.debug(f"Query expanded into {len(queries)} variants: {queries}")

    # L1: RAG 语义检索, 各社区 top_k, 检索后进行 kernel_version 本地过滤
    linux_l1 = await rag.search_linux_community_cases(
        "", kernel_version, top_k=cfg.l1_top_k, queries=queries
    )
    openeuler_l1 = await rag.search_openeuler_community_cases(
        "", kernel_version, top_k=cfg.l1_top_k, queries=queries
    )
    for c in linux_l1:
        c.match_level = "L1"
    for c in openeuler_l1:
        c.match_level = "L1"

    # 根据 scoring_mode 打分
    if cfg.scoring_mode == "llm" and scorer:
        linux_l1 = await scorer.score_cases(query_text, linux_l1)
        openeuler_l1 = await scorer.score_cases(query_text, openeuler_l1)
    else:
        for c in linux_l1:
            c.score, c.score_details = _score_case(query_text, kernel_version, c)
        for c in openeuler_l1:
            c.score, c.score_details = _score_case(query_text, kernel_version, c)

    # L1 本地 kernel_version 过滤 (empty OR >=)
    linux_l1 = _filter_by_kernel_version(linux_l1, kernel_version)
    openeuler_l1 = _filter_by_kernel_version(openeuler_l1, kernel_version)

    l1_over = [c for c in linux_l1 + openeuler_l1 if c.score > l1_threshold]
    if l1_over:
        candidates = l1_over
        stop_reason = f"L1 社区案例命中高分(>{l1_threshold})"
    else:
        # L2: 二次确认
        if cfg.scoring_mode == "llm" and scorer:
            l2_confirmed = [c for c in linux_l1 + openeuler_l1 if c.score >= l2_threshold]
        else:
            l2_confirmed = [c for c in linux_l1 + openeuler_l1 if _secondary_confirm(query_text, kernel_version, c, l2_threshold)]
        if l2_confirmed:
            for c in l2_confirmed:
                c.match_level = "L2"
            candidates = l2_confirmed
            stop_reason = "L2 社区案例二次确认命中"
        else:
            # L3: 扩大召回, 各社区 top_k
            linux_l3 = await rag.search_linux_community_cases(
                "", kernel_version, top_k=cfg.l3_top_k, queries=queries
            )
            openeuler_l3 = await rag.search_openeuler_community_cases(
                "", kernel_version, top_k=cfg.l3_top_k, queries=queries
            )
            for c in linux_l3:
                c.match_level = "L3"
            for c in openeuler_l3:
                c.match_level = "L3"

            if cfg.scoring_mode == "llm" and scorer:
                linux_l3 = await scorer.score_cases(query_text, linux_l3)
                openeuler_l3 = await scorer.score_cases(query_text, openeuler_l3)
            else:
                for c in linux_l3:
                    c.score, c.score_details = _score_case(query_text, kernel_version, c)
                for c in openeuler_l3:
                    c.score, c.score_details = _score_case(query_text, kernel_version, c)

            # L3 本地 kernel_version 过滤 (empty OR >=)
            linux_l3 = _filter_by_kernel_version(linux_l3, kernel_version)
            openeuler_l3 = _filter_by_kernel_version(openeuler_l3, kernel_version)
            candidates = linux_l3 + openeuler_l3
            stop_reason = "L3 Linux社区 + openEuler社区 扩大召回"

    candidates.sort(key=lambda x: x.score, reverse=True)
    final_cases = candidates[:cfg.top_k_final]

    if cfg.scoring_mode == "hybrid" and scorer:
        final_cases = await _hybrid_score(query_text, kernel_version, final_cases, scorer)
        candidates[:cfg.top_k_final] = final_cases
        candidates.sort(key=lambda x: x.score, reverse=True)

    # Build match_reason for each final case
    for case in final_cases:
        case.match_reason = _build_community_match_reason(query_text, kernel_version, case)

    # Analyze commit relevance for each final case (改动三)
    _cfg = Config().get()
    commit_cfg = getattr(_cfg, 'commit_analysis', None)
    if commit_cfg and commit_cfg.get('enabled', False) and final_cases:
        try:
            from ..git_commit_fetcher import analyze_commit_relevance
            for case in final_cases[:commit_cfg.get('max_commits_to_analyze', 5)]:
                if case.source_file:
                    relevance = await analyze_commit_relevance(case, query_text)
                    if relevance.get("relevant") is False:
                        case.score *= 0.5
                        case.match_reason["commit_relevance"] = f"commit 不相关: {relevance.get('reason', '')}"
                    else:
                        case.match_reason["commit_relevance"] = relevance.get("reason", "")
        except Exception:
            logger.debug("commit analysis failed", exc_info=True)

    if scorer:
        await scorer.close()

    return CommunityMatchResult(
        matched=bool(final_cases),
        stop_reason=stop_reason,
        cases=final_cases,
        total_candidates=len(candidates),
    )


async def _hybrid_score(
    query_text: str,
    kernel_version: str,
    cases: list[CommunityCase],
    scorer,
) -> list[CommunityCase]:
    """hybrid mode: 先用 LLM 打分，再与 keyword 分数加权。"""
    cfg = Config().get().llm_scorer
    llm_cases = await scorer.score_cases(query_text, cases)
    for c in llm_cases:
        kw_score, _ = _score_case(query_text, kernel_version, c)
        final = cfg.keyword_weight * kw_score + cfg.llm_weight * c.score
        c.score = round(final, 2)
        if c.score_details:
            c.score_details.total = c.score
    return llm_cases


def _score_case(query_text: str, kernel_version: str, case: CommunityCase) -> tuple[float, ScoreDetails]:
    """
    Custom scoring (0-100) using jieba + Jaccard + synonyms:
      - Exact kernel_version match: +30
      - kernel_version prefix/major-version match: +15~20
      - Title Jaccard overlap: +25
      - Content/phenomenon/root_cause Jaccard overlap: +25
      - Exact English/technical token matches: +25 (capped)
      - Has solution: +10
    """
    query_terms = get_term_set(query_text, use_synonyms=True)
    title_terms = get_term_set(case.title, use_synonyms=False)
    content_terms = get_term_set(
        case.content + " " + case.phenomenon + " " + case.root_cause, use_synonyms=False
    )

    kv_score = _kernel_version_score(kernel_version, case.kernel_version)
    title_score = jaccard_similarity(query_terms, title_terms) * 25
    content_score = jaccard_similarity(query_terms, content_terms) * 25

    # Exact English/technical token matches (e.g., function names, module names)
    exact_overlap = exact_english_overlap(query_text, case.title + " " + case.content)
    exact_score = min(25, exact_overlap * 6)

    solution_score = 10 if case.solution else 0

    total = kv_score + title_score + content_score + exact_score + solution_score
    total = min(100.0, total)
    case.match_score = round(total / 100.0, 4)  # shennong 对齐: 0-1 归一化
    details = ScoreDetails(
        kernel_version_score=kv_score,
        title_score=round(title_score, 2),
        content_score=round(content_score, 2),
        exact_token_score=exact_score,
        solution_score=solution_score,
        total=round(total, 2),
    )
    return total, details


def _secondary_confirm(query_text: str, kernel_version: str, case: CommunityCase, l2_threshold: int = 60) -> bool:
    """Secondary confirmation: high score, or moderate score with strong overlap."""
    score, details = _score_case(query_text, kernel_version, case)
    if score >= l2_threshold + 15:  # L2 上限附近直接确认
        return True
    if score < l2_threshold - 15:   # 过低不确认
        return False
    query_terms = get_term_set(query_text, use_synonyms=True)
    title_terms = get_term_set(case.title, use_synonyms=False)
    content_terms = get_term_set(
        case.content + " " + case.phenomenon + " " + case.root_cause, use_synonyms=False
    )
    title_overlap = len(query_terms & title_terms)
    content_overlap = len(query_terms & content_terms)
    kv_exact = bool(kernel_version and case.kernel_version and kernel_version.strip().lower() == case.kernel_version.strip().lower())
    exact_tokens = exact_english_overlap(query_text, case.title + " " + case.content)
    return kv_exact or (title_overlap >= 2) or (content_overlap >= 3) or (exact_tokens >= 2)


def _kernel_version_score(q_kv: str, c_kv: str) -> float:
    if not q_kv or not c_kv:
        return 0.0
    q_kv = q_kv.strip().lower()
    c_kv = c_kv.strip().lower()
    if q_kv == c_kv:
        return 30.0
    if c_kv.startswith(q_kv) or q_kv.startswith(c_kv):
        return 20.0
    q_major = ".".join(q_kv.split(".")[:2])
    c_major = ".".join(c_kv.split(".")[:2])
    if q_major and c_major and q_major == c_major:
        return 15.0
    return 0.0


def _parse_kernel_version(kv: str):
    """Parse kernel version string into integer tuple for comparison.

    '6.6.0-82.0.0.mt20250613' -> (6, 6, 0)
    '5.10.0-136.71.0' -> (5, 10, 0)
    '5.9-rc4' -> (5, 9)
    '' -> None
    """
    if not kv or not kv.strip():
        return None
    kv = kv.strip()
    m = re.match(r'^(\d+(?:\.\d+)*)', kv)
    if not m:
        return None
    return tuple(int(x) for x in m.group(1).split('.'))


def _kernel_version_gte(query_kv: str, case_kv: str) -> bool:
    """Check if case kernel_version >= query kernel_version (numeric comparison)."""
    q_ver = _parse_kernel_version(query_kv)
    c_ver = _parse_kernel_version(case_kv)
    if q_ver is None or c_ver is None:
        return False
    max_len = max(len(q_ver), len(c_ver))
    q_padded = list(q_ver) + [0] * (max_len - len(q_ver))
    c_padded = list(c_ver) + [0] * (max_len - len(c_ver))
    return c_padded >= q_padded


def _filter_by_kernel_version(cases: list[CommunityCase], query_kv: str) -> list[CommunityCase]:
    """
    Filter cases: keep those where kernel_version is empty (universal fix)
    OR case kernel_version >= query kernel_version (same or newer kernel).
    """
    if not query_kv:
        return cases
    return [c for c in cases if not c.kernel_version or _kernel_version_gte(query_kv, c.kernel_version)]


def _build_community_match_reason(query_text: str, kernel_version: str, case: CommunityCase) -> dict:
    """Build human-readable match reason for a community case."""
    reasons: dict[str, str] = {}

    score_details = case.score_details
    if score_details and score_details.total > 0:
        if score_details.title_score > 10:
            reasons["phenomenon_similarity"] = f"标题相似度较高 (得分: {score_details.title_score:.1f})"
        if score_details.content_score > 10:
            reasons["content_similarity"] = f"内容/现象/根因描述匹配 (得分: {score_details.content_score:.1f})"
        if score_details.exact_token_score > 5:
            reasons["exact_token_match"] = f"技术关键词精确命中 (得分: {score_details.exact_token_score:.1f})"
        if score_details.kernel_version_score > 15:
            reasons["kernel_version_match"] = f"内核版本匹配 (得分: {score_details.kernel_version_score:.1f})"

    if not reasons:
        q_terms = get_term_set(query_text, use_synonyms=False)
        title_terms = get_term_set(case.title, use_synonyms=False)
        common = q_terms & title_terms
        if common:
            reasons["keyword_overlap"] = f"共同关键词: {', '.join(sorted(common)[:5])}"

    if case.source_file:
        reasons["commit_relevance"] = "待分析 (需通过 git commit fetcher 获取代码 diff 确认相关性)"

    return reasons
