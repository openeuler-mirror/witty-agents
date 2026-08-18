"""Query expansion / multi-query retrieval for community cases.

Generate several search query variants from the original crash query to improve
RAG recall. By default uses fast rule-based expansion; LLM-based expansion
can be enabled via config.
"""

import re
import asyncio
import logging
from typing import Optional

import httpx

from ..config import Config
from ..utils.text_similarity import tokenize

logger = logging.getLogger(__name__)


# Common Chinese-English crash term mapping for rule-based expansion
_CN_TO_EN = {
    "空指针": "NULL pointer",
    "解引用": "dereference",
    "内核崩溃": "kernel crash panic",
    "内核挂起": "kernel hang",
    "死锁": "deadlock",
    "软死锁": "soft lockup",
    "硬死锁": "hard lockup",
    "死机": "system hang",
    "重启": "reboot",
    "崩溃": "crash panic",
    "挂起": "hang",
    "内存": "memory",
    "文件系统": "filesystem",
    "网络": "network",
    "驱动": "driver",
    "中断": "interrupt irq",
    "竞态": "race condition",
    "越界": "out of bounds",
    "泄漏": "leak",
    "未初始化": "uninitialized",
    "警告": "warning",
    "报错": "error",
}

# Acronyms / short technical tokens that should be preserved even if short
_TECH_SHORT_FORMS = {
    "gcwq": "gcwq workqueue",
    "pciback": "pciback pci backend",
    "pcibk": "pciback pci backend",
    "slub": "slub slab",
    "cma": "cma contiguous memory allocator",
    "rcu": "rcu read copy update",
    "wq": "wq workqueue",
}


def _normalize(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _extract_english_tokens(text: str) -> str:
    """Extract English/technical tokens to form a compact search query."""
    tokens = tokenize(text)
    # Prefer longer/more technical tokens
    en_tokens = [t for t in tokens if re.search(r"[a-zA-Z0-9_]", t) and len(t) >= 2]
    # Boost tokens that look like kernel identifiers (contain underscores or mixed case)
    en_tokens.sort(key=lambda t: (len(t), "_" in t or any(c.isupper() for c in t)), reverse=True)
    cn_tokens = [t for t in tokens if re.search(r"[\u4e00-\u9fff]", t) and len(t) >= 2]
    selected = en_tokens[:8] + cn_tokens[:3]
    return " ".join(selected)


def _english_only_variant(text: str) -> str:
    """Keep only English/number/underscore tokens; strip Chinese filler words.

    Useful when the Chinese paraphrase dilutes the technical signal.
    """
    tokens = tokenize(text)
    en_tokens = [t for t in tokens if re.fullmatch(r"[a-zA-Z0-9_]+", t) and len(t) >= 2]
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for t in en_tokens:
        low = t.lower()
        if low not in seen:
            seen.add(low)
            unique.append(t)
    return " ".join(unique[:10])


def _extract_stack_function(text: str) -> Optional[str]:
    """Extract the first concrete function name from a Call Trace / RIP line."""
    # Call Trace: func [args]
    m = re.search(r"Call Trace:\s*\[?\s*([a-zA-Z0-9_]+)", text, re.IGNORECASE)
    if m:
        return m.group(1)
    # RIP: 0010:func+0x...
    m = re.search(r"RIP:\s*\S+[:\s]+([a-zA-Z0-9_]+)", text, re.IGNORECASE)
    if m:
        return m.group(1)
    # IP: func+0x...
    m = re.search(r"\bIP:\s*([a-zA-Z0-9_]+)", text, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _expand_acronyms(text: str) -> str:
    """Expand known short technical forms to improve recall."""
    lowered = text.lower()
    extras = []
    for short, expansion in _TECH_SHORT_FORMS.items():
        if re.search(rf"\b{re.escape(short)}\b", lowered):
            extras.append(expansion)
    if extras:
        return f"{text} {' '.join(extras)}"
    return text


def _add_kernel_version(query: str, kernel_version: str) -> str:
    if not kernel_version:
        return query
    return f"{query} {kernel_version}".strip()


def _translate_key_terms(query: str) -> str:
    """Simple rule-based translation of common Chinese crash terms."""
    result = query
    for cn, en in _CN_TO_EN.items():
        if cn in result:
            result = result.replace(cn, f"{cn} {en}")
    return result


def expand_query(query_text: str, kernel_version: str = "", anomaly_features: dict = None) -> list[str]:
    """
    Generate search query variants.

    Returns a list of unique queries, ordered from most specific to most general.
    """
    cfg = Config().get().community
    if not cfg.enable_query_expansion:
        return [_normalize(query_text)]

    variants = []

    # 1. Original normalized query
    norm = _normalize(query_text)
    variants.append(norm)

    # 2. Query + kernel version (helps when version matters)
    if cfg.expansion_include_kernel and kernel_version:
        variants.append(_normalize(_add_kernel_version(norm, kernel_version)))

    # 3. English/technical enriched variant (for mixed Chinese-English queries)
    if cfg.expansion_include_english:
        enriched = _normalize(_translate_key_terms(norm))
        if enriched != norm:
            variants.append(enriched)

    # 4. Compact keyword variant (extract core tokens, English prioritized)
    compact = _normalize(_extract_english_tokens(norm))
    if compact and compact != norm and len(compact) >= 3:
        variants.append(compact)

    # 5. English-only variant (strip Chinese noise)
    eng_only = _normalize(_english_only_variant(norm))
    if eng_only and eng_only != norm and eng_only != compact and len(eng_only) >= 3:
        variants.append(eng_only)

    # 6. Stack-function focused variant (very specific for crash traces)
    func = _extract_stack_function(norm)
    if func:
        func_variant = _normalize(f"{func} {norm}")
        if func_variant != norm:
            variants.append(func_variant)

    # 7. Acronym expansion variant
    acronym = _normalize(_expand_acronyms(norm))
    if acronym != norm:
        variants.append(acronym)

    # 8. Anomaly keyword variant (changes 5 + 4c) — inject error_keywords
    if anomaly_features and anomaly_features.get("error_keywords"):
        ekws = " ".join(anomaly_features["error_keywords"][:6])
        anomaly_variant = _normalize(f"{norm} {ekws}")
        if anomaly_variant != norm:
            variants.append(anomaly_variant)

    # 9. LLM-based multi-angle query expansion (changes 4) — controlled by config
    adv_cfg = getattr(Config().get(), 'advanced', None)
    if adv_cfg and getattr(adv_cfg, 'enable_llm_query_generation', False):
        try:
            llm_variants = _generate_llm_queries_sync(query_text, norm)
            for v in llm_variants:
                if v and v != norm:
                    variants.append(_normalize(v))
        except Exception:
            logger.debug("LLM query expansion failed", exc_info=True)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for v in variants:
        key = v.lower()
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return unique


LLM_QUERY_EXPANSION_PROMPT = """你是 Linux 内核崩溃分析专家。根据以下崩溃特征，生成3个不同搜索角度的 query，用于在社区案例库中检索相关 commit/issue。

崩溃信息: {query_text}

生成3个 query，每行一个，不要加序号、Markdown 或解释:
1. 精确匹配角度: 函数名+模块名+崩溃类型（英文技术词为主）
2. 泛化角度: 核心关键词+技术术语（4-8词，英文>60%）
3. 因果角度: 推测的根因+修复方向（技术词为主）

输出格式: 每行一个 query，不要空行、不要序号。"""


def _generate_llm_queries_sync(query_text: str, norm: str) -> list[str]:
    """Generate multi-angle queries via LLM (sync wrapper)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return []
    except RuntimeError:
        pass
    try:
        return asyncio.run(_generate_llm_queries(query_text, norm))
    except Exception:
        return []


async def _generate_llm_queries(query_text: str, norm: str) -> list[str]:
    """Call LLM to generate multi-angle search queries."""
    llm_cfg = Config().get().llm_scorer
    if not llm_cfg.enabled or not llm_cfg.api_key:
        return []

    prompt = LLM_QUERY_EXPANSION_PROMPT.replace("{query_text}", query_text)
    payload = {
        "model": llm_cfg.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 200,
    }
    headers = {
        "Authorization": f"Bearer {llm_cfg.api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=llm_cfg.timeout) as client:
            resp = await client.post(
                f"{llm_cfg.base_url.rstrip('/')}/chat/completions",
                json=payload, headers=headers
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return [line.strip() for line in content.strip().split("\n") if line.strip()][:3]
    except Exception:
        return []


def build_query_from_features(bug_type: str = "", rip_function: str = "",
                              bug_key: str = "", related_modules: list[str] = None,
                              anomaly_features: dict = None) -> str:
    """Build optimal query text from crash features for community retrieval."""
    parts = []
    if bug_type:
        parts.append(bug_type)
    if rip_function:
        parts.append(rip_function)
    if bug_key:
        bk = bug_key[:60]
        if bk not in " ".join(parts):
            parts.append(bk)
    if related_modules:
        parts.extend(related_modules[:3])

    # Inject anomaly error_keywords for better recall
    if anomaly_features and anomaly_features.get("error_keywords"):
        ekws = [k for k in anomaly_features["error_keywords"][:5]
                if len(k) > 2 and k not in " ".join(parts)]
        parts.extend(ekws)

    return " ".join(parts)
