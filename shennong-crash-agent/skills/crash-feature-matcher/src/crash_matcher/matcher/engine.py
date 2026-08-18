"""匹配引擎 — L1指纹 + L2 RAG驱动 + jieba/Jaccard/synonyms 综合打分"""

import logging
from typing import Optional

from ..models import CrashFeatures, HostFeatures, CrashIssue, CrashCase, MatchResult
from ..extractor.signature import compute_signature
from ..utils.text_similarity import get_term_set, jaccard_similarity

from ..config_models import SearchConfig, Expression, LogicalExpression
from .l2_configs import build_l2_config, get_strategy_name
from ..knowledge.client import RAGClient
from .classifier import classify_bug_type


logger = logging.getLogger(__name__)


async def match_crash(feature: CrashFeatures, host: HostFeatures,
                      rag: Optional[RAGClient] = None) -> MatchResult:

    if not feature.bug_type:
        feature.bug_type = classify_bug_type(feature)

    feature_sig = compute_signature(feature)
    missing = _check_missing(feature)
    current_case = _build_case(feature, host, feature_sig)

    if not rag:
        return MatchResult(matched=False, fingerprint_match=False,
                          knowledge=None, similar_cases=[], current_case=current_case,
                          suggestions=["RAG not configured"], missing_fields=missing)

    # ═══ L1: Fingerprint keyword match (one RAG call) ═══
    l1_cfg = _build_l1_config(feature_sig, rag.knowledge_kb_id)
    l1_items = await rag.search_configs([l1_cfg])

    for item in l1_items:
        issue = _to_issue(item)
        if not issue:
            continue
        fps = issue.fingerprints or []
        if feature_sig in fps:
            score = _compute_issue_match_score(feature, host, issue)
            issue.match_score = round(score / 100.0, 4)  # shennong 对齐: 0-1 归一化
            _bump(issue)
            similar = await _maybe_search_cases(rag, issue)
            current_case.match_score = score
            current_case.match_method = "L1_fingerprint"
            return MatchResult(matched=True, fingerprint_match=True,
                              knowledge=issue, similar_cases=similar,
                              current_case=current_case,
                              suggestions=_suggestions(issue), missing_fields=missing)

    # ═══ L2: bug_key-driven RAG search (second RAG call, only on L1 miss) ═══
    l2_cfg = build_l2_config(feature, rag.knowledge_kb_id)
    if l2_cfg:
        l2_items = await rag.search_configs([l2_cfg])
        best_issue = None
        best_score = 0.0
        best_similar = []
        for item in l2_items:
            issue = _to_issue(item)
            if not issue:
                continue
            valid, score = _validate_l2_match(feature, host, issue)
            if not valid:
                continue
            if score > best_score:
                best_issue = issue
                best_score = score
                best_similar = await _maybe_search_cases(rag, issue)
        if best_issue and best_score >= 60:  # L2 threshold on 0-100 scale
            best_issue.match_score = best_score  # shennong 对齐: 注入匹配分数
            _bump(best_issue)
            current_case.match_score = best_score
            current_case.match_method = "L2_rag_scored"
            return MatchResult(matched=True, fingerprint_match=False,
                              knowledge=best_issue, similar_cases=best_similar,
                              current_case=current_case,
                              suggestions=_suggestions(best_issue), missing_fields=missing)
    # New issue
    new_issue = _build_new_issue(feature, feature_sig)
    return MatchResult(matched=False, fingerprint_match=False,
                      knowledge=new_issue, similar_cases=[], current_case=current_case,
                      suggestions=["no known crash pattern matched"], missing_fields=missing)


def _validate_l2_match(feature: CrashFeatures, host: HostFeatures, issue: CrashIssue) -> tuple[bool, float]:
    """L2 validation: strict checks by bug_key strategy, then comprehensive scoring."""
    strategy = get_strategy_name(feature.bug_key)

    # LIKE strategies: rip_function must match
    if strategy in ("exact_rip_with_bugkey", "fuzzy_rip_offset"):
        if feature.rip_function and issue.rip_function:
            if feature.rip_function != issue.rip_function:
                return False, 0.0

    score = _compute_issue_match_score(feature, host, issue)
    return True, score


def _compute_issue_match_score(feature: CrashFeatures, host: HostFeatures, issue: CrashIssue) -> float:
    """
    Comprehensive 0-100 scoring for CrashIssue matching using jieba + Jaccard + synonyms.
    Also populates issue.match_reason with human-readable match explanations.

    Score factors:
      - bug_type match: +20
      - bug_key Jaccard overlap: +10
      - rip_function exact match: +20
      - call_trace Jaccard overlap: +15
      - related_modules overlap: +10
      - bug_summary/root_cause/solution content Jaccard: +15
      - kernel_version match: +8
      - error_keywords overlap: +2 (from anomaly_features)
    """
    score = 0.0
    reasons: dict[str, str] = {}

    # bug_type exact match
    if feature.bug_type and issue.bug_type and feature.bug_type == issue.bug_type:
        score += 20.0
        reasons["bug_type_match"] = f"bug_type 完全一致: {feature.bug_type}"
    elif feature.bug_type and issue.bug_type:
        reasons["bug_type_match"] = f"bug_type 不一致 (当前: {feature.bug_type}, 案例: {issue.bug_type})"

    # bug_key overlap
    if feature.bug_key and issue.bug_key:
        bk_score = jaccard_similarity(
            get_term_set(feature.bug_key, use_synonyms=True),
            get_term_set(issue.bug_key, use_synonyms=False)
        ) * 10.0
        score += bk_score
        if bk_score > 3:
            reasons["bug_key_overlap"] = f"bug_key 关键词具有语义关联 (得分: {bk_score:.1f})"

    # rip_function exact match
    if feature.rip_function and issue.rip_function and feature.rip_function == issue.rip_function:
        score += 20.0
        reasons["rip_match"] = f"RIP 函数完全一致: {feature.rip_function}"
    elif feature.rip_function and issue.rip_function:
        reasons["rip_mismatch"] = f"RIP 函数不一致 (当前: {feature.rip_function}, 案例: {issue.rip_function})"

    # call_trace overlap
    if feature.call_trace_functions and issue.call_trace_signature:
        feature_ct = set(f.lower() for f in feature.call_trace_functions if f)
        issue_ct = set(f.lower() for f in issue.call_trace_signature if f)
        ct_overlap = jaccard_similarity(feature_ct, issue_ct)
        ct_score = ct_overlap * 15.0
        score += ct_score
        common = feature_ct & issue_ct
        if common:
            reasons["call_trace_overlap"] = f"调用栈共同函数: {', '.join(sorted(common)[:5])} (Jaccard: {ct_overlap:.2f})"

    # related_modules overlap
    if feature.related_modules and issue.related_modules:
        feature_mods = set(m.lower() for m in feature.related_modules if m)
        issue_mods = set(m.lower() for m in issue.related_modules if m)
        mod_overlap = jaccard_similarity(feature_mods, issue_mods)
        mod_score = mod_overlap * 10.0
        score += mod_score
        common_mods = feature_mods & issue_mods
        if common_mods:
            reasons["module_match"] = f"关联模块一致: {', '.join(sorted(common_mods))}"

    # content overlap (bug_summary + root_cause + solution + call_trace_text)
    query_text = " ".join([
        feature.bug or "",
        feature.bug_key or "",
        " ".join(feature.call_trace_functions) if feature.call_trace_functions else "",
    ]).strip()
    doc_text = " ".join([
        issue.bug_summary or "",
        issue.root_cause or "",
        issue.solution or "",
        issue.call_trace_text or "",
    ]).strip()
    if query_text and doc_text:
        content_score = jaccard_similarity(
            get_term_set(query_text, use_synonyms=True),
            get_term_set(doc_text, use_synonyms=False)
        ) * 15.0
        score += content_score

    # kernel version match
    if host.kernel_version and issue.kernel_versions:
        kv_s = _kernel_version_score(host.kernel_version, issue.kernel_versions)
        kv_score = kv_s * 8.0
        score += kv_score
        if kv_s > 0.5:
            reasons["kernel_version_match"] = f"内核版本匹配 (当前: {host.kernel_version}, 案例版本范围: {issue.kernel_versions[:3]})"

    # error_keywords overlap (from anomaly_features) — 改动五
    feat_kws = set(k.lower() for k in feature.anomaly_features.get("error_keywords", []))
    issue_kws = set(k.lower() for k in issue.error_keywords)
    if feat_kws and issue_kws:
        common_kws = feat_kws & issue_kws
        ekw_score = min(10, len(common_kws) * 3)
        score += ekw_score
        if common_kws:
            reasons["error_keyword_match"] = f"异常关键词一致: {', '.join(sorted(common_kws))}"

    issue.match_reason = reasons
    return min(100.0, score)


def _kernel_version_score(host_kv: str, issue_kvs: list[str]) -> float:
    """Return 0-1 kernel version match score."""
    if not host_kv or not issue_kvs:
        return 0.0
    host_kv = host_kv.strip().lower()
    for issue_kv in issue_kvs:
        if not issue_kv:
            continue
        issue_kv = issue_kv.strip().lower()
        if host_kv == issue_kv:
            return 1.0
        if issue_kv.startswith(host_kv) or host_kv.startswith(issue_kv):
            return 0.67
        host_major = ".".join(host_kv.split(".")[:2])
        issue_major = ".".join(issue_kv.split(".")[:2])
        if host_major and issue_major and host_major == issue_major:
            return 0.5
    return 0.0


def _build_l1_config(sig: str, kb_id: str) -> SearchConfig:
    return SearchConfig(
        kb_id=kb_id, query="", top_k=5,
        logical_expression=LogicalExpression(operator="and", expressions=[
            Expression(field="source", type="string", operator="eq", value="issue"),
            Expression(field="fingerprints", type="string", operator="like", value=sig),
        ]),
        semantic_keys=[], ratio=0.3,
    )

def _check_missing(f: CrashFeatures) -> list[str]:
    m = []
    if not f.rip or not f.rip_function:
        m.append("rip")
    if not f.call_trace or len(f.call_trace_functions) < 2:
        m.append("call_trace")
    if not f.bug_key:
        m.append("bug_key")
    return m


def _bump(issue: CrashIssue):
    from ..models import _utc_now
    issue.case_count = (issue.case_count or 0) + 1
    issue.last_seen = _utc_now()


def _suggestions(issue: CrashIssue) -> list[str]:
    s = []
    if issue.solution:
        s.append(f"solution: {issue.solution}")
    if issue.hotpatch:
        s.append(f"hotpatch: {issue.hotpatch}")
    return s


async def _maybe_search_cases(rag, issue) -> list[CrashCase]:
    if not issue.solution:
        try: return await rag.search_cases_by_knowledge_id(issue.knowledge_id, limit=10)
        except Exception: logger.debug(f"search_cases_by_knowledge_id failed for {issue.knowledge_id}", exc_info=True)
    return []


def _to_issue(item) -> Optional[CrashIssue]:
    if isinstance(item, CrashIssue): return item
    if isinstance(item, dict):
        try:
            d = dict(item)
            if "signature" in d and "fingerprints" not in d:
                d["fingerprints"] = [d.pop("signature")]
            return CrashIssue(**d)
        except Exception:
            logger.debug(f"_to_issue failed for data keys={list(item.keys())[:5]}", exc_info=True)
    return None


def _build_case(f, host, sig) -> CrashCase:
    return CrashCase(
        host_name=host.host_name, machine_model=host.machine_model,
        kernel_version=host.kernel_version, cpu_model=host.cpu_model,
        cpu_num=host.cpu_num, memory_size=host.memory_size,
        uptime_seconds=host.uptime_seconds, vendor=host.vendor, modules=host.modules,
        crash_time=f.crash_time, crash_type=f.crash_type, bug_type=f.bug_type,
        rip=f.rip, rip_function=f.rip_function, bug_key=f.bug_key, bug=f.bug,
        call_trace=f.call_trace, call_trace_functions=f.call_trace_functions,
        crash_cpu=f.crash_cpu, crash_command=f.crash_command,
        related_modules=f.related_modules, crash_log=f.crash_log, signature=sig,
    )


def _build_new_issue(f, sig) -> CrashIssue:
    return CrashIssue(
        fingerprints=[sig],
        bug_type=f.bug_type, bug_key=f.bug_key,
        bug_summary=f.bug[:200] if f.bug else f.bug_key,
        rip=f.rip, rip_function=f.rip_function, rip_offset=f.rip_offset,
        related_modules=f.related_modules,
        call_trace_signature=f.call_trace_functions, call_trace_text=f.call_trace,
    )
