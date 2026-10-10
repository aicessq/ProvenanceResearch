"""Citation Gate v1（execution-plan Phase 3）。

不直接验证自然语言：LLM 先输出结构化 claims
    [{"claim": "xxx", "citations": ["K123"]}]
再验证四步：
  1. citation 存在（EvidenceStore 已登记）；
  2. citation scope 正确（引用的证据内容范围足以支撑该 claim）；
  3. 数字/专名存在（claim 中的数字与引号内专名须在证据原文中出现，全角/半角归一化）；
  4. semantic support（LLM 语义复检）。
任一失败 → 拒答；一次重生成后仍失败 → 拒答（重生成不重置预算）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from evidence.schema import Evidence

# 全角数字/字母 → 半角（decisions 2026-09-18：全角数字会造成假拒答）
_FULLWIDTH_MAP = {ord(c): ord(c) - 0xFEE0 for c in "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"}
_FULLWIDTH_MAP[ord("　")] = ord(" ")

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_QUOTED_RE = re.compile(r"[\"'「『“]([^\"'」』”]{2,})[\"'」』”]")


def normalize_text(text: str) -> str:
    """全角→半角、折叠空白，供字面匹配使用。"""
    return " ".join(text.translate(_FULLWIDTH_MAP).split())


@dataclass(frozen=True)
class Claim:
    claim: str
    citations: tuple[str, ...]
    scope: str = "fulltext"  # fulltext / abstract / snippet —— 该 claim 需要的内容范围


@dataclass(frozen=True)
class ClaimCheck:
    claim: Claim
    passed: bool
    reason: str = ""


@dataclass(frozen=True)
class GateReport:
    passed: bool
    checks: tuple[ClaimCheck, ...] = field(default_factory=tuple)

    @property
    def failed_claims(self) -> list[ClaimCheck]:
        return [c for c in self.checks if not c.passed]


class SemanticChecker(Protocol):
    """语义复检：claim 是否被引用证据支撑。"""

    async def check(self, claim: Claim, evidence: list[Evidence]) -> bool: ...


def parse_claims(raw: str | dict[str, Any]) -> list[Claim]:
    """解析 LLM 输出的 claims JSON；结构非法抛 ValueError。"""
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"claims 不是合法 JSON: {exc}") from exc
    else:
        payload = raw
    items = payload.get("claims") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("claims 必须是列表")
    claims: list[Claim] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"claim 项必须是对象: {item!r}")
        text = item.get("claim")
        citations = item.get("citations")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"claim 缺少文本: {item!r}")
        if not isinstance(citations, list) or not citations or not all(isinstance(c, str) for c in citations):
            raise ValueError(f"claim 缺少引用: {item!r}")
        scope = item.get("scope", "fulltext")
        if scope not in ("fulltext", "abstract", "snippet"):
            raise ValueError(f"非法 claim.scope: {scope}")
        claims.append(Claim(claim=text.strip(), citations=tuple(citations), scope=scope))
    return claims


class CitationGate:
    """引用闸门：结构化 claims 的四步验证。"""

    def __init__(self, *, semantic_checker: SemanticChecker | None = None) -> None:
        self._semantic = semantic_checker

    async def verify(self, claims: list[Claim], store: Any) -> GateReport:
        checks: list[ClaimCheck] = []
        for claim in claims:
            checks.append(await self._verify_one(claim, store))
        return GateReport(passed=all(c.passed for c in checks), checks=tuple(checks))

    async def _verify_one(self, claim: Claim, store: Any) -> ClaimCheck:
        # 1. citation 存在
        evidence: list[Evidence] = []
        for cid in claim.citations:
            ev = store.get(cid)
            if ev is None:
                return ClaimCheck(claim, False, f"引用未登记: {cid}")
            evidence.append(ev)

        # 2. scope 正确：claim 要求的范围不能超过证据内容范围
        #    fulltext claim 需要 fulltext 证据；abstract claim 接受 abstract/fulltext
        scope_rank = {"snippet": 0, "abstract": 1, "fulltext": 2}
        needed = scope_rank[claim.scope]
        best = max((scope_rank.get(ev.content_scope, 0) for ev in evidence), default=0)
        if best < needed:
            return ClaimCheck(
                claim,
                False,
                f"claim 需要 {claim.scope} 范围，证据最高只有 {evidence[0].content_scope}",
            )

        # 3. 数字/专名存在（全角/半角归一化后字面匹配）
        joined = normalize_text(" ".join(ev.raw_text or "" for ev in evidence))
        claim_norm = normalize_text(claim.claim)
        for number in _NUMBER_RE.findall(claim_norm):
            if number not in joined:
                return ClaimCheck(claim, False, f"数字 {number} 未在证据原文中出现")
        for proper in _QUOTED_RE.findall(claim.claim):
            if normalize_text(proper) not in joined:
                return ClaimCheck(claim, False, f"专名 {proper} 未在证据原文中出现")

        # 4. semantic support
        if self._semantic is not None:
            supported = await self._semantic.check(claim, evidence)
            if not supported:
                return ClaimCheck(claim, False, "语义复检未通过")
        return ClaimCheck(claim, True)
