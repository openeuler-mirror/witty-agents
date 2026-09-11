"""MCP 工具接口"""

import logging
from typing import Optional

from fastmcp import FastMCP
from pydantic import Field

from .models import CrashFeatures, HostFeatures, CrashIssue, CrashCase, MatchResult
from .extractor import parse_dmesg, compute_signature, parse_host_from_dmesg, run_crash_analysis
from .matcher import match_crash
from .matcher.engine import _compute_issue_match_score
from .matcher.community_retriever import retrieve_community_cases, retrieve_upstream_online
from .knowledge import RAGClient
from .config import Config
from .analysis_chain import build_analysis_chain as _build_analysis_chain

logger = logging.getLogger(__name__)

mcp = FastMCP("CrashFeatureMatcher")


def _get_rag() -> Optional[RAGClient]:
    rag_cfg = Config().get().rag
    if rag_cfg.knowledge_kb_id:
        return RAGClient()
    return None


# ============================================================
# analyze_crash
# ============================================================

@mcp.tool()
async def analyze_crash(
    dmesg_text: str = Field(default="", description="dmesg 或 vmcore-dmesg 日志的完整文本"),
    dmesg_file: str = Field(default="", description="dmesg 日志文件路径(与 dmesg_text 二选一)"),
) -> dict:
    """
    分析 Linux 内核宕机日志, 提取特征值并匹配已知问题。

    输入 dmesg 文本或文件路径, 返回提取的宕机特征 + 匹配结果。
    """
    text = dmesg_text
    if not text and dmesg_file:
        try:
            with open(dmesg_file) as f:
                text = f.read()
        except Exception as e:
            return {"error": f"failed to read file: {e}"}
    if not text:
        return {"error": "provide dmesg_text or dmesg_file"}

    feature, host, has_hw = parse_dmesg(text)
    host_full = parse_host_from_dmesg(text)
    for k, v in host_full.model_dump().items():
        if v and not getattr(host, k):
            setattr(host, k, v)

    feature_sig = compute_signature(feature)
    rag = _get_rag()
    if not rag:
        return {"error": "RAG knowledge base not configured"}

    result = await match_crash(feature, host, rag)

    # shennong schema 对齐: 仅输出 schema 允许的字段 (additionalProperties:false)
    crash_dict = {
        "crash_time": feature.crash_time,
        "signature": feature_sig,
        "bug_type": feature.bug_type,
        "bug_key": feature.bug_key,
        "bug_summary": feature.bug_summary,
        "rip": feature.rip,
        "rip_function": feature.rip_function,
        "rip_offset": feature.rip_offset,
        "related_modules": feature.related_modules,
        "call_trace_signature": feature.call_trace_signature,
        "call_trace_text": feature.call_trace_text,
        "kernel_version": host.kernel_version,
        "anomaly_features": feature.anomaly_features,
    }
    host_dict = {
        "host_name": host.host_name,
        "kernel_version": host.kernel_version,
        "cpu_model": host.cpu_model,
        "machine_model": host.machine_model,
        "cpu_num": host.cpu_num,
        "memory_size": host.memory_size,
        "modules": host.modules,
    }

    # Determine if online fallback is recommended based on match result
    has_high_match = False
    has_confirmed = False
    if result.knowledge:
        has_high_match = getattr(result.knowledge, 'match_score', 0.0) >= 0.7
        has_confirmed = getattr(result.knowledge, 'verdict', '') == 'confirmed'
    should_fallback = not (has_high_match or has_confirmed)

    return {
        "signature": feature_sig,
        "crash_features": crash_dict,
        "host_features": host_dict,
        "match_result": {
            "matched": result.matched,
            "fingerprint_match": result.fingerprint_match,
            "knowledge": result.knowledge.model_dump() if result.knowledge else None,
            "similar_cases_count": len(result.similar_cases),
            "suggestions": result.suggestions,
        },
        "missing_fields": result.missing_fields,
        "should_fallback_online": should_fallback,
        "fallback_reason": "无 match_score >= 0.7 的高匹配" if not has_high_match else ("无 confirmed verdict" if not has_confirmed else ""),
    }


# ============================================================
# analyze_vmcore — local crash analysis (no RAG)
# ============================================================

@mcp.tool()
async def analyze_vmcore(
    vmcore: str = Field(..., description="vmcore file path"),
    vmlinux: str = Field(..., description="vmlinux file path"),
) -> dict:
    """Analyze vmcore + vmlinux via crash command (local extraction only, no RAG)."""
    feature, host, _has_hw = run_crash_analysis(vmcore, vmlinux)
    if feature is None:
        return {"error": "crash command failed"}

    feature_sig = compute_signature(feature) if feature.rip else ""

    return {
        "signature": feature_sig,
        "crash_features": {
            "crash_time": feature.crash_time,
            "signature": feature_sig,
            "bug_type": feature.bug_type,
            "bug_key": feature.bug_key,
            "bug_summary": feature.bug_summary,
            "rip": feature.rip,
            "rip_function": feature.rip_function,
            "rip_offset": feature.rip_offset,
            "related_modules": feature.related_modules,
            "call_trace_signature": feature.call_trace_signature,
            "call_trace_text": feature.call_trace_text,
            "kernel_version": host.kernel_version,
            "anomaly_features": feature.anomaly_features,
        },
        "host_features": {
            "host_name": host.host_name,
            "kernel_version": host.kernel_version,
            "cpu_model": host.cpu_model,
            "machine_model": host.machine_model,
            "cpu_num": host.cpu_num,
            "memory_size": host.memory_size,
            "modules": host.modules,
        },
    }


# ============================================================
# query_knowledge
# ============================================================

@mcp.tool()
async def query_knowledge(
    crash_features: dict = Field(description="REQUIRED: crash_features dict from analyze_crash result, used for L1 fingerprint detection and match scoring"),
    host_features: dict = Field(description="REQUIRED: host_features dict from analyze_crash result, used for match scoring"),
    bug_type: str = Field(default="", description="Bug type filter (e.g., panic, oops, soft_lockup)"),
    rip_function: str = Field(default="", description="RIP function name filter"),
    keyword: str = Field(default="", description="Semantic search keyword"),
    limit: int = Field(default=5, description="Maximum number of results to return"),
) -> dict:
    """Query the crash knowledge base with automatic L1/L2/L3 match scoring. Returns issues with match_score (0-1 normalized), match_level (L1/L2/L3), and match_reason populated."""
    rag = _get_rag()
    if not rag:
        return {"error": "RAG knowledge base not configured"}
    try:
        if rip_function:
            issues = await rag.search_issues_by_rip_function(rip_function, bug_type, limit)
        else:
            issues = await rag.search_issues_semantic(keyword or bug_type or "", bug_type, limit)

        if issues:
            feature = CrashFeatures(**crash_features)
            host = HostFeatures(**host_features)
            feature_sig = compute_signature(feature)
            for issue in issues:
                _compute_issue_match_score(feature, host, issue)  # sets issue.match_score (0-1) and match_reason
                # Determine match_level based on matching engine results
                if feature_sig and issue.fingerprints and feature_sig in issue.fingerprints:
                    issue.match_level = "L1"
                elif issue.match_score >= 0.6:
                    issue.match_level = "L2"
                elif issue.match_score > 0:
                    issue.match_level = "L3"

        # Determine if online fallback is recommended
        has_high_match = any(i.match_score >= 0.7 for i in issues) if issues else False
        has_confirmed = any(getattr(i, 'verdict', '') == 'confirmed' for i in issues) if issues else False
        should_fallback = not (has_high_match or has_confirmed)
        
        return {
            "total": len(issues),
            "issues": [i.model_dump() for i in issues],
            "should_fallback_online": should_fallback,
            "fallback_reason": "无 match_score >= 0.7 的高匹配" if not has_high_match else ("无 confirmed verdict" if not has_confirmed else ""),
        }
    finally:
        await rag.close()


# ============================================================
# query_cases
# ============================================================

@mcp.tool()
async def query_cases(
    knowledge_id: str = Field(default="", description="已知问题ID"),
    host_name: str = Field(default="", description="主机名过滤"),
    limit: int = Field(default=10, description="返回数量"),
) -> dict:
    """查询历史宕机案例库"""
    rag = _get_rag()
    if not rag:
        return {"error": "RAG knowledge base not configured"}
    try:
        cases = await rag.search_cases_by_knowledge_id(knowledge_id, limit) if knowledge_id else []
        return {"total": len(cases), "cases": [c.model_dump() for c in cases]}
    finally:
        await rag.close()


# ============================================================
# query_community_cases
# ============================================================

def _build_verdict_summary(cases) -> dict:
    """Aggregate community case verdicts into a structured summary consumed by
    the LLM when composing root_cause_analysis.conclusion / solution."""
    confirmed, excluded, unverified = [], [], []
    for c in cases:
        v = (getattr(c, "verdict", "") or "").strip()
        ev = getattr(c, "evidence", {}) or {}
        if v == "confirmed":
            confirmed.append({
                "title": c.title,
                "id": c.id or "",
                "html_url": ev.get("html_url") or c.source_file or "",
                "touched_files": ev.get("touched_files", []) or [],
                "touched_functions": ev.get("touched_functions", []) or [],
            })
        elif v in ("same_area", "not_relevant"):
            excluded.append({
                "title": c.title,
                "verdict": v,
                "html_url": ev.get("html_url") or c.source_file or "",
                "reason": (ev.get("reasons") or ["上游一手证据比对后判定不相关"])[0],
            })
        else:
            unverified.append({
                "title": c.title,
                "html_url": ev.get("html_url") or c.source_file or "",
            })

    if confirmed:
        top_verdict, confidence = "confirmed", "high"
    elif excluded:
        top_verdict, confidence = "same_area", "medium"
    elif unverified:
        top_verdict, confidence = "unverified", "low"
    else:
        top_verdict, confidence = "none", "low"

    if confirmed:
        first = confirmed[0]
        fns = "、".join(first["touched_functions"][:2]) if first["touched_functions"] else first["title"]
        ref = first["id"] or first["html_url"]
        conclusion_hint = f"上游提交 {ref} 直接修改崩溃路径上的函数（{fns}），确认本次根因，结论由推测升级为确认"
        solution_hint = f"采纳上游补丁：{first['title']}（{first['html_url']}）"
    elif excluded:
        conclusion_hint = "社区检索到的案例经上游 diff 比对未直接修复本次崩溃点，结论是否确认仅取决于内部知识库"
        solution_hint = "参考同子系统补丁思路，但不将其作为本次修复证据"
    elif unverified:
        conclusion_hint = "社区上游证据未能获取，相关性未经代码级确认，结论标记为推测"
        solution_hint = "无社区确认补丁，给出缓解建议"
    else:
        conclusion_hint = "未匹配到社区案例，结论标记为推测"
        solution_hint = "无社区确认补丁，给出缓解建议"

    return {
        "top_verdict": top_verdict,
        "confidence": confidence,
        "confirmed": confirmed,
        "excluded": excluded,
        "unverified": unverified,
        "conclusion_hint": conclusion_hint,
        "solution_hint": solution_hint,
    }


@mcp.tool()
async def query_community_cases(
    query_text: str = Field(..., description="查询文本/宕机关键词，建议包含 RIP 函数名与调用栈关键函数"),
    kernel_version: str = Field(default="", description="内核版本, 用于逻辑过滤"),
    crash_features: dict = Field(default={}, description="analyze_crash 返回的 crash_features (含 rip_function、call_trace 等), 用于对社区案例抓取上游一手证据(commit diff/message、issue 原文)并做代码级相关性校验"),
) -> dict:
    """L1/L2/L3 检索社区案例 (Linux/openEuler, 返回top3)。

    返回案例自动附带:
      - verdict: confirmed(补丁直接修复崩溃函数) / same_area(同子系统不同bug) /
        not_relevant(与崩溃路径无关) / unverified(原文获取失败)
      - evidence: commit message 原文、issue 正文摘要、改动文件/函数、diff 统计
      - verdict_summary: 聚合后的 confirmed/excluded/unverified 清单 + conclusion_hint /
        solution_hint, 供根因分析直接消费 (confirmed 补丁结构化注入结论)
    """
    rag = _get_rag()
    if not rag:
        return {"error": "RAG knowledge base not configured"}
    try:
        result = await retrieve_community_cases(
            query_text, kernel_version, rag, crash_features=crash_features or None
        )
        # Determine if online fallback is recommended
        has_high_match = any(c.match_score >= 0.7 for c in result.cases) if result.cases else False
        has_confirmed = any(c.verdict == 'confirmed' for c in result.cases) if result.cases else False
        should_fallback = not (has_high_match or has_confirmed)
        
        return {
            "matched": result.matched,
            "stop_reason": result.stop_reason,
            "total_candidates": result.total_candidates,
            "cases": [c.model_dump() for c in result.cases],
            "verdict_summary": _build_verdict_summary(result.cases),
            "should_fallback_online": should_fallback,
            "fallback_reason": "无 match_score >= 0.7 的高匹配" if not has_high_match else ("无 confirmed verdict" if not has_confirmed else ""),
        }
    except Exception as e:
        logger.exception("query_community_cases failed")
        return {"error": str(e)}
    finally:
        await rag.close()


# ============================================================
# query_upstream_online
# ============================================================

@mcp.tool()
async def query_upstream_online(
    crash_features: dict = Field(..., description="analyze_crash 返回的 crash_features (必须含 rip_function；call_trace_signature 用于子系统定位)"),
    query_text: str = Field(default="", description="补充查询文本 (崩溃现象描述)"),
    max_mails: int = Field(default=5, description="邮件列表讨论返回条数上限"),
) -> dict:
    """在线检索上游修复证据（本地知识库无高匹配时调用，不依赖 RAG 配置）。

    使用场景：query_knowledge / query_cases / query_community_cases 均无
    高匹配 (match_score < 0.7) 或无 confirmed 案例时，显式调用本工具在线获取：
      - commits: 上游修复 commit (REST API 检索 + 一手 diff 验证，
        仅返回 confirmed/same_area)，含 verdict / evidence / commit_relevance
      - patch_mails: openEuler 邮件列表中的 patch 讨论与分析线索
        (title / url / author / snippet)，用于补充根因分析思路
      - verdict_summary: 聚合 confirmed_commits / conclusion_hint / solution_hint

    与 query_community_cases 的区别：本工具不查 RAG 知识库，直接在线检索，
    因此 RAG 未配置时同样可用。
    """
    try:
        cfg = Config().get().community
        result = await retrieve_upstream_online(
            crash_features, cfg, query_text=query_text, max_mails=max_mails
        )
        commits = [c.model_dump() for c in result["commits"]]
        return {
            "commits": commits,
            "patch_mails": result["patch_mails"],
            "stop_reason": result["stop_reason"],
            "verdict_summary": _build_verdict_summary(result["commits"]),
        }
    except Exception as e:
        logger.exception("query_upstream_online failed")
        return {"error": str(e)}


# ============================================================
# build_analysis_chain
# ============================================================

@mcp.tool()
async def build_analysis_chain(
    crash_features: dict = Field(..., description="analyze_crash 返回的 crash_features (含 rip_function, call_trace_signature, anomaly_features)"),
) -> dict:
    """构建深度分析链：事件时间线 + 崩溃传播链 + 源码线索。

    为 LLM 的 analysis[] 提供结构化输入，支撑"先分析后判定"的推理过程。
    输出为数据字段（event_timeline / propagation_chain / source_clues），供根因推理使用；
    注意这些是数据字段，不是 reasoning_flow 的 stage 取值（stage 用 stack/hypothesis/path_analysis/internal/community/commit/source_compare/conclusion）。
    """
    try:
        return _build_analysis_chain(crash_features)
    except Exception as e:
        logger.exception("build_analysis_chain failed")
        return {"error": str(e)}


# ============================================================
# add_knowledge
# ============================================================

@mcp.tool()
async def add_knowledge(
    bug_summary: str = Field(..., description="问题简要描述"),
    bug_type: str = Field(..., description="Bug 类型"),
    bug_key: str = Field(default="", description="Bug 关键字"),
    fingerprints: str = Field(default="", description="指纹列表(逗号分隔, 空则自动生成)"),
    rip: str = Field(default="", description="RIP 地址"),
    rip_function: str = Field(default="", description="RIP 函数名"),
    rip_offset: str = Field(default="", description="RIP 偏移量"),
    related_modules: str = Field(default="", description="关联模块(逗号分隔)"),
    call_trace_text: str = Field(default="", description="调用栈文本"),
    call_trace_signature: str = Field(default="", description="调用栈函数签名(逗号分隔)"),
    root_cause: str = Field(default="", description="根因分析"),
    solution: str = Field(default="", description="解决方案"),
    hotpatch: str = Field(default="", description="热补丁名称"),
) -> dict:
    """向知识库中录入一条已知宕机问题"""
    rag = _get_rag()
    if not rag:
        return {"error": "RAG knowledge base not configured"}

    modules_list = [m.strip() for m in related_modules.split(",") if m.strip()]
    trace_list = [f.strip() for f in call_trace_signature.split(",") if f.strip()]
    fp_list = [f.strip() for f in fingerprints.split(",") if f.strip()]

    if not fp_list:
        from .extractor.signature import compute_issue_signature
        sig = compute_issue_signature(bug_type, modules_list, rip_function, rip_offset)
        fp_list = [sig]

    issue = CrashIssue(
        fingerprints=fp_list,
        bug_type=bug_type,
        bug_key=bug_key or bug_type,
        bug_summary=bug_summary,
        rip=rip,
        rip_function=rip_function,
        rip_offset=rip_offset,
        related_modules=modules_list,
        call_trace_signature=trace_list,
        call_trace_text=call_trace_text,
        root_cause=root_cause,
        solution=solution,
        hotpatch=hotpatch,
        case_count=0,
    )

    try:
        json_id = await rag.create_issue(issue)
        return {"success": True, "json_id": json_id, "knowledge_id": issue.knowledge_id}
    except Exception as e:
        return {"error": str(e)}
    finally:
        await rag.close()


# ============================================================
# merge_knowledge
# ============================================================

@mcp.tool()
async def merge_knowledge(
    source_ids: str = Field(..., description="要合并的 knowledge_id 列表(逗号分隔)"),
    target_bug_summary: str = Field(..., description="合并后的 issue 摘要"),
    target_root_cause: str = Field(default="", description="合并后的根因分析"),
    target_solution: str = Field(default="", description="合并后的解决方案"),
    target_hotpatch: str = Field(default="", description="合并后的热补丁"),
) -> dict:
    """
    合并多条相似知识为一个, 保留所有指纹。

    合并后任意指纹命中即可 L1 匹配。
    """
    rag = _get_rag()
    if not rag:
        return {"error": "RAG knowledge base not configured"}

    ids = [s.strip() for s in source_ids.split(",") if s.strip()]
    if len(ids) < 2:
        return {"error": "至少需要 2 个 knowledge_id 进行合并"}

    try:
        # 拉取所有源 issue (通过语义搜索找 approximate match, 再用 knowledge_id 过滤)
        all_issues = await rag.search_issues_semantic("", "", top_k=250)
        sources = [i for i in all_issues if i.knowledge_id in ids]

        if len(sources) < 2:
            return {"error": f"只找到 {len(sources)}/{len(ids)} 个 issue"}

        # 合并指纹
        all_fps: list[str] = []
        all_versions: set[str] = set()
        total_cases = 0
        best_hp = target_hotpatch
        best_sol = target_solution
        best_wiki = ""
        first_seen = ""
        last_seen = ""

        for s in sources:
            for fp in (s.fingerprints or []):
                if fp and fp not in all_fps:
                    all_fps.append(fp)
            all_versions.update(s.kernel_versions)
            total_cases += s.case_count or 0
            if not best_hp and s.hotpatch:
                best_hp = s.hotpatch
            if not best_sol and s.solution:
                best_sol = s.solution
            if not best_wiki and s.history_wiki:
                best_wiki = s.history_wiki
            if not first_seen or (s.first_seen and s.first_seen < first_seen):
                first_seen = s.first_seen or ""
            if not last_seen or (s.last_seen and s.last_seen > last_seen):
                last_seen = s.last_seen or ""

        merged = CrashIssue(
            fingerprints=all_fps,
            bug_type=sources[0].bug_type,
            bug_key=sources[0].bug_key,
            bug_summary=target_bug_summary,
            rip=sources[0].rip if sources else "",
            rip_function=sources[0].rip_function if sources else "",
            rip_offset=sources[0].rip_offset if sources else "",
            related_modules=list(set(m for s in sources for m in s.related_modules)),
            call_trace_signature=sources[0].call_trace_signature if sources else [],
            call_trace_text=sources[0].call_trace_text if sources else "",
            kernel_versions=sorted(all_versions),
            root_cause=target_root_cause,
            solution=best_sol,
            hotpatch=best_hp,
            history_wiki=best_wiki,
            case_count=total_cases,
            first_seen=first_seen,
            last_seen=last_seen,
        )

        json_id = await rag.create_issue(merged)
        return {
            "success": True,
            "json_id": json_id,
            "knowledge_id": merged.knowledge_id,
            "fingerprints": all_fps,
            "merged_count": len(sources),
            "total_cases": total_cases,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        await rag.close()


@mcp.tool()
async def get_stats() -> dict:
    """获取宕机统计概览"""
    return {"message": "not implemented", "stats": {}}
