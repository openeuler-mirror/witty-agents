"""L2 RAG 查询策略 — 每种 bug_key → RAG SearchJsonConfig + 策略名"""

from ..config import Config
from ..config_models import L2SearchRule, SearchConfig, Expression, LogicalExpression
from ..models import CrashFeatures


def _get_rules() -> list[L2SearchRule]:
    return Config().get().l2_search_rules


def build_l2_config(feature: CrashFeatures, kb_id: str) -> SearchConfig | None:
    for rule in _get_rules():
        patterns = rule.bug_key_patterns
        if "*" in patterns or any(p in feature.bug_key for p in patterns):
            query = _build_query(feature, rule.query_from)
            expressions = [
                Expression(field="source", type="string", operator="eq", value="issue"),
            ]
            if rule.filter_bug_type and feature.bug_type:
                expressions.append(Expression(field="bug_type", type="string",
                    operator="eq", value=feature.bug_type))

            if rule.search_mode == "like":
                like_field = "rip_function"
                if rule.query_from == "call_trace_top":
                    like_field = "call_trace_signature"
                expressions.append(Expression(field=like_field, type="string",
                    operator="like", value=query))

            query_val = "" if rule.search_mode == "like" else query
            return SearchConfig(
                kb_id=kb_id, query=query_val, top_k=15,
                logical_expression=LogicalExpression(operator="and", expressions=expressions),
                semantic_keys=rule.semantic_keys, ratio=rule.ratio,
            )
    return None


def get_strategy_name(bug_key: str) -> str:
    for rule in _get_rules():
        patterns = rule.bug_key_patterns
        if "*" in patterns or any(p in bug_key for p in patterns):
            return rule.strategy
    return "stack_similarity"


def _build_query(feature: CrashFeatures, source: str) -> str:
    if source == "rip_function":
        return feature.rip_function or feature.bug_key
    if source == "call_trace_top":
        return feature.call_trace_functions[0] if feature.call_trace_functions else (feature.rip_function or "")
    if source == "call_trace_text":
        return feature.call_trace[:500] if feature.call_trace else (feature.bug or feature.bug_key)
    return feature.rip_function or ""
