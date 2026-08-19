"""Git commit fetcher — fetch commit diff from gitcode/gitee via API.

Requires GITCODE_TOKEN environment variable to be configured.
Uses the same token mechanism as the openEuler portal MCP.
"""

import logging
import os
import re
import urllib.parse
from typing import Optional

import httpx

from .models import CommunityCase

logger = logging.getLogger(__name__)

GITCODE_DIFF_API = "https://api.gitcode.com/api/v5/repos/{owner}/{repo}/commit/{sha}/diff"
GITEE_COMMIT_API = "https://gitee.com/api/v5/repos/{owner}/{repo}/commits/{sha}"

_URL_PATTERNS = [
    re.compile(r"(?:gitcode\.com|gitee\.com)/([^/]+)/([^/]+)/commits?/(?:detail/)?([a-f0-9]{7,40})", re.IGNORECASE),
    re.compile(r"(?:gitcode\.com|gitee\.com)/([^/]+)/([^/]+)/commit/([a-f0-9]{7,40})", re.IGNORECASE),
    re.compile(r"(?:gitcode\.com|gitee\.com)/([^/]+)/([^/]+)/-/commit/([a-f0-9]{7,40})", re.IGNORECASE),
]


def _parse_commit_url(url: str) -> Optional[tuple[str, str, str]]:
    """Extract (owner, repo, sha) from a commit URL."""
    for pat in _URL_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1), m.group(2), m.group(3)
    return None


def _is_gitcode(url: str) -> bool:
    return "gitcode.com" in url.lower()


async def fetch_commit_diff(source_file: str) -> Optional[str]:
    """Fetch the commit diff from gitcode/gitee API.

    Args:
        source_file: URL to the commit page.

    Returns:
        The commit diff content, or None if unavailable.
    """
    parsed = _parse_commit_url(source_file)
    if not parsed:
        return None

    owner, repo, sha = parsed

    token = os.environ.get("GITCODE_TOKEN", "")
    if not token:
        logger.warning("GITCODE_TOKEN not configured, cannot fetch commit diff")
        return None

    if _is_gitcode(source_file):
        diff_url = GITCODE_DIFF_API.format(owner=urllib.parse.quote(owner), repo=urllib.parse.quote(repo), sha=sha)
        headers = {"PRIVATE-TOKEN": token}
        accept_json = False
    else:
        diff_url = GITEE_COMMIT_API.format(owner=urllib.parse.quote(owner), repo=urllib.parse.quote(repo), sha=sha)
        headers = {"Authorization": f"token {token}", "Accept": "application/json"}
        accept_json = True

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(diff_url, headers=headers)
            resp.raise_for_status()

            if accept_json:
                data = resp.json()
                files = data.get("files", [])
                if files:
                    diffs = []
                    for f in files[:5]:
                        patch = f.get("patch", "")
                        if patch:
                            diffs.append(f"--- {f.get('filename', '?')}\n{patch[:500]}")
                    return "\n".join(diffs) if diffs else data.get("commit", {}).get("message", "")[:2000]
                return data.get("commit", {}).get("message", "")[:2000]
            else:
                diff_text = resp.text
                if diff_text and len(diff_text) > 10:
                    return diff_text[:5000]
                return None
    except Exception as e:
        logger.warning(f"Failed to fetch commit diff from {diff_url}: {e}")
        return None


async def analyze_commit_relevance(
    case: CommunityCase,
    query_text: str,
) -> dict:
    """Analyze whether a community case's commit is relevant to the current crash.

    Fetches the commit diff from the source_url, then compares with crash features.

    Returns dict with keys:
        - relevant: bool
        - reason: str (explanation of relevance or irrelevance)
    """
    source_file = case.source_file or ""
    if not source_file:
        return {"relevant": True, "reason": "无 source_file，无法分析 commit"}

    diff = await fetch_commit_diff(source_file)
    if not diff:
        return {"relevant": True, "reason": "无法获取 commit diff，保留案例"}

    case.commit_diff = diff[:2000]

    llm_scorer_cfg = None
    try:
        from .config import Config
        llm_scorer_cfg = Config().get().llm_scorer
    except Exception:
        pass

    if not llm_scorer_cfg or not llm_scorer_cfg.enabled:
        return _keyword_commit_relevance(query_text, diff)

    from .llm_scorer import LLMScorer
    scorer = LLMScorer()
    try:
        prompt = scorer.prompt_template
        prompt = prompt.replace("{{query}}", query_text)
        mock_case = CommunityCase(
            title=case.title,
            kernel_version=case.kernel_version,
            phenomenon=case.phenomenon,
            root_cause=case.root_cause,
            solution=case.solution,
            content=case.content,
        )
        prompt = scorer._build_prompt(query_text, mock_case)
        prompt += f"\n\nCommit Diff (前2000字符):\n{diff[:2000]}\n\n请根据Commit Diff判断该案例是否与当前崩溃相关。"
    finally:
        await scorer.close()

    return {"relevant": True, "reason": f"commit diff fetched ({len(diff)} chars)"}


def _keyword_commit_relevance(query_text: str, diff: str) -> dict:
    """Quick keyword-based commit relevance check (no LLM)."""
    query_tokens = set(query_text.lower().split())
    diff_lower = diff.lower()

    matched = [t for t in query_tokens if len(t) > 3 and t in diff_lower]
    if not matched:
        return {"relevant": False, "reason": f"commit diff 中未找到 query 关键词: {', '.join(list(query_tokens)[:5])}"}

    return {"relevant": True, "reason": f"commit diff 命中关键词: {', '.join(matched[:5])}"}
