"""知识缺口账本：计划不是证据，闭合条件必须经过相同引用闸门。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent.citation_gate import Claim


@dataclass
class KnowledgeGap:
    gap_id: str
    question: str
    required_scope: str
    completion_criterion: str
    status: str = "open"
    supporting_citation_ids: list[str] = field(default_factory=list)
    attempts: list[dict] = field(default_factory=list)
    validation_error: str = ""


class GapLedger:
    """任务内保留缺口，后续规划不能靠删项或改条件伪造进展。"""

    def __init__(self) -> None:
        self._items: dict[str, KnowledgeGap] = {}

    @property
    def open_ids(self) -> list[str]:
        return [g.gap_id for g in self._items.values() if g.status != "resolved"]

    async def update(self, raw: Any, store: Any, gate: Any) -> None:
        if not isinstance(raw, list) or len(raw) > 12:
            raise ValueError("gaps 必须为最多 12 项的数组")
        seen = set()
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("gap 必须为对象")
            for key in ("gap_id", "question", "completion_criterion"):
                if not isinstance(item.get(key), str) or not item[key].strip():
                    raise ValueError(f"gap 缺少 {key}")
            gid = item["gap_id"]
            scope = item.get("required_scope")
            ids = item.get("supporting_citation_ids", [])
            status = item.get("status", "open")
            if (gid in seen or scope not in ("snippet", "abstract", "fulltext")
                    or status not in ("open", "resolved", "unresolved")
                    or not isinstance(ids, list) or not all(isinstance(cid, str) for cid in ids)):
                raise ValueError("非法缺口状态/范围/证据列表")
            seen.add(gid)
            existing = self._items.get(gid)
            if existing is not None:
                if (existing.question, existing.required_scope, existing.completion_criterion) != (
                        item["question"], scope, item["completion_criterion"]):
                    raise ValueError("不能改写已有缺口的完成条件")
                gap = existing
            else:
                if len(self._items) >= 12:
                    raise ValueError("缺口总数超过 12")
                gap = KnowledgeGap(gid, item["question"], scope, item["completion_criterion"])
                self._items[gid] = gap
            if status == "resolved" and ids:
                report = await gate.verify([Claim(gap.completion_criterion, tuple(ids), scope)], store)
                gap.status = "resolved" if report.passed else "open"
                gap.supporting_citation_ids = ids if report.passed else []
                gap.validation_error = "; ".join(c.reason for c in report.failed_claims)
            elif gap.status != "resolved":
                gap.status = "open"

    def targets(self, call: dict) -> list[str]:
        ids = call.get("gap_ids", self.open_ids)
        if not isinstance(ids, list) or not all(isinstance(gid, str) and gid in self._items for gid in ids):
            raise ValueError("工具引用未知 gap_id")
        return ids

    def record(self, ids: list[str], observation: dict) -> None:
        for gid in ids:
            self._items[gid].attempts.append(dict(observation))

    def snapshot(self, *, final: bool = False) -> list[dict]:
        result = [asdict(gap) for gap in self._items.values()]
        if final:
            for item in result:
                if item["status"] != "resolved":
                    item["status"] = "unresolved"
        return result
