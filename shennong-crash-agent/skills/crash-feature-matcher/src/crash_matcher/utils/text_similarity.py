"""Shared text similarity utilities: jieba + Jaccard + synonyms expansion"""

import logging
import re

import jieba

logger = logging.getLogger(__name__)

# Suppress noisy synonyms/jieba logs
logging.getLogger("jieba").setLevel(logging.WARNING)

# Synonyms import is optional; gracefully degrade if not available
try:
    import synonyms

    logging.getLogger("synonyms").setLevel(logging.WARNING)
    _HAS_SYNONYMS = True
except Exception:
    _HAS_SYNONYMS = False
    logger.warning("synonyms package not available, synonym expansion disabled")


# Stopwords shared across all tokenizers
_STOPWORDS = set(
    "a an the and or but in on at to for of with by from as is was are were be been being have has had do does did will would could should may might must "
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 那 之 与 及 等 可以 需要 进行 通过 使用 如果 因为 所以 但是 然后 并且 其中 其 为 对 将 被 把 给 让 向 从 到 关于 能够 已经 正在 曾经 过 时候 时间 方式 方法 问题 情况 工作 部分 功能 系统 进程 内核 模块 驱动 文件 设备 信息 数据 代码 调用 函数 指针 地址 内存 错误 失败 异常 崩溃 挂起 死机 重启 启动 运行 返回 处理 检查 设置 配置 修改 修复 解决 更新 升级 添加 删除 调整 优化 实现 导致 引起 触发 产生 发生 出现 造成 由于 当 时 后 前 中 内 外 下 上 里 间 处 些 种 个 条 项 点 面 方 头 部 边 端 侧 层 级 段 节 块 片 组 类 型 态 状 式 制 法 则 准 据 源 果 因 由 故 目 的 地 得 着 过 会 能 可 应 该 当 须 必 须 需 需 须 正 真 假 虚 实 否 非 无 没 不 未 别 莫 勿 别 甭"
    .split()
)


def _preserve_alphanum_tokens(text: str) -> tuple[str, list[str]]:
    """
    Extract alphanumeric+digit tokens (e.g., 3c59x, boomerang_start_xmit) before jieba.
    Returns (cleaned_text, preserved_tokens).
    """
    preserved = []
    # Match English/digit/underscore mixed tokens of length >= 3
    pattern = re.compile(r"[a-zA-Z0-9_][a-zA-Z0-9_.]*[a-zA-Z0-9_]")
    for match in pattern.finditer(text):
        token = match.group(0)
        if len(token) >= 3 and any(c.isalpha() for c in token):
            preserved.append(token.lower())
    # Replace them with spaces so jieba doesn't split them
    cleaned = pattern.sub(" ", text)
    return cleaned, preserved


def tokenize(text: str) -> list[str]:
    """Tokenize text using jieba for Chinese and regex for English."""
    if not text:
        return []
    text = text.strip()
    if not text:
        return []

    cleaned, preserved = _preserve_alphanum_tokens(text)

    # English tokens from cleaned text
    en_tokens = set(
        w.lower()
        for w in re.findall(r"[a-zA-Z_]{2,}", cleaned)
        if w.lower() not in _STOPWORDS
    )
    en_tokens.update(preserved)

    # Chinese tokens via jieba
    cn_tokens = set()
    for tok in jieba.lcut(cleaned):
        tok = tok.strip().lower()
        if not tok or tok in _STOPWORDS:
            continue
        if len(tok) >= 2 and re.search(r"[\u4e00-\u9fa5]", tok):
            cn_tokens.add(tok)

    return list(en_tokens | cn_tokens)


def _expand_with_synonyms(terms: set[str], top_n: int = 2, threshold: float = 0.8) -> set[str]:
    """Expand term set with high-quality synonyms for Chinese terms."""
    if not _HAS_SYNONYMS or not terms:
        return terms
    expanded = set(terms)
    for term in list(terms):
        # Only expand Chinese terms
        if not re.search(r"[\u4e00-\u9fa5]", term):
            continue
        try:
            words, scores = synonyms.nearby(term)
            for w, s in zip(words[1:top_n + 1], scores[1:top_n + 1]):
                if s >= threshold and w.strip() and re.search(r"[\u4e00-\u9fa5]", w):
                    expanded.add(w.strip().lower())
        except Exception:
            continue
    return expanded


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def jaccard_distance(set_a: set[str], set_b: set[str]) -> float:
    return 1.0 - jaccard_similarity(set_a, set_b)


def compute_text_similarity(query: str, doc: str, use_synonyms: bool = True) -> float:
    """
    Compute Jaccard similarity between query and doc.
    If use_synonyms is True, query terms are expanded with synonyms.
    """
    q_terms = set(tokenize(query))
    d_terms = set(tokenize(doc))
    if not q_terms or not d_terms:
        return 0.0
    if use_synonyms:
        q_terms = _expand_with_synonyms(q_terms)
    return jaccard_similarity(q_terms, d_terms)


def get_term_set(text: str, use_synonyms: bool = False) -> set[str]:
    """Return token set, optionally expanded with synonyms."""
    terms = set(tokenize(text))
    if use_synonyms:
        terms = _expand_with_synonyms(terms)
    return terms


def exact_english_overlap(query: str, doc: str) -> int:
    """Count English/technical tokens that appear in both query and doc."""
    # Include tokens starting with digits/letters/underscore, e.g., 3c59x, boomerang_start_xmit
    pattern = re.compile(r"[a-zA-Z0-9_][a-zA-Z0-9_.]{2,}")
    q_tokens = set(w.lower() for w in pattern.findall(query))
    d_tokens = set(w.lower() for w in pattern.findall(doc))
    if not q_tokens:
        return 0
    return len(q_tokens & d_tokens)
