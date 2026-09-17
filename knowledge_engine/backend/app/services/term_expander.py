"""术语扩展服务。

Phase 7 负责把网络安全领域缩写、简称和术语展开成更适合检索的候选词。
当前优先使用本地静态词典，保持结果可解释、可测试。
"""

from __future__ import annotations

TERM_DICTIONARY: dict[str, list[str]] = {
    "等保": ["网络安全等级保护", "GB/T 22239", "等级保护"],
    "sql注入": ["SQL Injection", "SQLi", "注入攻击"],
    "sqli": ["SQL注入", "SQL Injection"],
    "cii": ["关键信息基础设施", "关基"],
    "waf": ["Web Application Firewall", "web 应用防火墙"],
    "edr": ["Endpoint Detection and Response", "终端检测与响应"],
    "cve": ["Common Vulnerabilities and Exposures", "漏洞编号"],
    "个人信息": ["自然人个人身份", "个人身份信息", "可识别自然人的信息"],
}


class TermExpander:
    """Phase 7 安全术语扩展器。"""

    def expand(self, query: str) -> list[str]:
        """根据本地词典返回去重后的扩展词。"""
        normalized_query = query.strip().lower()
        expanded_terms: list[str] = []
        for term, expansions in TERM_DICTIONARY.items():
            if term in normalized_query:
                expanded_terms.extend(expansions)
        return _deduplicate(expanded_terms)


def _deduplicate(items: list[str]) -> list[str]:
    """保持顺序地去重。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
