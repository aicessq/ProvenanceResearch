"""意图分类服务。

Phase 7 负责识别用户问题主要属于哪类安全知识请求，
用于后续 query rewrite、术语扩展和 filter 补全。
当前优先采用规则分类，保留后续 LLM 细化空间。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class IntentResult:
    """意图分类输出。"""

    intent: str
    confidence: float
    reason: str
    suggested_doc_types: list[str] = field(default_factory=list)


class IntentClassifier:
    """Phase 7 用户问题意图分类器。"""

    def classify(self, query: str) -> IntentResult:
        """使用规则识别问题主要意图。"""
        normalized_query = query.strip().lower()

        if any(keyword in normalized_query for keyword in ["绕过waf", "payload", "getshell", "提权", "横向移动"]):
            return IntentResult(
                intent="attack_request",
                confidence=0.98,
                reason="命中了明显攻击或绕过关键词",
                suggested_doc_types=[],
            )
        if any(keyword in normalized_query for keyword in ["等保", "gb/t", "标准", "基线", "三级", "四级"]):
            return IntentResult(
                intent="standard_query",
                confidence=0.92,
                reason="命中了标准、等级保护或规范类关键词",
                suggested_doc_types=["standard", "policy"],
            )
        if any(keyword in normalized_query for keyword in ["法律", "法规", "条例", "规定", "办法", "条款", "第"]):
            return IntentResult(
                intent="law_query",
                confidence=0.85,
                reason="命中了法规条文相关关键词",
                suggested_doc_types=["law", "regulation", "policy"],
            )
        if any(keyword in normalized_query for keyword in ["什么是", "是什么", "的定义", "如何定义", "是指什么", "原理", "概念", "为什么"]):
            return IntentResult(
                intent="concept_explanation",
                confidence=0.88,
                reason="问题更偏概念解释、定义与原理说明",
                suggested_doc_types=["law", "regulation", "standard", "textbook", "manual", "note"],
            )
        if any(keyword in normalized_query for keyword in ["教材", "课本", "手册", "怎么讲", "章节"]):
            return IntentResult(
                intent="textbook_query",
                confidence=0.90,
                reason="命中了教材、手册或章节类关键词",
                suggested_doc_types=["textbook", "manual", "note"],
            )
        if any(keyword in normalized_query for keyword in ["修复", "整改", "加固", "修补", "补丁"]):
            return IntentResult(
                intent="vulnerability_fix",
                confidence=0.88,
                reason="命中了修复、整改或加固类关键词",
                suggested_doc_types=["manual", "note", "standard"],
            )
        if any(keyword in normalized_query for keyword in ["区别", "对比", "比较"]):
            return IntentResult(
                intent="comparison",
                confidence=0.82,
                reason="问题更像比较多个概念、制度或对象",
                suggested_doc_types=["law", "standard", "textbook"],
            )
        if any(keyword in normalized_query for keyword in ["总结", "概括", "梳理"]):
            return IntentResult(
                intent="summary",
                confidence=0.80,
                reason="问题目标更像总结与归纳",
                suggested_doc_types=["law", "standard", "textbook", "note"],
            )

        return IntentResult(
            intent="out_of_scope",
            confidence=0.55,
            reason="未命中明确安全知识意图规则，暂按泛化问题处理",
            suggested_doc_types=["note"],
        )
