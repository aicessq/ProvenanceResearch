"""Citation Gate v1（execution-plan Phase 3）。

不直接验证自然语言：LLM 先输出结构化 claims
    [{"claim": "xxx", "citations": ["K123"]}]
再验证四步：
  1. citation 存在（EvidenceStore 已登记）；
  2. citation scope 正确（引用的证据内容范围足以支撑该 claim）；
  3. 数字/专名存在（claim 中的数字与引号内专名须在证据正文或其登记身份——arxiv_id/URL/标题——
     中出现，全角/半角归一化；编号类事实由来源身份承载）；
  4. semantic support（LLM 语义复检）。
验证产出逐条 ClaimCheck；loop 层按 v1"部分有据则部分回答"取舍——存在通过的 claims
即以通过部分作答，全部失败才一次重生成后拒答（重生成不重置预算）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from inspect import signature
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
    quote: str = ""  # 可选：证据原文逐字跨度（F9，答案组装用；须为所引证据 raw_text 的归一化子串）
    rationale: str = ""  # 非空时，正文是提案，引用用于核验依据。

    @property
    def display_text(self) -> str:
        return f"建议：{self.claim}（依据：{self.rationale}）" if self.rationale else self.claim


@dataclass(frozen=True)
class ClaimCheck:
    claim: Claim
    passed: bool
    reason: str = ""
    code: str = ""
    action: str = ""


@dataclass(frozen=True)
class GateReport:
    passed: bool
    checks: tuple[ClaimCheck, ...] = field(default_factory=tuple)

    @property
    def failed_claims(self) -> list[ClaimCheck]:
        return [c for c in self.checks if not c.passed]

    def feedback(self) -> list[dict]:
        return [{"claim": c.claim.claim, "citations": list(c.claim.citations),
                 "required_scope": c.claim.scope, "code": c.code, "action": c.action,
                 "reason": c.reason} for c in self.failed_claims]


class SemanticChecker(Protocol):
    """语义复检：claim 是否被引用证据支撑，且是对提问的实质回答。"""

    async def check(self, claim: Claim, evidence: list[Evidence], question: str = "") -> bool: ...


def parse_claims(raw: str | dict[str, Any], *, allow_proposals: bool = False) -> list[Claim]:
    """解析 LLM 输出的 claims JSON；结构非法抛 ValueError。容忍 ```json 围栏包裹（LLM 常见输出习惯）。"""
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        try:
            payload = json.loads(text)
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
        rationale = item.get("rationale", "")
        if not isinstance(rationale, str) or (rationale and (not allow_proposals or not rationale.strip())):
            raise ValueError("非法建议依据")
        claims.append(Claim(claim=text.strip(), citations=tuple(citations), scope=scope,
                            quote=str(item.get("quote") or "").strip(), rationale=rationale.strip()))
    return claims


class CitationGate:
    """引用闸门：结构化 claims 的四步验证。"""

    def __init__(self, *, semantic_checker: SemanticChecker | None = None) -> None:
        self._semantic = semantic_checker
        self._accepts_question = semantic_checker is not None and len(signature(semantic_checker.check).parameters) >= 3

    async def verify(self, claims: list[Claim], store: Any, *, question: str = "") -> GateReport:
        checks: list[ClaimCheck] = []
        for claim in claims:
            checks.append(await self._verify_one(claim, store, question=question))
        return GateReport(passed=all(c.passed for c in checks), checks=tuple(checks))

    async def _verify_one(self, claim: Claim, store: Any, *, question: str = "") -> ClaimCheck:
        evidence = self._screen(claim, store)
        if isinstance(evidence, ClaimCheck):
            return evidence
        if self._semantic is not None:
            args = (claim, evidence, question) if self._accepts_question else (claim, evidence)
            if not await self._semantic.check(*args):
                return ClaimCheck(claim, False, "语义复检未通过", "unsupported_claim", "search")
        return ClaimCheck(claim, True)

    async def verify_batch(self, cases: list[tuple[Claim, str]], store: Any) -> tuple[ClaimCheck, ...]:
        """Run the same mechanical gate before asking for independent semantic verdicts."""
        check_batch = getattr(self._semantic, "check_batch", None)
        if check_batch is None:
            return tuple([await self._verify_one(claim, store, question=question) for claim, question in cases])
        screened = [self._screen(claim, store) for claim, _ in cases]
        pending = [(claim, evidence, question) for (claim, question), evidence in zip(cases, screened)
                   if not isinstance(evidence, ClaimCheck)]
        verdicts = iter(await check_batch(pending) if pending else ())
        checks = []
        for (claim, _), evidence in zip(cases, screened):
            if isinstance(evidence, ClaimCheck):
                checks.append(evidence)
            else:
                supported = next(verdicts, False) is True
                checks.append(ClaimCheck(claim, True) if supported else
                              ClaimCheck(claim, False, "语义复检未通过", "unsupported_claim", "search"))
        return tuple(checks)

    @staticmethod
    def _screen(claim: Claim, store: Any) -> ClaimCheck | list[Evidence]:
        # 1. citation 存在
        evidence: list[Evidence] = []
        for cid in claim.citations:
            ev = store.get(cid)
            if ev is None:
                return ClaimCheck(claim, False, f"引用未登记: {cid}", "unregistered_citation", "reject")
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
                "insufficient_scope", "fetch",
            )

        # 3. 数字/专名存在（全角/半角归一化后字面匹配）。
        #    合法出处 = 证据正文 ∪ 证据登记身份（arxiv_id/版本/URL/文档标题等）——
        #    编号类事实（如 arXiv 号）由来源身份承载，正文不含自身编号是常态，不得因此误拒
        identity_parts: list[str] = []
        for ev in evidence:
            p = ev.provenance
            identity_parts.extend(
                x
                for x in (
                    p.doc_id,
                    p.doc_title,
                    p.doc_version,
                    p.chunk_id,
                    p.title,
                    p.canonical_url,
                    p.arxiv_id,
                    p.arxiv_version,
                    p.fulltext_url,
                )
                if x
            )
        joined = normalize_text(" ".join((ev.raw_text or "") for ev in evidence) + " " + " ".join(identity_parts))
        factual_text = claim.rationale or claim.claim
        claim_norm = normalize_text(factual_text)
        for number in _NUMBER_RE.findall(claim_norm):
            if number not in joined:
                return ClaimCheck(claim, False, f"数字 {number} 未在证据原文中出现", "number_missing", "rewrite")
        for proper in _QUOTED_RE.findall(factual_text):
            if normalize_text(proper) not in joined:
                return ClaimCheck(claim, False, f"专名 {proper} 未在证据原文中出现", "name_missing", "rewrite")

        return evidence
