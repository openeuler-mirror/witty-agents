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

