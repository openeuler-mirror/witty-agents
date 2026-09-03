"""社区案例检索 — Linux/openEuler 社区 L1/L2/L3"""

import asyncio
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
    crash_features: dict = None,
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
      - final 案例自动抓取上游一手证据 (commit diff/message、issue 原文) 并给出
        confirmed/same_area/not_relevant/unverified 校验结论。
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

    # Online fallback: community KBs unconfigured or zero RAG hit -> search
    # upstream kernel commits via the lightweight REST commits API (no git
    # clone). Fallback candidates carry a baseline score and go through the
    # same first-hand diff verification below; only confirmed/same_area ones
    # survive into the report.
    if not final_cases:
        fallback_cases = await _online_fallback_cases(crash_features, cfg)
        if fallback_cases:
            final_cases = fallback_cases
            candidates = list(fallback_cases)
            stop_reason = "社区KB未配置/无命中，在线检索上游内核补丁（REST commits API，无 git clone）"

    if cfg.scoring_mode == "hybrid" and scorer:
        final_cases = await _hybrid_score(query_text, kernel_version, final_cases, scorer)
        candidates[:cfg.top_k_final] = final_cases
        candidates.sort(key=lambda x: x.score, reverse=True)

    # Build match_reason for each final case
    for case in final_cases:
        case.match_reason = _build_community_match_reason(query_text, kernel_version, case)

    # Fetch first-hand upstream evidence (commit diff/message, issue body) for
    # final cases concurrently, derive confirmed/same_area/not_relevant verdicts,
    # and adjust scores accordingly.
    commit_cfg = cfg.commit_analysis or {}
    if commit_cfg.get("enabled", True) and final_cases:
        try:
            from ..git_commit_fetcher import analyze_commit_relevance
            targets = [c for c in final_cases[:commit_cfg.get("max_commits_to_analyze", 5)] if c.source_file]

            async def _analyze(case: CommunityCase):
                try:
                    return case, await analyze_commit_relevance(case, query_text, crash_features)
                except Exception:
                    logger.debug("evidence analysis failed for %s", case.source_file, exc_info=True)
                    return case, None

            results = await asyncio.gather(*[_analyze(c) for c in targets])
            boost = commit_cfg.get("confirmed_boost", 1.15)
            penalty = commit_cfg.get("irrelevant_penalty", 0.5)
            for case, relevance in results:
                if not relevance:
                    case.verdict = "unverified"
                    continue
                verdict = relevance.get("verdict", "unverified")
                case.verdict = verdict
                case.match_reason["commit_relevance"] = relevance.get("reason", "")
                if verdict == "confirmed":
                    case.score = min(100.0, case.score * boost)
                elif verdict == "not_relevant":
                    case.score *= penalty
                # same_area / unverified: keep RAG score
            # online fallback candidates are synthetic (baseline score only):
            # drop those that failed first-hand verification
            final_cases = [
                c for c in final_cases
                if c.match_level != "ONLINE" or c.verdict in ("confirmed", "same_area")
            ]
            # re-rank after verdict adjustment and re-slice final list
            final_cases.sort(key=lambda x: x.score, reverse=True)
            final_cases = final_cases[:cfg.top_k_final]
        except Exception:
            logger.debug("commit evidence analysis stage failed", exc_info=True)

    # Post-verification fallback: RAG recall can be wrong-domain (all cards
    # verified not_relevant/unverified). When no card passed first-hand
    # verification, additionally search upstream commits via the REST API so
    # the real fix is discovered instead of presenting an unrelated card.
    positive = [c for c in final_cases if c.verdict in ("confirmed", "same_area")]
    fb_cfg = cfg.online_fallback or {}
    if (not positive and fb_cfg.get("enabled", True)
            and commit_cfg.get("enabled", True) and crash_features and final_cases):
        try:
            from ..git_commit_fetcher import analyze_commit_relevance as _acr
            extra = await _online_fallback_cases(crash_features, cfg)
            if extra:
                # Never persist post-verification fallback hits: they exist
                # despite RAG already returning docs, and "patch touches the
                # crash function" can be tangential for hot functions
                # (spinlock/sched/mm) — persisting them self-reinforces wrong
                # L1 hits on later runs. Only the primary (empty-KB) fallback
                # feeds C1 persistence.
                for c in extra:
                    c.evidence = {**(c.evidence or {}), "persist_blocked": True}

                async def _analyze2(case: CommunityCase):
                    try:
                        return case, await _acr(case, query_text, crash_features)
                    except Exception:
                        logger.debug("evidence analysis failed for %s", case.source_file, exc_info=True)
                        return case, None
                extra_res = await asyncio.gather(*[_analyze2(c) for c in extra])
                boost = commit_cfg.get("confirmed_boost", 1.15)
                for case, relevance in extra_res:
                    if not relevance:
                        continue
                    case.verdict = relevance.get("verdict", "unverified")
                    case.match_reason = _build_community_match_reason(query_text, kernel_version, case)
                    case.match_reason["commit_relevance"] = relevance.get("reason", "")
                    if case.verdict == "confirmed":
                        case.score = min(100.0, case.score * boost + 25.0)
                kept = [c for c, _r in extra_res if c.verdict in ("confirmed", "same_area")]
                if kept:
                    final_cases.extend(kept)
                    # first-hand verification of fallback cards establishes the
                    # correct subsystem(s): RAG cards verified not_relevant are
                    # wrong-domain noise (e.g. nftables hits on a sched lockup)
                    final_cases = [c for c in final_cases if c.verdict != "not_relevant"]
                    final_cases.sort(key=lambda x: x.score, reverse=True)
                    final_cases = final_cases[:cfg.top_k_final]
                    stop_reason += "；RAG 无 confirmed，在线兜底补充上游补丁检索"
                    logger.info("post-verification online fallback added %d case(s)", len(kept))
        except Exception:
            logger.debug("post-verification online fallback failed", exc_info=True)

    # Collapse duplicate cards of the same patch: identical sha (seed doc +
    # persisted doc) or upstream commit vs its stable backport (same title).
    final_cases = _dedupe_same_patch_cases(final_cases)

    # Confirmed upstream commits (RAG-hit curated docs or online-fallback
    # commits) are English material: fill Chinese phenomenon/root_cause/solution
    # via LLM (best-effort) before persisting, so the report card is readable
    # and newly persisted KB docs carry the Chinese summary.
    fb_cfg = cfg.online_fallback or {}
    if fb_cfg.get("summarize_confirmed", True):
        await _summarize_confirmed_cases(final_cases, query_text, crash_features or {})
    # Self-curating knowledge: online-fallback cases verified as `confirmed`
    # are persisted into the community KB (dedup by commit sha), so future
    # analyses hit them via semantic RAG retrieval instead of re-searching.
    if fb_cfg.get("persist_confirmed", True) and rag is not None:
        await _persist_online_confirmed(final_cases, rag)

    if scorer:
        await scorer.close()

    return CommunityMatchResult(
        matched=bool(final_cases),
        stop_reason=stop_reason,
        cases=final_cases,
        total_candidates=len(candidates),
    )


# Generic tokens in kernel function names that rarely identify a fix commit
_FB_TOKEN_STOPWORDS = {
    "init", "exit", "free", "alloc", "new", "del", "get", "set", "do", "show",
    "store", "read", "write", "create", "destroy", "add", "remove", "func",
    "handler", "callback", "check", "test", "run", "start", "stop", "open",
    "close", "lock", "unlock", "enable", "disable", "register", "unregister",
    "probe", "setup", "clear", "flush", "take", "put", "find", "make", "try",
    "core", "done", "err",
}


def _fallback_search_keywords(rip_function: str, drop_prefix: str = "") -> list[str]:
    """Derive commit-message keywords from the crash function name.

    Kernel commits refer to functions with underscores intact
    (``load_balance()``), so the full function name (and the tail after a
    short subsystem prefix like ``nft_``) is the strongest keyword. Short
    split tokens are added as a fallback for messages that name the concept
    but not the function (``nft_verdict_init`` -> ``verdict``). Keep this
    tight: overly broad keywords flood the candidate window with unrelated
    commits of the same subsystem.
    """
    name = re.split(r"[^a-z0-9_]", (rip_function or "").strip().lower())[0]
    drop = (drop_prefix or "").strip("_").lower()
    out, seen = [], set()

    def _add(k: str):
        if len(k) >= 3 and k not in seen and k not in _FB_TOKEN_STOPWORDS:
            seen.add(k)
            out.append(k)

    _add(name)  # exact function name, underscores preserved
    if drop and len(drop) <= 5 and name.startswith(drop):
        _add(name[len(drop):].strip("_"))  # e.g. nft_verdict_init -> verdict_init
    for t in re.split(r"[^a-z0-9]+", name):
        if len(t) >= 4:
            _add(t)
    return out[:4]


def _rank_fallback_commits(commits: list[dict], keywords: list[str]) -> list[dict]:
    """Rank API-ordered (newest-first) commits by subject keyword hits.

    Tier 0: subject contains every keyword; tier 1: subject contains some;
    tier 2: body-only matches. Stable sort keeps recency order within a tier,
    so the most recent on-topic fixes are verified first.
    """
    kws = [k for k in (keywords or []) if k]
    # Full function names (keep underscores) identify the fix precisely;
    # split tokens (pick/task/...) are broad and must not dominate ranking.
    exact_kws = [k for k in kws if "_" in k]
    token_kws = [k for k in kws if "_" not in k]

    def _tier(c: dict) -> tuple[int, int]:
        msg = (c.get("message") or "").lower()
        subj = msg.splitlines()[0] if msg else ""
        exact_hits = sum(1 for k in exact_kws if k in subj)
        token_hits = sum(1 for k in token_kws if k in subj)
        if exact_kws and exact_hits == len(exact_kws):
            return (0, -exact_hits)
        if exact_hits:
            return (1, -exact_hits)
        if not exact_kws and token_kws and token_hits == len(token_kws):
            return (0, -token_hits)
        if token_hits:
            return (2, -token_hits)
        return (3, 0)

    return sorted(commits, key=_tier)


async def _online_fallback_cases(crash_features: Optional[dict], cfg) -> list[CommunityCase]:
    """Online fallback when community KB retrieval returns nothing.

    Searches upstream kernel commits via the lightweight REST commits API
    (path-filtered by the crash function's subsystem, message-filtered by
    function-name keywords) — never clones a repository. Returned candidates
    carry a baseline score and MUST pass the existing first-hand diff
    verification stage (analyze_commit_relevance); only confirmed/same_area
    cases reach the report.
    """
    fb = cfg.online_fallback or {}
    if not fb.get("enabled", True):
        return []
    crash = crash_features or {}
    rip = (crash.get("rip_function") or "").strip()
    if not rip:
        return []

    trace = crash.get("call_trace") or crash.get("call_trace_signature") or []
    if isinstance(trace, str):
        trace = [trace]

    from ..git_commit_fetcher import search_commits, _fn_subsystem_match

    # One physical crash can span subsystems (e.g. a lockup whose RIP is in
    # kernel/locking while the actual fix lands in kernel/sched). Build up to
    # two search plans: each subsystem path paired with keywords derived from
    # the crash functions that map to it.
    plans: dict = {}
    for fn in [rip] + [f for f in trace[:6] if isinstance(f, str) and f]:
        fn = re.split(r"[+. ]", fn.strip(), 1)[0]
        if not fn:
            continue
        path, prefix = _fn_subsystem_match(fn)
        if not path:
            continue
        if path not in plans and len(plans) >= 2:
            continue  # cap searched paths, but still feed keywords to existing plans
        plans.setdefault(path, set()).update(
            _fallback_search_keywords(fn, drop_prefix=prefix))
    if not plans:
        kws = _fallback_search_keywords(rip)
        if not kws:
            return []
        plans[""] = set(kws)

    repo = fb.get("repo", "openeuler/kernel")
    seen_shas: set = set()
    commits: list = []
    for path, kws in plans.items():
        try:
            batch = await search_commits(
                repo,
                path=path,
                keywords=sorted(kws) or None,
                source=fb.get("source", "gitcode"),
                max_pages=int(fb.get("max_pages", 5)),
            )
        except Exception:
            logger.debug("online fallback search_commits failed (path=%s)", path, exc_info=True)
            continue
        for c in batch:
            sha = c.get("sha") or ""
            if sha and sha not in seen_shas:
                seen_shas.add(sha)
                commits.append(c)
        logger.info(
            "online fallback search: path=%s keywords=%s -> %d commit(s)",
            path or "-", ",".join(sorted(kws)) or "-", len(batch),
        )

    # surface on-topic fixes (keyword in subject) before newer unrelated commits
    all_keywords = sorted({k for kws in plans.values() for k in kws})
    commits = _rank_fallback_commits(commits, all_keywords)

    baseline = float(fb.get("baseline_score", 50.0))
    max_cand = int(fb.get("max_candidates", 8))
    source_label = fb.get("source_label", "openEuler社区")
    cases: list[CommunityCase] = []
    for c in commits[:max_cand]:
        sha = c.get("sha") or ""
        msg = c.get("message") or ""
        title = msg.splitlines()[0] if msg else (sha[:12] or "upstream commit")
        cases.append(CommunityCase(
            source=source_label,
            type="commit",
            json_id=f"online_{sha[:12]}",
            id=f"online_{sha[:12]}",
            title=title,
            content=msg,
            source_file=c.get("html_url") or "",
            creattime=(c.get("date") or "")[:10],
            score=baseline,
            match_score=round(baseline / 100.0, 4),
            match_level="ONLINE",
            verdict="unverified",
            evidence={"commit_sha": sha, "source_kind": "commit", "online_fallback": True},
        ))
    if cases:
        logger.info(
            "online fallback: %d candidate commit(s) from %s (paths=%s, keywords=%s)",
            len(cases), repo, ",".join(plans.keys()) or "-",
            ",".join(all_keywords) or "-",
        )
    return cases


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _case_commit_sha(case: CommunityCase) -> str:
    """Full commit sha from stashed evidence or parsed from source_file URL."""
    sha = str((case.evidence or {}).get("commit_sha") or "")
    if sha:
        return sha
    from ..git_commit_fetcher import _parse_commit_url
    parsed = _parse_commit_url(case.source_file or "")
    return parsed[3] if parsed else ""


def _is_commit_case(case: CommunityCase) -> bool:
    """Whether a case points at a kernel commit (vs an issue/PR)."""
    kind = str((case.evidence or {}).get("source_kind") or "")
    sf = case.source_file or ""
    return kind == "commit" or "/commit" in sf or "/commits/" in sf


def _norm_commit_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _dedupe_same_patch_cases(cases: list[CommunityCase]) -> list[CommunityCase]:
    """Collapse duplicate cards of the same upstream patch.

    The same fix can appear multiple times in results:
      - identical sha duplicated across/within KBs (seed doc + persisted doc);
      - upstream commit vs its stable backport (e.g. torvalds/linux vs
        openeuler/kernel "stable inclusion ... commit <sha> upstream.") which
        keep the exact same commit title.
    Commit cases are grouped by sha first, then merged across groups sharing
    the normalized title. Issue/PR cases are never title-merged. The primary
    card is preferred in this order: confirmed verdict > RAG-hit (non-ONLINE,
    so it is not re-persisted) > openEuler source > higher score.
    """
    others = [c for c in cases if not _is_commit_case(c)]
    groups: list[dict] = []  # {"shas": set, "title": str, "members": [cases]}
    for c in cases:
        if not _is_commit_case(c):
            continue
        sha = _case_commit_sha(c)
        title = _norm_commit_title(c.title)
        g = None
        if sha:
            g = next((g for g in groups if sha in g["shas"]), None)
        if g is None and title:
            g = next((g for g in groups if g["title"] and g["title"] == title), None)
        if g is None:
            g = {"shas": set(), "title": title, "members": []}
            groups.append(g)
        if sha:
            g["shas"].add(sha)
        g["members"].append(c)

    out: list[CommunityCase] = list(others)
    for g in groups:
        members = g["members"]
        if len(members) == 1:
            out.append(members[0])
            continue

        def _rank(c: CommunityCase):
            return (
                1 if c.verdict == "confirmed" else 0,
                0 if c.match_level == "ONLINE" else 1,
                1 if "openeuler" in (c.source or "").lower() else 0,
                c.score or 0.0,
            )

        primary = max(members, key=_rank)
        related = []
        for c in members:
            if c is primary:
                continue
            c_sha = _case_commit_sha(c)
            related.append({
                "source": c.source or "",
                "sha": c_sha,
                "url": c.source_file or "",
                "match_level": c.match_level or "",
            })
        ev = dict(primary.evidence or {})
        ev["related_commits"] = related
        primary.evidence = ev
        logger.info(
            "merged %d cards of the same patch into one (shas=%s): %s",
            len(members), ",".join(sorted(s[:12] for s in g["shas"])) or "-",
            (primary.title or "")[:60],
        )
        out.append(primary)

    out.sort(key=lambda x: x.score or 0.0, reverse=True)
    return out


async def _summarize_confirmed_cases(
    cases: list[CommunityCase], query_text: str, crash_features: dict
) -> None:
    """Best-effort: fill Chinese phenomenon/root_cause/solution for cases
    verified as `confirmed` (any match level: L1/L2 RAG hits or ONLINE fallback)
    using the LLM against the first-hand commit evidence. Cases whose three
    fields are already Chinese are skipped; duplicate docs of the same commit
    share one LLM call. Never raises; English content stays on any failure."""
    from ..llm_scorer import summarize_commit_case

    # Select confirmed cases with first-hand material that lack a Chinese summary
    canonicals: list[CommunityCase] = []
    duplicates: dict[str, list[CommunityCase]] = {}
    for c in cases:
        if c.verdict != "confirmed":
            continue
        ev = c.evidence or {}
        if not ev.get("commit_message"):
            continue
        fields = [c.phenomenon or "", c.root_cause or "", c.solution or ""]
        if all(fields) and all(_CJK_RE.search(f) for f in fields):
            continue  # already a full Chinese curated summary
        sha = _case_commit_sha(c)
        if sha and sha in duplicates:
            duplicates[sha].append(c)
        else:
            canonicals.append(c)
            if sha:
                duplicates[sha] = [c]
    if not canonicals:
        return

    cf = crash_features or {}
    frames = cf.get("call_trace_signature") or []
    if isinstance(frames, (list, tuple)):
        frames = ", ".join(str(f) for f in list(frames)[:5])
    crash_text = (
        f"崩溃描述: {query_text}\n"
        f"栈顶函数(RIP): {cf.get('rip_function', '')}\n"
        f"调用栈: {frames}\n"
        f"崩溃类型: {cf.get('bug_type', '')}"
    )
    results = await asyncio.gather(
        *[summarize_commit_case(c, crash_text) for c in canonicals],
        return_exceptions=True,
    )
    for case, ok in zip(canonicals, results):
        if ok is True:
            logger.info("zh summary generated for confirmed commit: %s",
                        (case.title or "")[:60])
            # share the result with duplicate KB docs of the same commit
            sha = _case_commit_sha(case)
            for dup in duplicates.get(sha, []):
                if dup is case:
                    continue
                dup.phenomenon, dup.root_cause, dup.solution = (
                    case.phenomenon, case.root_cause, case.solution)
                dup.evidence = {**(dup.evidence or {}), "summary_zh": True}
        else:
            logger.debug("zh summary skipped for %s (%s)", (case.title or "")[:60], ok)


async def _persist_online_confirmed(cases: list[CommunityCase], rag) -> None:
    """Best-effort: persist online-fallback cases verified as `confirmed` into
    the community KB, deduplicated by full commit sha. Never raises."""
    from ..git_commit_fetcher import _parse_commit_url

    for case in cases:
        if case.match_level != "ONLINE" or case.verdict != "confirmed":
            continue
        if (case.evidence or {}).get("persist_blocked"):
            continue  # post-verification fallback: report-only, no KB write
        sha = str((case.evidence or {}).get("commit_sha") or "")
        if not sha:
            parsed = _parse_commit_url(case.source_file or "")
            if parsed:
                sha = parsed[3]
        if not sha:
            continue
        try:
            if await rag.community_commit_exists(sha):
                logger.info("community case already in KB, skip: %s", sha[:12])
                continue
            json_id = await rag.create_community_case(case)
            if json_id:
                case.evidence = {**(case.evidence or {}), "persisted": True}
                logger.info("persisted confirmed upstream fix %s -> community KB (json_id=%s)",
                            sha[:12], json_id)
            else:
                logger.debug("persist skipped/failed for %s (KB unconfigured or write error)", sha[:12])
        except Exception:
            logger.debug("persist community case failed for %s", case.source_file, exc_info=True)


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

    if case.source_file and "commit_relevance" not in reasons:
        reasons["commit_relevance"] = "上游一手证据（commit diff/message、issue 原文）待校验"

    return reasons
