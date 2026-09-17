"""元数据过滤服务。

Phase 6 负责“显式 filter 应用”。
Phase 7 在此基础上继续补齐 metadata_filter_builder：
- 用户显式 filter 优先；
- intent 推断只能补充，不能覆盖；
- 默认保留 active / current version 约束。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(slots=True)
class MetadataFilter:
    """检索层使用的结构化过滤对象。"""

    doc_type: list[str] = field(default_factory=list)
    doc_title: list[str] = field(default_factory=list)
    version_status: list[str] = field(default_factory=lambda: ["active"])
    security_domain: list[str] = field(default_factory=list)
    chapter: list[str] = field(default_factory=list)
    section: list[str] = field(default_factory=list)
    article_no: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    is_active: bool | None = True
    current_version_only: bool = True

    @classmethod
    def from_input(cls, filters: dict | None) -> "MetadataFilter":
        """从 API / 服务层输入规范化过滤对象。"""
        if not filters:
            return cls()
        return cls(
            doc_type=_ensure_list(filters.get("doc_type")),
            doc_title=_ensure_list(filters.get("doc_title")),
            version_status=_ensure_list(filters.get("version_status")) or ["active"],
            security_domain=_ensure_list(filters.get("security_domain")),
            chapter=_ensure_list(filters.get("chapter")),
            section=_ensure_list(filters.get("section")),
            article_no=_ensure_list(filters.get("article_no")),
            page_start=filters.get("page_start"),
            page_end=filters.get("page_end"),
            is_active=filters.get("is_active", True),
            current_version_only=filters.get("current_version_only", True),
        )

    def to_payload_dict(self) -> dict[str, object]:
        """输出给向量检索侧的结构化过滤字典。"""
        return {
            "doc_type": self.doc_type,
            "doc_title": self.doc_title,
            "version_status": self.version_status,
            "security_domain": self.security_domain,
            "chapter": self.chapter,
            "section": self.section,
            "article_no": self.article_no,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "is_active": self.is_active,
            "current_version_only": self.current_version_only,
        }


class MetadataFilterBuilder:
    """Phase 7 metadata filter builder。"""

    def build(self, *, explicit_filters: dict | None, suggested_doc_types: list[str] | None) -> MetadataFilter:
        """合并显式 filter 与 intent 推断结果。"""
        base_filter = MetadataFilter.from_input(explicit_filters)
        if not base_filter.doc_type and suggested_doc_types:
            base_filter.doc_type = _ensure_list(suggested_doc_types)
        if not base_filter.version_status:
            base_filter.version_status = ["active"]
        return base_filter


def _ensure_list(value: object) -> list[str]:
    """把单值 / 多值输入统一成字符串列表。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(value)]


def matches_payload_filters(payload: dict[str, object], filters: MetadataFilter) -> bool:
    """在无法把过滤完全下推时，用于服务层二次过滤。"""
    if filters.doc_type and payload.get("doc_type") not in filters.doc_type:
        return False
    if filters.doc_title and payload.get("doc_title") not in filters.doc_title:
        return False
    if filters.version_status and payload.get("version_status") not in filters.version_status:
        return False
    if filters.chapter and payload.get("chapter") not in filters.chapter:
        return False
    if filters.section and payload.get("section") not in filters.section:
        return False
    if filters.article_no and payload.get("article_no") not in filters.article_no:
        return False
    if filters.is_active is not None and payload.get("is_active") is not filters.is_active:
        return False
    if filters.current_version_only and payload.get("is_current_version") is False:
        return False

    security_domains = payload.get("security_domain") or []
    if filters.security_domain and not any(domain in security_domains for domain in filters.security_domain):
        return False

    page_start = payload.get("page_start")
    page_end = payload.get("page_end")
    if filters.page_start is not None and page_start is not None and int(page_start) < filters.page_start:
        return False
    if filters.page_end is not None and page_end is not None and int(page_end) > filters.page_end:
        return False
    return True


def is_current_version(version_id: UUID | str, current_version_id: UUID | str | None) -> bool:
    """判断 chunk 是否属于文档当前版本。"""
    if current_version_id is None:
        return False
    return str(version_id) == str(current_version_id)
