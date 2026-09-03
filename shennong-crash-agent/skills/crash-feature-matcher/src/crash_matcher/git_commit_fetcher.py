"""Git community evidence fetcher — fetch commit diff, commit message and
issue/PR body from gitcode/gitee, then derive a structured relevance verdict.

Public-repo endpoints work anonymously; GITCODE_TOKEN is only needed for
private repos or rate-limit headroom (we try anonymous first, then retry
with the token on 401/403).
"""

import html as html_mod
import logging
import os
import re
import urllib.parse
from typing import Optional

import httpx

from .models import CommunityCase

logger = logging.getLogger(__name__)

GITCODE_API = "https://api.gitcode.com/api/v5"
GITEE_API = "https://gitee.com/api/v5"

_COMMIT_PATTERNS = [
    re.compile(r"(?:gitcode\.com|gitee\.com)/([^/]+)/([^/]+)/commits?/(?:detail/)?([a-f0-9]{7,40})", re.IGNORECASE),
    re.compile(r"(?:gitcode\.com|gitee\.com)/([^/]+)/([^/]+)/commit/([a-f0-9]{7,40})", re.IGNORECASE),
    re.compile(r"(?:gitcode\.com|gitee\.com)/([^/]+)/([^/]+)/-/commit/([a-f0-9]{7,40})", re.IGNORECASE),
]
_ISSUE_PATTERN = re.compile(
    r"(?:gitcode\.com|gitee\.com)/([^/]+)/([^/]+)/(?:issues|pulls?)/(\d+)", re.IGNORECASE)

# in-process cache: source url -> evidence dict
_EVIDENCE_CACHE: dict[str, dict] = {}

_DIFF_LIMIT = 6000
_MSG_LIMIT = 2500
_BODY_LIMIT = 3500


# ------------------------------------------------------------
# URL parsing
# ------------------------------------------------------------

def _parse_commit_url(url: str) -> Optional[tuple[str, str, str, str]]:
    """Return (api_base, owner, repo, sha) or None."""
    for pat in _COMMIT_PATTERNS:
        m = pat.search(url or "")
        if m:
            base = GITEE_API if "gitee.com" in url.lower() and "gitcode.com" not in url.lower() else GITCODE_API
            return base, m.group(1), m.group(2), m.group(3)
    return None


def _parse_issue_url(url: str) -> Optional[tuple[str, str, str, str, str]]:
    """Return (api_base, owner, repo, number, kind) where kind is issue/pull."""
    m = _ISSUE_PATTERN.search(url or "")
    if not m:
        return None
    owner, repo, number = m.group(1), m.group(2), m.group(3)
    kind = "pull" if re.search(r"/pulls?/", url, re.IGNORECASE) else "issue"
    base = GITEE_API if "gitee.com" in url.lower() and "gitcode.com" not in url.lower() else GITCODE_API
    return base, owner, repo, number, kind


def _is_gitcode(url: str) -> bool:
    return "gitcode.com" in url.lower()


# ------------------------------------------------------------
# HTTP helper (anonymous first, token retry)
# ------------------------------------------------------------

async def _http_get(client: httpx.AsyncClient, url: str, accept: str = "text") -> Optional[httpx.Response]:
    headers = {"Accept": "application/json"} if accept == "json" else {}
    try:
        resp = await client.get(url, headers=headers)
        if resp.status_code in (401, 403):
            token = os.environ.get("GITCODE_TOKEN", "")
            if token:
                h2 = dict(headers)
                h2["PRIVATE-TOKEN"] = token
                resp = await client.get(url, headers=h2)
        resp.raise_for_status()
        return resp
    except Exception as e:
        logger.warning("fetch failed %s: %s", url, e)
        return None


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|h[1-6]|li|pre|tr|table)>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "- ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html_mod.unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# ------------------------------------------------------------
# Fetchers
# ------------------------------------------------------------

async def fetch_commit_diff(source_file: str) -> Optional[str]:
    """Fetch raw commit diff text (gitcode has a dedicated plain-text diff
    endpoint; gitee returns JSON with files[].patch)."""
    parsed = _parse_commit_url(source_file)
    if not parsed:
        return None
    base, owner, repo, sha = parsed
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        if _is_gitcode(source_file):
            url = f"{base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/commit/{sha}/diff"
            resp = await _http_get(client, url, accept="text")
            if resp and resp.text and len(resp.text.strip()) > 10 and not resp.text.lstrip().startswith("{"):
                return resp.text[:_DIFF_LIMIT]
        # gitee (or gitcode fallback): JSON commit detail, assemble patches
        url = f"{base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/commits/{sha}"
        resp = await _http_get(client, url, accept="json")
        if not resp:
            return None
        try:
            data = resp.json()
        except Exception:
            return None
        files = data.get("files") or []
        chunks = []
        for f in files[:6]:
            patch = f.get("patch") or ""
            if patch:
                chunks.append(f"--- {f.get('filename', '?')}\n{patch}")
        if chunks:
            return "\n".join(chunks)[:_DIFF_LIMIT]
        return None


async def fetch_commit_detail(source_file: str) -> dict:
    """Fetch commit metadata: message, author, stats."""
    parsed = _parse_commit_url(source_file)
    if not parsed:
        return {}
    base, owner, repo, sha = parsed
    url = f"{base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/commits/{sha}"
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await _http_get(client, url, accept="json")
        if not resp:
            return {}
        try:
            data = resp.json()
        except Exception:
            return {}
    commit = data.get("commit") or {}
    stats = data.get("stats") or {}
    return {
        "sha": data.get("sha") or sha,
        "message": (commit.get("message") or "").strip()[:_MSG_LIMIT],
        "author": (commit.get("author") or {}).get("name", ""),
        "date": (commit.get("author") or {}).get("date", ""),
        "html_url": data.get("html_url", ""),
        "additions": stats.get("additions", 0),
        "deletions": stats.get("deletions", 0),
    }


async def fetch_issue_detail(source_file: str) -> dict:
    """Fetch issue/PR title and body (HTML stripped to plain text)."""
    parsed = _parse_issue_url(source_file)
    if not parsed:
        return {}
    base, owner, repo, number, kind = parsed
    endpoint = "pulls" if kind == "pull" else "issues"
    url = f"{base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/{endpoint}/{number}"
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await _http_get(client, url, accept="json")
        if not resp:
            return {}
        try:
            data = resp.json()
        except Exception:
            return {}
    body = _strip_html(data.get("body") or data.get("description") or "")
    return {
        "number": data.get("number") or number,
        "title": data.get("title") or "",
        "state": data.get("state") or "",
        "body": body[:_BODY_LIMIT],
        "html_url": data.get("html_url", ""),
    }


async def search_commits(
    repo: str,
    path: str = "",
    keywords: Optional[list[str]] = None,
    source: str = "gitcode",
    max_pages: int = 2,
) -> list[dict]:
    """Lightweight replacement for `git clone` + `git log --grep/-S`.

    Lists commits via the gitcode/gitee REST API (optionally filtered by file
    path) and keeps those whose message contains any of ``keywords``. Each page
    is at most 100 commits; total traffic is a few hundred KB — no repository
    is ever downloaded.

    repo: ``owner/repo`` (e.g. ``openeuler/kernel``); source: ``gitcode`` or
    ``gitee``. Returns a list of ``{sha, html_url, date, author, message}``.
    """
    if "/" not in (repo or ""):
        return []
    owner, repo_name = repo.split("/", 1)
    base = GITEE_API if source == "gitee" else GITCODE_API
    kws = [k.lower() for k in (keywords or []) if k]
    results: list[dict] = []
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for page in range(1, max_pages + 1):
            params = {"per_page": 100, "page": page}
            if path:
                params["path"] = path
            url = (f"{base}/repos/{urllib.parse.quote(owner)}/"
                   f"{urllib.parse.quote(repo_name)}/commits?"
                   f"{urllib.parse.urlencode(params)}")
            resp = await _http_get(client, url, accept="json")
            if not resp:
                break
            try:
                data = resp.json()
            except Exception:
                break
            if not isinstance(data, list) or not data:
                break
            for item in data:
                commit = item.get("commit") or {}
                msg = (commit.get("message") or "").strip()
                if kws and not any(k in msg.lower() for k in kws):
                    continue
                author = commit.get("author") or {}
                results.append({
                    "sha": item.get("sha") or "",
                    "html_url": item.get("html_url") or "",
                    "date": author.get("date") or "",
                    "author": author.get("name") or "",
                    "message": msg[:_MSG_LIMIT],
                })
    return results


async def fetch_community_evidence(source_file: str, case_type: str = "") -> dict:
    """Unified entry: fetch first-hand evidence for a community case.

    Returns a dict with keys:
      fetched, source_kind (commit/issue),
      diff, commit_message, commit_author, commit_date, additions, deletions,
      issue_title, issue_body, issue_state, html_url
    """
    if not source_file:
        return {"fetched": False, "reason": "no source url"}
    if source_file in _EVIDENCE_CACHE:
        return _EVIDENCE_CACHE[source_file]

    ev = {"fetched": False, "source_kind": "", "diff": "", "commit_message": "",
          "commit_author": "", "commit_date": "", "additions": 0, "deletions": 0,
          "issue_title": "", "issue_body": "", "issue_state": "", "html_url": source_file}

    commit_parsed = _parse_commit_url(source_file)
    issue_parsed = _parse_issue_url(source_file)
    try:
        if commit_parsed and (not case_type or case_type == "commit"):
            ev["source_kind"] = "commit"
            ev["diff"] = (await fetch_commit_diff(source_file)) or ""
            detail = await fetch_commit_detail(source_file)
            if detail:
                ev["commit_message"] = detail.get("message", "")
                ev["commit_author"] = detail.get("author", "")
                ev["commit_date"] = detail.get("date", "")
                ev["additions"] = detail.get("additions", 0)
                ev["deletions"] = detail.get("deletions", 0)
                ev["html_url"] = detail.get("html_url") or source_file
            ev["fetched"] = bool(ev["diff"] or ev["commit_message"])
        elif issue_parsed:
            ev["source_kind"] = issue_parsed[4]
            detail = await fetch_issue_detail(source_file)
            if detail:
                ev["issue_title"] = detail.get("title", "")
                ev["issue_body"] = detail.get("body", "")
                ev["issue_state"] = detail.get("state", "")
                ev["html_url"] = detail.get("html_url") or source_file
            ev["fetched"] = bool(ev["issue_body"] or ev["issue_title"])
    except Exception as e:
        logger.warning("fetch_community_evidence failed for %s: %s", source_file, e)
        ev["fetched"] = False

    _EVIDENCE_CACHE[source_file] = ev
    return ev


# ------------------------------------------------------------
# Diff parsing & subsystem heuristics
# ------------------------------------------------------------

def _parse_diff(diff: str) -> dict:
    """Extract touched files, hunk function contexts, added lines."""
    files, hunks, added = [], [], []
    for line in (diff or "").splitlines():
        if line.startswith("+++ b/"):
            files.append(line[6:].strip())
        elif line.startswith("+++ "):
            files.append(line[4:].strip())
        elif line.startswith("@@"):
            hunks.append(line)
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line)
    return {"files": files, "hunks": hunks, "added_text": "\n".join(added)}


def _subsystem_of_path(path: str) -> str:
    parts = [p for p in (path or "").split("/") if p]
    if len(parts) >= 3 and parts[0] in ("drivers", "fs", "net", "kernel", "mm", "arch"):
        return "/".join(parts[:2])
    return parts[0] if parts else ""


# kernel function prefix -> likely source subsystem
_FN_SUBSYSTEM = [
    (("mlx5",), "drivers/net"),
    (("tcp_", "udp_", "inet_", "sock_", "reqsk_", "inet_csk"), "net/ipv4"),
    (("nft_", "nf_", "nfnetlink", "nfnl_", "xt_", "ipt_", "ip6t_"), "net/netfilter"),
    (("ip_", "icmp_", "xfrm_", "__netif", "netif_", "napi_", "gro_", "skb_", "dev_"), "net/core"),
    (("do_IRQ", "irq_", "__do_softirq", "softirq", "common_interrupt"), "kernel/irq"),
    (("ext4_",), "fs/ext4"),
    (("xfs_",), "fs/xfs"),
    (("queued_spin", "spin_", "osq_", "mutex_", "rwsem_", "rtmutex_",
      "lockdep_", "ww_mutex"), "kernel/locking"),
    (("futex_", "do_futex", "sys_futex"), "kernel/futex"),
    (("schedule", "try_to_wake", "wake_up", "ttwu_", "pick_next",
      "load_balance", "newidle", "enqueue_task", "dequeue_task",
      "sched_", "check_preempt", "hrtick_", "__switch_to"), "kernel/sched"),
    (("__alloc", "kmalloc", "kfree", "slab_", "page_", "get_page"), "mm"),
]


def _fn_subsystem_match(fn: str) -> tuple[str, str]:
    """Return ``(subsystem_path, matched_prefix)`` for a kernel function.

    Returns ``("", "")`` when no prefix matches.
    """
    for prefixes, sub in _FN_SUBSYSTEM:
        for p in prefixes:
            if fn.startswith(p):
                return sub, p
    return "", ""


def _fn_subsystem_hint(fn: str) -> str:
    return _fn_subsystem_match(fn)[0]


def _word_in(pattern: str, text: str) -> bool:
    return bool(pattern) and bool(re.search(r"(?<![A-Za-z0-9_])" + re.escape(pattern) + r"(?![A-Za-z0-9_])", text or ""))


# ------------------------------------------------------------
# Structured verdict
# ------------------------------------------------------------

VERDICT_LABELS = {
    "confirmed": "已确认相关",
    "same_area": "同域不同因",
    "not_relevant": "不相关",
    "unverified": "待验证",
}

# bug-classification / symptom tokens that must never be mistaken for a
# kernel function name when mining the RIP symbol out of query text
_RIP_QUERY_STOPWORDS = {
    "use_after_free", "use_after_free_read", "use_after_free_write",
    "double_free", "null_pointer", "null_ptr_deref", "null_ptr",
    "out_of_bounds", "buffer_overflow", "stack_overflow", "heap_overflow",
    "page_fault", "kernel_panic", "general_protection", "divide_error",
    "bug_on", "warning_bug", "deadlock", "soft_lockup", "hard_lockup",
    "rcu_stall", "memory_corruption", "invalid_opcode",
}


def analyze_community_verdict(evidence: dict, crash_features: dict) -> dict:
    """Compare first-hand community evidence against crash features.

    crash_features: {rip_function, call_trace: [fn,...], bug_type}

    Returns {verdict, confidence, reasons[], fixes_rip, touched_files[],
             touched_functions[], trace_hits[]}.
    """
    rip = (crash_features or {}).get("rip_function", "") or ""
    trace_fns = [f for f in ((crash_features or {}).get("call_trace") or []) if f]
    diff = evidence.get("diff") or ""
    message = evidence.get("commit_message") or ""
    issue_body = evidence.get("issue_body") or ""
    prose = f"{message}\n{issue_body}"

    if not evidence.get("fetched"):
        return {"verdict": "unverified", "confidence": "low",
                "reasons": ["无法获取该社区链接的 commit/issue 原文（网络或权限受限），相关性未经一手证据验证"],
                "fixes_rip": False, "touched_files": [], "touched_functions": [], "trace_hits": []}

    parsed = _parse_diff(diff)
    files = parsed["files"]
    hunks_text = "\n".join(parsed["hunks"])
    added_text = parsed["added_text"]
    touched_subs = {_subsystem_of_path(f) for f in files if _subsystem_of_path(f)}
    rip_sub = _fn_subsystem_hint(rip)
    subsystem_match = bool(rip_sub) and (rip_sub in touched_subs or any(s.startswith(rip_sub) or rip_sub.startswith(s) for s in touched_subs if s))

    # No crash-side context to compare against: we hold the patch evidence but
    # cannot judge relevance. Never return a negative verdict in this case.
    if not (rip or trace_fns):
        reasons = []
        if files:
            reasons.append(f"补丁改动文件: {', '.join(files[:3])}" + (f" 等 {len(files)} 个" if len(files) > 3 else ""))
        reasons.append("已获取补丁一手证据，但未提供崩溃特征（RIP 函数/调用栈），无法做代码级相关性判定，标记为待验证")
        return {"verdict": "unverified", "confidence": "low",
                "reasons": reasons,
                "fixes_rip": False, "touched_files": files[:6],
                "touched_functions": sorted(set(re.findall(r"@@[^\n]*?([A-Za-z_][A-Za-z0-9_]*)\s*\(", hunks_text)))[:8],
                "trace_hits": []}

    # functions the patch actually touches (hunk context + added lines matching trace fns)
    trace_hits_added = [f for f in trace_fns if _word_in(f, added_text) or _word_in(f, hunks_text)]
    trace_hits_any = [f for f in trace_fns if _word_in(f, diff) or _word_in(f, prose)]
    hunk_fns = set(re.findall(r"@@[^\n]*?([A-Za-z_][A-Za-z0-9_]*)\s*\(", hunks_text))

    # Crash-path functions may live in different subsystems than the RIP
    # (e.g. hard lockup RIP queued_spin_lock_slowpath -> kernel/locking while
    # the actual fix changes newidle_balance/load_balance -> kernel/sched).
    # A trace function the patch modifies whose OWN subsystem overlaps the
    # patched files is a direct fix of the crash path.
    def _subs_overlap(a: set[str], b: set[str]) -> bool:
        return any(x == y or x.startswith(y) or y.startswith(x) for x in a for y in b if x and y)

    trace_subs = {_fn_subsystem_hint(f) for f in trace_fns if f}
    crash_subs = {s for s in ({rip_sub} | trace_subs) if s}
    trace_added_subs = set()
    for f in trace_hits_added:
        fs = _fn_subsystem_hint(f)
        if fs and (fs in touched_subs or _subs_overlap({fs}, touched_subs)):
            trace_added_subs.add(fs)

    rip_in_added = _word_in(rip, added_text) or _word_in(rip, hunks_text)
    rip_in_diff = _word_in(rip, diff)
    rip_in_prose = _word_in(rip, prose)

    reasons = []
    if files:
        reasons.append(f"补丁改动文件: {', '.join(files[:3])}" + (f" 等 {len(files)} 个" if len(files) > 3 else ""))
    if evidence.get("additions") or evidence.get("deletions"):
        reasons.append(f"补丁规模: +{evidence.get('additions',0)}/-{evidence.get('deletions',0)}")
    if rip_in_added:
        reasons.append(f"崩溃函数 {rip} 出现在补丁修改行/函数上下文中，属于直接修复该崩溃点")
    if trace_hits_added:
        reasons.append(f"补丁修改了调用路径上的函数: {', '.join(trace_hits_added[:4])}")
    if rip_in_prose:
        where = "commit message" if _word_in(rip, message) else "issue 正文"
        reasons.append(f"崩溃函数 {rip} 在{where}中被提及")
    if not (rip_in_added or trace_hits_added or rip_in_prose):
        if subsystem_match or _subs_overlap(touched_subs, crash_subs):
            reasons.append(f"补丁与崩溃路径同属 {', '.join(sorted(crash_subs or {rip_sub} - {''}))} 子系统，但未修改崩溃函数 {rip} 或其调用路径")
        elif touched_subs and crash_subs:
            reasons.append(f"补丁改动子系统为 {', '.join(sorted(touched_subs))}，与崩溃路径子系统 {', '.join(sorted(crash_subs))} 不同")
        else:
            reasons.append("崩溃函数所在内核子系统未能从函数名识别，无法完成子系统级比对")

    # verdict decision
    if rip_in_added:
        verdict, conf = "confirmed", "high"
    elif trace_hits_added and (subsystem_match or trace_added_subs):
        verdict, conf = "confirmed", "high"
    elif rip_in_prose and subsystem_match:
        verdict, conf = "confirmed", "medium"
    elif trace_hits_added:
        # patch modifies a trace function whose subsystem could not be mapped
        verdict, conf = "same_area", "medium"
    elif rip_in_diff or (rip_in_prose and not subsystem_match):
        verdict, conf = "same_area", "medium"
    elif subsystem_match or _subs_overlap(touched_subs, crash_subs):
        verdict, conf = "same_area", "medium"
    elif trace_hits_any:
        verdict, conf = "same_area", "low"
    elif not crash_subs:
        # crash-side subsystems unknown / not identifiable:
        # no positive signal but also no justified negative verdict
        verdict, conf = "unverified", "low"
    else:
        verdict, conf = "not_relevant", "high" if files else "low"

    return {
        "verdict": verdict,
        "confidence": conf,
        "reasons": reasons,
        "fixes_rip": bool(rip_in_added),
        "touched_files": files[:6],
        "touched_functions": sorted(hunk_fns)[:8],
        "trace_hits": sorted(set(trace_hits_added or trace_hits_any))[:6],
    }


# ------------------------------------------------------------
# Backward-compatible entry used by community_retriever
# ------------------------------------------------------------

def _normalize_crash(crash_features: dict | None) -> dict:
    """Normalize crash_features: accept call_trace list or call_trace_signature /
    call_trace_text strings, extracting kernel function names."""
    crash = dict(crash_features or {})
    trace = crash.get("call_trace")
    if isinstance(trace, str):
        trace = [trace]
    fns = [f for f in (trace or []) if isinstance(f, str)]
    sig_text = "\n".join([
        str(crash.get("call_trace_signature", "") or ""),
        str(crash.get("call_trace_text", "") or ""),
    ])
    if sig_text.strip():
        # stack frames look like "? func+0x1f/0x..." or "#5 [addr] func";
        # take the symbol before a "+offset" or the leading column-1 identifier
        for line in sig_text.splitlines():
            m = re.search(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\+\s*0x[0-9a-fA-F]+", line)
            if m:
                fns.append(m.group(1))
            else:
                tok = re.findall(r"\b([a-z_][a-z0-9_]*(?:_[a-z0-9]+)+)\b", line)
                fns.extend(tok[:2])
    crash["call_trace"] = sorted({f.split(".")[0] for f in fns if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", f.split(".")[0])})
    return crash


async def analyze_commit_relevance(
    case: CommunityCase,
    query_text: str,
    crash_features: dict | None = None,
) -> dict:
    """Fetch first-hand evidence for a community case and judge relevance.

    Returns {relevant, reason, verdict, evidence}.
    """
    source_file = case.source_file or ""
    if not source_file:
        return {"relevant": True, "reason": "无来源链接，无法获取上游原文",
                "verdict": "unverified", "evidence": {}}

    evidence = await fetch_community_evidence(source_file, getattr(case, "type", "") or "")
    crash = _normalize_crash(crash_features)
    if not crash.get("rip_function"):
        # fall back: mine rip function name from query text (best effort);
        # skip bug-classification words (use_after_free, null_ptr_deref, ...)
        for tok in re.findall(r"\b([a-z_][a-z0-9_]*(?:_[a-z0-9]+)+)\b", query_text or ""):
            if tok not in _RIP_QUERY_STOPWORDS:
                crash["rip_function"] = tok
                break

    result = analyze_community_verdict(evidence, crash)
    verdict = result["verdict"]
    label = VERDICT_LABELS.get(verdict, verdict)
    reason = f"{label}: " + "；".join(result["reasons"][:2]) if result["reasons"] else label

    # expose trimmed first-hand text on the case for the report; merge with
    # pre-existing evidence keys (e.g. commit_sha stashed by online fallback)
    case.commit_diff = evidence.get("diff", "")[:2000]
    new_evidence = {
        "verdict": verdict,
        "verdict_label": label,
        "confidence": result["confidence"],
        "reasons": result["reasons"],
        "source_kind": evidence.get("source_kind", ""),
        "commit_message": evidence.get("commit_message", ""),
        "commit_author": evidence.get("commit_author", ""),
        "issue_title": evidence.get("issue_title", ""),
        "issue_body_excerpt": (evidence.get("issue_body", "") or "")[:600],
        "touched_files": result["touched_files"],
        "touched_functions": result["touched_functions"],
        "additions": evidence.get("additions", 0),
        "deletions": evidence.get("deletions", 0),
        "html_url": evidence.get("html_url", source_file),
        "fetched": evidence.get("fetched", False),
    }
    case.evidence = {**(case.evidence or {}), **new_evidence}

    return {
        "relevant": verdict in ("confirmed", "same_area"),
        "reason": reason,
        "verdict": verdict,
        "evidence": case.evidence,
    }
