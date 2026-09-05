"""LLM-based relevance scoring for community cases.

Provides an Agent/LLM scorer that evaluates how well a retrieved community case
matches a crash query, replacing or augmenting the strict keyword/Jaccard scorer.
"""

import asyncio
import json
import logging
import random
import re
from typing import Optional

import httpx

from .config import Config
from .models import CommunityCase, ScoreDetails

logger = logging.getLogger(__name__)

# Concurrency limit to avoid provider rate limits (e.g. 429 Too Many Requests)
# Free-tier providers (e.g. SiliconFlow) often have strict per-minute limits.
# For production with higher quota, increase concurrency and reduce interval.
_MAX_CONCURRENT_LLM_REQUESTS = 1
_MAX_RETRIES = 5
_BASE_RETRY_DELAY = 2.0  # seconds
_PER_REQUEST_MIN_INTERVAL = 1.0  # seconds between requests within the semaphore

_llm_semaphore: Optional[asyncio.Semaphore] = None


_last_request_time: Optional[float] = None


def _get_llm_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_LLM_REQUESTS)
    return _llm_semaphore


async def _throttle():
    """Enforce a minimum interval between LLM requests to avoid rate limits."""
    global _last_request_time
    import time
    now = time.monotonic()
    if _last_request_time is not None:
        elapsed = now - _last_request_time
        if elapsed < _PER_REQUEST_MIN_INTERVAL:
            await asyncio.sleep(_PER_REQUEST_MIN_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


DEFAULT_SCORING_PROMPT = """你是一位资深的 Linux 内核崩溃分析专家。请根据用户提供的崩溃查询（Query）和候选社区案例（Case），判断该案例与当前崩溃的关联程度，并给出 0-100 的匹配分数。

打分原则：
- 如果 Query 中的核心模块/驱动/函数名（如 xfs、amdgpu、mvpp2、workqueue、fuse_lookup）与 Case 的标题/现象/根因中的模块一致，分数应偏高（≥70）。
- 如果 Query 只是通用症状（如 "kernel NULL pointer dereference"、"kernel paging request"、"Kernel panic"），而 Case 涉及完全不同的模块，即使症状字面相似，分数也应偏低（≤55），因为参考意义有限。
- 如果 Query 与 Case 的标题高度匹配或核心函数名相同，优先考虑模块一致性给出高分。
- 如果 Case 的解决方案对 Query 描述的问题没有直接参考价值，应扣分。

分数含义：
- 90-100：几乎完全匹配，症状、模块、根因均一致，可直接参考。
- 70-89：高度相关，模块和根因匹配，症状相似。
- 55-69：有一定关联，模块或症状部分匹配，但不够直接。
- 20-54：弱相关，仅个别关键词相同或症状泛化。
- 0-19：几乎无关。

评分维度（总分 100）：
1. 症状/现象相似度（0-30）：具体错误信息、栈顶函数、调用链是否匹配
2. 模块/组件匹配（0-25）：驱动、子系统、架构是否一致
3. 根因匹配（0-25）：根本原因是否相同或高度相似
4. 解决方案可参考性（0-15）：Case 的修复方案能否用于 Query 场景
5. 版本/上下文适配（0-5）：内核版本、架构上下文是否兼容

输出要求（必须严格遵守）：
- 第一行：SCORE: <0-100 的整数>
- 第二行：REASON: <30-80字的简短理由，必须说明模块是否匹配>
- 不要输出任何其他内容、Markdown、代码块或解释。

Query:
{{query}}

Candidate Case:
标题: {{title}}
内核版本: {{kernel_version}}
现象: {{phenomenon}}
根因: {{root_cause}}
解决方案: {{solution}}
内容: {{content}}
"""


class LLMScorer:
    """OpenAI-compatible LLM scorer for community case relevance."""

    def __init__(self):
        cfg = Config().get().llm_scorer
        self.api_key = cfg.api_key
        self.base_url = cfg.base_url.rstrip("/")
        self.model = cfg.model
        self.timeout = cfg.timeout
        self.temperature = cfg.temperature
        self.max_tokens = cfg.max_tokens
        self.prompt_template = cfg.prompt_template or DEFAULT_SCORING_PROMPT
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def _build_prompt(self, query_text: str, case: CommunityCase) -> str:
        return (
            self.prompt_template
            .replace("{{query}}", query_text or "")
            .replace("{{title}}", case.title or "")
            .replace("{{kernel_version}}", case.kernel_version or "")
            .replace("{{phenomenon}}", case.phenomenon or "")
            .replace("{{root_cause}}", case.root_cause or "")
            .replace("{{solution}}", case.solution or "")
            .replace("{{content}}", case.content or "")
        )

    @staticmethod
    def _parse_score(text: str) -> tuple[float, str]:
        """Extract SCORE and REASON from LLM output."""
        text = text.strip()
        score = 0.0
        reason = ""
        # Parse SCORE: line
        m_score = re.search(r"^SCORE:\s*(\d+(?:\.\d+)?)", text, re.MULTILINE | re.IGNORECASE)
        if m_score:
            score = float(m_score.group(1))
        else:
            # Fallback: any standalone number 0-100
            m_fallback = re.search(r"\b(\d{1,2}(?:\.\d+)?|100)\b", text)
            if m_fallback:
                score = float(m_fallback.group(1))
        # Parse REASON: line
        m_reason = re.search(r"^REASON:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
        if m_reason:
            reason = m_reason.group(1).strip()
        else:
            reason = text[:200].replace("\n", " ")
        score = max(0.0, min(100.0, score))
        return score, reason

    async def _call_llm(self, payload: dict) -> dict:
        """Call LLM API with concurrency control and retry on rate limits."""
        async with _get_llm_semaphore():
            await _throttle()
            last_err = None
            for attempt in range(_MAX_RETRIES):
                try:
                    resp = await self.client.post("/chat/completions", json=payload)
                    # Rate limit -> retry with backoff
                    if resp.status_code == 429:
                        delay = _BASE_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
                        logger.warning(f"LLM rate limit (429), retrying in {delay:.1f}s (attempt {attempt + 1}/{_MAX_RETRIES})")
                        await asyncio.sleep(delay)
                        last_err = httpx.HTTPStatusError(
                            "429 Too Many Requests", request=resp.request, response=resp
                        )
                        continue
                    resp.raise_for_status()
                    return resp.json()
                except httpx.HTTPStatusError as e:
                    # Server errors (5xx) also retry
                    if e.response.status_code >= 500:
                        delay = _BASE_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
                        logger.warning(f"LLM server error {e.response.status_code}, retrying in {delay:.1f}s")
                        await asyncio.sleep(delay)
                        last_err = e
                        continue
                    raise
                except Exception as e:
                    raise
            raise last_err or RuntimeError("LLM request failed after retries")

    async def score_case(self, query_text: str, case: CommunityCase) -> tuple[float, ScoreDetails]:
        """Score a single case against the query using LLM."""
        if not self.api_key or not self.model:
            return 0.0, ScoreDetails(total=0.0, reason="LLM scorer not configured")
        prompt = self._build_prompt(query_text, case)
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        try:
            data = await self._call_llm(payload)
            content = data["choices"][0]["message"]["content"]
            score, reason = self._parse_score(content)
        except Exception as e:
            logger.warning(f"LLM scoring failed: {e}")
            return 0.0, ScoreDetails(total=0.0, reason=f"LLM error: {e}")

        case.match_score = round(score / 100.0, 4)
        details = ScoreDetails(
            kernel_version_score=0.0,
            title_score=0.0,
            content_score=0.0,
            exact_token_score=0.0,
            solution_score=0.0,
            total=round(score, 2),
            reason=reason,
        )
        return score, details

    async def score_cases(
        self, query_text: str, cases: list[CommunityCase]
    ) -> list[CommunityCase]:
        """Score a list of cases concurrently."""
        if not cases:
            return cases
        results = await asyncio.gather(
            *[self.score_case(query_text, c) for c in cases]
        )
        for c, (score, details) in zip(cases, results):
            c.score = score
            c.score_details = details
        return cases


# ------------------------------------------------------------
# Chinese structured summary for verified upstream commits
# ------------------------------------------------------------

COMMIT_SUMMARY_PROMPT = """你是一位资深的 Linux 内核崩溃分析专家。下面是一个已经过一手代码证据（commit diff）确认、与当前崩溃直接相关的上游补丁。请用简体中文为崩溃分析报告撰写该补丁的结构化摘要。

严格要求：
- 全部使用简体中文；但内核函数名、文件名、宏/枚举名、子系统名（例如 nft_verdict_init、net/netfilter/nf_tables_api.c、NF_QUEUE、KASAN、use-after-free）必须保持英文原样，禁止翻译。
- phenomenon：1-2 句，描述该补丁修复的问题现象（触发条件、错误类型、崩溃位置）。
- root_cause：1-2 句，说明代码层面的根本原因。
- solution：1-2 句，说明补丁的修复手法。
- 只允许依据下面给出的材料，不得编造材料中没有的信息；每个字段不超过 120 个汉字。
- 只输出一个 JSON 对象，不要 Markdown 代码块、不要任何额外解释：
{"phenomenon": "...", "root_cause": "...", "solution": "..."}

当前崩溃特征：
{{crash}}

补丁材料：
标题: {{title}}
改动文件: {{files}}
修改函数: {{functions}}
commit message 摘要:
{{message}}
案例库中已有的英文描述（如有，作为参考材料，可据其内容改写为中文）:
现象: {{phenomenon}}
根因: {{root_cause}}
方案: {{solution}}
"""


def _parse_summary_json(text: str) -> dict:
    """Extract the {phenomenon, root_cause, solution} object from LLM output."""
    if not text:
        return {}
    t = text.strip()
    # strip ```json ... ``` fences if present
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE | re.MULTILINE)
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        data = json.loads(t[start:end + 1])
    except Exception:
        return {}
    out = {}
    for k in ("phenomenon", "root_cause", "solution"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()[:400]
    return out


async def summarize_commit_case(
    case: CommunityCase,
    crash_text: str,
) -> bool:
    """Fill ``case.phenomenon/root_cause/solution`` with a Chinese structured
    summary derived from the verified commit evidence. Returns True on success.

    Uses the shared [llm_scorer] config; silently degrades (returns False) when
    the LLM is not configured or the call/parse fails.
    """
    cfg = Config().get().llm_scorer
    if not cfg.api_key or not cfg.model or not cfg.base_url:
        return False
    ev = case.evidence or {}
    message = (ev.get("commit_message") or case.content or "")[:1500]
    if not message:
        return False
    files = ", ".join(ev.get("touched_files") or []) or "-"
    functions = ", ".join(f"{f}()" for f in (ev.get("touched_functions") or [])) or "-"

    scorer = LLMScorer()
    try:
        prompt = (
            COMMIT_SUMMARY_PROMPT
            .replace("{{crash}}", (crash_text or "")[:600])
            .replace("{{title}}", case.title or "")
            .replace("{{files}}", files)
            .replace("{{functions}}", functions)
            .replace("{{message}}", message)
            .replace("{{phenomenon}}", (case.phenomenon or "-")[:300])
            .replace("{{root_cause}}", (case.root_cause or "-")[:300])
            .replace("{{solution}}", (case.solution or "-")[:300])
        )
        payload = {
            "model": scorer.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 600,
        }
        data = await scorer._call_llm(payload)
        content = data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning(f"LLM commit summary failed for {case.title[:60]}: {e}")
        return False
    finally:
        await scorer.close()

    summary = _parse_summary_json(content)
    if len(summary) < 2:
        logger.debug("LLM commit summary unparseable, skipped: %s", content[:200])
        return False
    if summary.get("phenomenon"):
        case.phenomenon = summary["phenomenon"]
    if summary.get("root_cause"):
        case.root_cause = summary["root_cause"]
    if summary.get("solution"):
        case.solution = summary["solution"]
    case.evidence = {**(case.evidence or {}), "summary_zh": True}
    return True

