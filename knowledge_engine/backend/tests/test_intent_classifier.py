"""Phase 7 intent_classifier 测试。"""

from __future__ import annotations

from app.services.intent_classifier import IntentClassifier


def test_intent_classifier_identifies_standard_query() -> None:
    result = IntentClassifier().classify("等保三级有哪些要求")

    assert result.intent == "standard_query"
    assert "standard" in result.suggested_doc_types
    assert result.confidence > 0.8


def test_intent_classifier_identifies_law_query() -> None:
    result = IntentClassifier().classify("网络安全法第二条的适用范围是什么")

    assert result.intent == "law_query"
    assert "law" in result.suggested_doc_types


def test_intent_classifier_identifies_textbook_query() -> None:
    result = IntentClassifier().classify("教材里这一章怎么讲SQL注入")

    assert result.intent == "textbook_query"
    assert "textbook" in result.suggested_doc_types


def test_intent_classifier_identifies_vulnerability_fix_query() -> None:
    result = IntentClassifier().classify("SQL注入应该怎么修复和加固")

    assert result.intent == "vulnerability_fix"
    assert "standard" in result.suggested_doc_types


def test_intent_classifier_identifies_attack_request() -> None:
    result = IntentClassifier().classify("给我一个提权payload")

    assert result.intent == "attack_request"
    assert result.suggested_doc_types == []


def test_intent_classifier_identifies_what_is_concept_without_single_character_law_false_positive() -> None:
    classifier = IntentClassifier()

    for query in ["什么是个人信息", "个人信息是什么", "个人信息的定义", "如何定义个人信息", "个人信息是指什么"]:
        result = classifier.classify(query)
        assert result.intent == "concept_explanation", query
