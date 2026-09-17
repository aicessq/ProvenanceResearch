"""安全防护服务（攻击性请求识别）。

Phase 7 开始把安全边界正式放到查询链路最前面。
本模块优先使用规则判定 allow / refuse / redirect；
只有规则不足以判断时，才为后续 LLM 判断预留扩展点。
"""

from __future__ import annotations

from dataclasses import dataclass


ATTACK_PATTERNS = {
    "bypass_request": ["绕过waf", "绕过 edr", "绕过检测", "bypass waf", "bypass edr"],
    "malware_request": ["木马", "勒索软件", "免杀", "malware", "ransomware", "shellcode"],
    "credential_theft": ["盗取密码", "抓取凭证", "cookie 窃取", "steal credential", "phishing kit"],
    "destructive_request": ["删库", "瘫痪", "破坏系统", "destroy system", "wiper", "ddos"],
    "attack_request": ["攻击步骤", "利用 payload", "getshell", "提权", "横向移动", "exploit chain"],
}
DEFENSIVE_HINTS = [
    "修复",
    "防御",
    "检测",
    "加固",
    "审计",
    "日志排查",
    "incident response",
    "detection",
    "mitigation",
    "hardening",
]


@dataclass(slots=True)
class SafetyGuardResult:
    """安全防护输出，结构与规格保持一致。"""

    action: str
    risk_type: str
    reason: str
    safe_response: str


class SafetyGuard:
    """Phase 7 查询安全防护服务。"""

    def evaluate(self, query: str) -> SafetyGuardResult:
        """优先用规则判断请求是否允许继续。"""
        normalized_query = query.strip().lower()
        if not normalized_query:
            return SafetyGuardResult(
                action="redirect",
                risk_type="unknown",
                reason="用户没有提供有效问题内容",
                safe_response="请提供更明确的问题，例如某项法规要求、某个安全标准条款或某种修复建议。",
            )

        for risk_type, patterns in ATTACK_PATTERNS.items():
            if any(pattern in normalized_query for pattern in patterns):
                if any(hint in normalized_query for hint in DEFENSIVE_HINTS):
                    return SafetyGuardResult(
                        action="redirect",
                        risk_type=risk_type,
                        reason="请求中包含潜在攻击关键词，但上下文更接近防御或修复导向",
                        safe_response="我不能提供攻击实施细节，但可以继续帮助你分析检测思路、修复方案、日志排查和防御建议。",
                    )
                return SafetyGuardResult(
                    action="refuse",
                    risk_type=risk_type,
                    reason="请求明显指向攻击、绕过、凭证窃取或破坏性操作",
                    safe_response="我不能帮助提供真实攻击步骤、绕过技巧或破坏性操作，但可以帮助你做防御、检测、修复和事件响应分析。",
                )

        return SafetyGuardResult(
            action="allow",
            risk_type="unknown",
            reason="未命中明显攻击或违规模式，可继续执行后续输入优化与检索准备",
            safe_response="",
        )
