"""EvidenceStore（P3c）：Evidence 登记、citation_id 冲突检测、回取。

citation_id 由完整来源身份+版本+位置+内容 hash 生成（schema.make_citation_id）；
同一 citation_id 指向不同内容即冲突，必须报错而不是覆盖——
这是"引用只能来自登记 Evidence"（design.md §5）的存储侧保障。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from evidence.schema import Evidence, make_citation_id


class CitationConflictError(ValueError):
    """同一 citation_id 指向不同内容。"""


@dataclass
class EvidenceStore:
    """任务/回答内的证据池。citation_id 在池内稳定。"""

    _by_citation: dict[str, Evidence] = field(default_factory=dict)
    _by_source: dict[str, list[str]] = field(default_factory=dict)

    def register(self, evidence: Evidence) -> Evidence:
        """登记证据；citation_id 不一致或冲突时显式失败。"""
        evidence.validate()
        expected = evidence.make_citation_id()
        if evidence.citation_id != expected:
            raise CitationConflictError(
                f"citation_id 与内容不一致: 登记 {evidence.citation_id!r}，计算得 {expected!r}"
            )
        existing = self._by_citation.get(evidence.citation_id)
        if existing is not None and existing.raw_text != evidence.raw_text:
            raise CitationConflictError(
                f"citation_id {evidence.citation_id!r} 已指向不同内容，拒绝覆盖"
            )
        self._by_citation[evidence.citation_id] = evidence
        self._by_source.setdefault(evidence.source_id, [])
        if evidence.citation_id not in self._by_source[evidence.source_id]:
            self._by_source[evidence.source_id].append(evidence.citation_id)
        return evidence

    def get(self, citation_id: str) -> Evidence | None:
        return self._by_citation.get(citation_id)

    def require(self, citation_id: str) -> Evidence:
        evidence = self.get(citation_id)
        if evidence is None:
            raise KeyError(f"citation_id 未登记: {citation_id}")
        return evidence

    def by_source(self, source_id: str) -> list[Evidence]:
        return [self._by_citation[cid] for cid in self._by_source.get(source_id, [])]

    def all(self) -> list[Evidence]:
        return list(self._by_citation.values())

    def resolve_citations(self, citation_ids: list[str]) -> tuple[list[Evidence], list[str]]:
        """解析引用列表：返回（已登记证据，未登记 id）——引用闸门的输入。"""
        resolved: list[Evidence] = []
        missing: list[str] = []
        for cid in citation_ids:
            evidence = self.get(cid)
            if evidence is None:
                missing.append(cid)
            else:
                resolved.append(evidence)
        return resolved, missing


def register_with_computed_id(store: EvidenceStore, evidence: Evidence) -> Evidence:
    """用内容生成 citation_id 后登记（工具产出证据的常用路径）。"""
    computed = make_citation_id(evidence.source_type, evidence.provenance, evidence.locator)
    fixed = Evidence(
        citation_id=computed,
        source_id=evidence.source_id,
        source_type=evidence.source_type,
        modality=evidence.modality,
        content_scope=evidence.content_scope,
        raw_text=evidence.raw_text,
        provenance=evidence.provenance,
        locator=evidence.locator,
        extraction=evidence.extraction,
        score=evidence.score,
        schema_version=evidence.schema_version,
        untrusted=evidence.untrusted,
        derived_observations=evidence.derived_observations,
    )
    return store.register(fixed)
