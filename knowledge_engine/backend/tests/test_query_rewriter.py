"""Phase 7 query_rewriter 测试。"""

from __future__ import annotations

from app.services.intent_classifier import IntentResult
from app.services.query_rewriter import QueryRewriter
from app.services.term_expander import TermExpander


def test_term_expander_expands_security_terms_without_duplicates() -> None:
    expanded_terms = TermExpander().expand("等保和WAF分别是什么")

    assert "网络安全等级保护" in expanded_terms
    assert "GB/T 22239" in expanded_terms
    assert "Web Application Firewall" in expanded_terms
    assert len(expanded_terms) == len(set(term.lower() for term in expanded_terms))


def test_term_expander_expands_personal_information_terms() -> None:
    expanded_terms = TermExpander().expand("什么是个人信息")

    assert "自然人个人身份" in expanded_terms
    assert "个人身份信息" in expanded_terms


def test_query_rewriter_builds_standard_query_payload() -> None:
    intent = IntentResult(
        intent="standard_query",
        confidence=0.92,
        reason="命中了标准类关键词",
        suggested_doc_types=["standard", "policy"],
    )

    result = QueryRewriter().rewrite(
        "等保三级访问控制要求",
        intent=intent,
        expanded_terms=["网络安全等级保护", "GB/T 22239"],
    )

    assert result.rewritten_query.startswith("围绕网络安全标准/等级保护要求检索：")
    assert result.search_keywords[0] == "等保三级访问控制要求"
    assert "网络安全等级保护" in result.search_keywords
    assert "standard" in result.search_keywords
    assert result.sub_queries[0] == "等保三级访问控制要求"
    assert any("GB/T 22239" in item for item in result.sub_queries)


def test_query_rewriter_keeps_default_text_for_unclassified_query() -> None:
    intent = IntentResult(
        intent="out_of_scope",
        confidence=0.55,
        reason="未命中规则",
        suggested_doc_types=["note"],
    )

    result = QueryRewriter().rewrite(
        "零信任有哪些核心思想",
        intent=intent,
        expanded_terms=[],
    )

    assert result.rewritten_query == "零信任有哪些核心思想"
    assert result.search_keywords == ["零信任有哪些核心思想", "note"]
    assert result.sub_queries == ["零信任有哪些核心思想"]
