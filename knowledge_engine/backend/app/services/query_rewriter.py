"""查询改写服务。

Phase 7 负责把用户自然语言问题整理为更适合检索的 rewritten query，
同时给出搜索关键词与可并行尝试的子查询。
当前优先使用规则生成，避免过度发挥改变原始语义。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.intent_classifier import IntentResult


@dataclass(slots=True)
class QueryRewriteResult:
    """查询改写输出。"""

    rewritten_query: str
    search_keywords: list[str] = field(default_factory=list)
    sub_queries: list[str] = field(default_factory=list)


class QueryRewriter:
    """Phase 7 查询改写器。"""

    def rewrite(self, query: str, *, intent: IntentResult, expanded_terms: list[str]) -> QueryRewriteResult:
        """把原始问题整理成更适合检索的表达。"""
        normalized_query = query.strip()
        keyword_parts = [normalized_query, *expanded_terms, *intent.suggested_doc_types]
        search_keywords = _deduplicate([part for part in keyword_parts if part])

        if intent.intent == "standard_query":
            rewritten_query = f"围绕网络安全标准/等级保护要求检索：{normalized_query}"
        elif intent.intent == "law_query":
            rewritten_query = f"围绕法规条文与适用要求检索：{normalized_query}"
        elif intent.intent == "textbook_query":
            rewritten_query = f"围绕教材/手册中的概念说明检索：{normalized_query}"
        elif intent.intent == "vulnerability_fix":
            rewritten_query = f"围绕修复、缓解、加固建议检索：{normalized_query}"
        elif intent.intent == "comparison":
            rewritten_query = f"围绕差异、对比与适用边界检索：{normalized_query}"
        else:
            rewritten_query = normalized_query

        sub_queries = _deduplicate(
            [
                normalized_query,
                *[f"{normalized_query} {term}" for term in expanded_terms[:2]],
            ]
        )
        return QueryRewriteResult(
            rewritten_query=rewritten_query,
            search_keywords=search_keywords,
            sub_queries=sub_queries,
        )


def _deduplicate(items: list[str]) -> list[str]:
    """保持顺序地去重。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
