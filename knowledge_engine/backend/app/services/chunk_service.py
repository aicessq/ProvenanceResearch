"""结构化切分服务（parent-child chunk）。

Phase 4 负责把解析 + 清洗后的文档文本转换为可持久化的 chunk 结构，
供后续 Phase 5 的 embedding / index 流程继续使用。

本阶段只做：
- law / standard / policy 类文档的结构化切分
- textbook / manual / note 类文档的结构化切分
- fallback recursive chunking
- parent-child 关系生成
- chunk_hash 与基础 metadata 组织

本阶段明确不做：
- embedding
- Qdrant / FTS 写入
- query / rerank / answer 逻辑
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from app.services.parser_service import ParsedDocument, ParsedPage
from app.utils.hash_utils import calculate_chunk_hash, normalize_chunk_text

LAW_LIKE_TYPES = {"law", "regulation", "standard", "policy"}
TEXTBOOK_LIKE_TYPES = {"textbook", "manual", "note"}

MAX_PARENT_CHARS = 2400
TARGET_CHILD_CHARS = 900
LONG_ARTICLE_THRESHOLD = 1600
CHILD_OVERLAP_CHARS = 120

CHAPTER_PATTERN = re.compile(r"^(第[一二三四五六七八九十百千]+章.*|\d+(?:\.\d+)?\s+.+)$")
SECTION_PATTERN = re.compile(r"^(第[一二三四五六七八九十百千]+节.*|\d+\.\d+\s+.+)$")
ARTICLE_PATTERN = re.compile(r"^(第[一二三四五六七八九十百千]+条)")
HEADING_PATTERN = re.compile(r"^(#{1,6}\s+.+|\d+(?:\.\d+){0,2}\s+.+)$")


@dataclass(slots=True)
class ChunkDraft:
    """切分阶段的统一中间结果。"""

    local_id: str
    text: str
    normalized_text: str
    chunk_type: str
    chunk_index: int
    page_start: int | None = None
    page_end: int | None = None
    chapter: str | None = None
    section: str | None = None
    article_no: str | None = None
    parent_local_id: str | None = None
    keywords: list[str] = field(default_factory=list)
    metadata: dict[str, str | int | None] = field(default_factory=dict)
    chunk_hash: str = ""


def generate_chunks(
    *,
    document: ParsedDocument,
    doc_type: str,
    document_id: str,
    version_id: str,
    file_hash: str,
    doc_title: str,
) -> list[ChunkDraft]:
    """按文档类型生成统一 chunk 列表。"""
    normalized_doc_type = doc_type.strip().lower()
    if normalized_doc_type in LAW_LIKE_TYPES:
        drafts = _chunk_law_like_document(document)
    elif normalized_doc_type in TEXTBOOK_LIKE_TYPES:
        drafts = _chunk_textbook_like_document(document)
    else:
        drafts = _chunk_with_recursive_fallback(document)

    enriched: list[ChunkDraft] = []
    for index, draft in enumerate(drafts):
        normalized_text = normalize_chunk_text(draft.text)
        metadata = {
            "doc_id": document_id,
            "version_id": version_id,
            "chunk_id": None,
            "doc_type": normalized_doc_type,
            "doc_title": doc_title,
            "chapter": draft.chapter,
            "section": draft.section,
            "article_no": draft.article_no,
            "page_start": draft.page_start,
            "page_end": draft.page_end,
            "file_hash": file_hash,
            "chunk_hash": calculate_chunk_hash(normalized_text),
            "chunk_type": draft.chunk_type,
            "parent_chunk_id": None,
        }
        enriched.append(
            ChunkDraft(
                local_id=draft.local_id,
                text=draft.text,
                normalized_text=normalized_text,
                chunk_type=draft.chunk_type,
                chunk_index=index,
                page_start=draft.page_start,
                page_end=draft.page_end,
                chapter=draft.chapter,
                section=draft.section,
                article_no=draft.article_no,
                parent_local_id=draft.parent_local_id,
                keywords=list(draft.keywords),
                metadata=metadata,
                chunk_hash=metadata["chunk_hash"] or "",
            )
        )
    return enriched


def _chunk_law_like_document(document: ParsedDocument) -> list[ChunkDraft]:
    """按章/节/条优先切分法规与标准文本。"""
    article_units: list[dict[str, object]] = []
    chapter: str | None = None
    section: str | None = None
    current_article: str | None = None
    current_lines: list[str] = []
    current_pages: list[int] = []

    for page in document.pages:
        for raw_line in page.text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if CHAPTER_PATTERN.match(line):
                chapter = line
                continue
            if SECTION_PATTERN.match(line):
                section = line
                continue
            article_match = ARTICLE_PATTERN.match(line)
            if article_match:
                if current_article is not None and current_lines:
                    article_units.append(
                        {
                            "article_no": current_article,
                            "text": "\n".join(current_lines),
                            "chapter": chapter,
                            "section": section,
                            "page_start": min(current_pages) if current_pages else page.page_number,
                            "page_end": max(current_pages) if current_pages else page.page_number,
                        }
                    )
                current_article = article_match.group(1)
                current_lines = [line]
                current_pages = [page.page_number]
                continue
            if current_article is not None:
                current_lines.append(line)
                current_pages.append(page.page_number)

    if current_article is not None and current_lines:
        article_units.append(
            {
                "article_no": current_article,
                "text": "\n".join(current_lines),
                "chapter": chapter,
                "section": section,
                "page_start": min(current_pages) if current_pages else 1,
                "page_end": max(current_pages) if current_pages else 1,
            }
        )

    if not article_units:
        return _chunk_with_recursive_fallback(document)

    drafts: list[ChunkDraft] = []
    for article_index, unit in enumerate(article_units):
        parent_local_id = f"parent-law-{article_index}"
        parent_text = str(unit["text"])
        drafts.append(
            ChunkDraft(
                local_id=parent_local_id,
                text=parent_text,
                normalized_text=normalize_chunk_text(parent_text),
                chunk_type="parent",
                chunk_index=0,
                page_start=unit["page_start"],
                page_end=unit["page_end"],
                chapter=unit["chapter"],
                section=unit["section"],
                article_no=unit["article_no"],
            )
        )
        for child_order, child_text in enumerate(_split_long_text_preserving_structure(parent_text)):
            if child_text.strip() and str(unit["article_no"]) not in child_text:
                child_text = f"{unit['article_no']} {child_text}"
            drafts.append(
                ChunkDraft(
                    local_id=f"child-law-{article_index}-{child_order}",
                    text=child_text,
                    normalized_text=normalize_chunk_text(child_text),
                    chunk_type="child",
                    chunk_index=0,
                    page_start=unit["page_start"],
                    page_end=unit["page_end"],
                    chapter=unit["chapter"],
                    section=unit["section"],
                    article_no=unit["article_no"],
                    parent_local_id=parent_local_id,
                )
            )
    return drafts


def _chunk_textbook_like_document(document: ParsedDocument) -> list[ChunkDraft]:
    """按标题与段落切分教材/手册/笔记文本。"""
    sections = _extract_heading_sections(document)
    if not sections:
        return _chunk_with_recursive_fallback(document)

    drafts: list[ChunkDraft] = []
    for section_index, section in enumerate(sections):
        parent_local_id = f"parent-textbook-{section_index}"
        chapter = section["chapter"]
        section_name = section["section"]
        text = section["text"]
        drafts.append(
            ChunkDraft(
                local_id=parent_local_id,
                text=text,
                normalized_text=normalize_chunk_text(text),
                chunk_type="parent",
                chunk_index=0,
                page_start=section["page_start"],
                page_end=section["page_end"],
                chapter=chapter,
                section=section_name,
            )
        )
        for child_order, child_text in enumerate(_split_textbook_children(text)):
            drafts.append(
                ChunkDraft(
                    local_id=f"child-textbook-{section_index}-{child_order}",
                    text=child_text,
                    normalized_text=normalize_chunk_text(child_text),
                    chunk_type="child",
                    chunk_index=0,
                    page_start=section["page_start"],
                    page_end=section["page_end"],
                    chapter=chapter,
                    section=section_name,
                    parent_local_id=parent_local_id,
                )
            )
    return drafts


def _chunk_with_recursive_fallback(document: ParsedDocument) -> list[ChunkDraft]:
    """在缺乏结构时，使用保守递归切分兜底。"""
    all_text_parts = [page.text.strip() for page in document.pages if page.text.strip()]
    if not all_text_parts:
        return []

    page_start = document.pages[0].page_number if document.pages else None
    page_end = document.pages[-1].page_number if document.pages else None
    parent_text = "\n\n".join(all_text_parts)
    parent_local_id = "parent-fallback-0"

    drafts = [
        ChunkDraft(
            local_id=parent_local_id,
            text=parent_text,
            normalized_text=normalize_chunk_text(parent_text),
            chunk_type="parent",
            chunk_index=0,
            page_start=page_start,
            page_end=page_end,
        )
    ]

    for child_order, child_text in enumerate(_split_recursive(parent_text, target_size=TARGET_CHILD_CHARS, overlap=CHILD_OVERLAP_CHARS)):
        drafts.append(
            ChunkDraft(
                local_id=f"child-fallback-0-{child_order}",
                text=child_text,
                normalized_text=normalize_chunk_text(child_text),
                chunk_type="child",
                chunk_index=0,
                page_start=page_start,
                page_end=page_end,
                parent_local_id=parent_local_id,
            )
        )
    return drafts


def _extract_heading_sections(document: ParsedDocument) -> list[dict[str, object]]:
    """提取教材类内容中的标题分段。"""
    sections: list[dict[str, object]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    current_pages: list[int] = []
    current_chapter: str | None = None

    for page in document.pages:
        for raw_line in page.text.splitlines():
            line = raw_line.strip()
            if not line:
                if current_lines:
                    current_lines.append("")
                continue
            if HEADING_PATTERN.match(line):
                if current_heading is not None and current_lines:
                    sections.append(
                        {
                            "chapter": current_chapter,
                            "section": current_heading,
                            "text": "\n".join(current_lines).strip(),
                            "page_start": min(current_pages) if current_pages else page.page_number,
                            "page_end": max(current_pages) if current_pages else page.page_number,
                        }
                    )
                current_heading = line
                current_lines = [line]
                current_pages = [page.page_number]
                if re.match(r"^(#|\d+\s)", line):
                    current_chapter = line
                continue
            if current_heading is None:
                current_heading = "未命名章节"
            current_lines.append(line)
            current_pages.append(page.page_number)

    if current_heading is not None and current_lines:
        sections.append(
            {
                "chapter": current_chapter,
                "section": current_heading,
                "text": "\n".join(current_lines).strip(),
                "page_start": min(current_pages) if current_pages else 1,
                "page_end": max(current_pages) if current_pages else 1,
            }
        )
    return sections


def _split_textbook_children(text: str) -> list[str]:
    """切教材类 child chunk，尽量保留代码块与段落边界。"""
    if "```" in text:
        blocks = _split_preserving_code_blocks(text)
        chunks: list[str] = []
        buffer = ""
        for block in blocks:
            candidate = block if not buffer else f"{buffer}\n\n{block}"
            if len(candidate) <= TARGET_CHILD_CHARS or not buffer:
                buffer = candidate
                continue
            chunks.append(buffer.strip())
            buffer = block
        if buffer.strip():
            chunks.append(buffer.strip())
        return chunks
    return _split_recursive(text, target_size=TARGET_CHILD_CHARS, overlap=CHILD_OVERLAP_CHARS)


def _split_long_text_preserving_structure(text: str) -> list[str]:
    """长条款切 child chunk，短条款保持原样。"""
    if len(text) <= LONG_ARTICLE_THRESHOLD:
        return [text.strip()]
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if len(paragraphs) > 1:
        parts: list[str] = []
        buffer = ""
        for paragraph in paragraphs:
            candidate = paragraph if not buffer else f"{buffer}\n\n{paragraph}"
            if len(candidate) <= TARGET_CHILD_CHARS or not buffer:
                buffer = candidate
                continue
            parts.append(buffer.strip())
            buffer = paragraph
        if buffer.strip():
            parts.append(buffer.strip())
        return parts
    return _split_recursive(text, target_size=TARGET_CHILD_CHARS, overlap=CHILD_OVERLAP_CHARS)


def _split_recursive(text: str, *, target_size: int, overlap: int) -> list[str]:
    """按优先分隔符递归切分文本。"""
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) <= target_size:
        return [stripped]

    separators = ["\n\n", "\n", "。", "；", " "]
    chunks = _split_by_separators(stripped, target_size, separators)
    if len(chunks) == 1 and len(chunks[0]) > target_size:
        chunks = [chunks[0][index : index + target_size] for index in range(0, len(chunks[0]), target_size - overlap)]
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _split_by_separators(text: str, target_size: int, separators: list[str]) -> list[str]:
    """使用优先级分隔符拼装近似目标长度的文本块。"""
    if not separators:
        return [text]

    separator = separators[0]
    parts = text.split(separator)
    if len(parts) == 1:
        return _split_by_separators(text, target_size, separators[1:])

    chunks: list[str] = []
    buffer = ""
    joiner = separator
    for part in parts:
        candidate = part if not buffer else f"{buffer}{joiner}{part}"
        if len(candidate) <= target_size or not buffer:
            buffer = candidate
            continue
        chunks.extend(_split_by_separators(buffer, target_size, separators[1:]))
        buffer = part
    if buffer:
        if len(buffer) > target_size and len(separators) > 1:
            chunks.extend(_split_by_separators(buffer, target_size, separators[1:]))
        else:
            chunks.append(buffer)
    return chunks


def _split_preserving_code_blocks(text: str) -> list[str]:
    """按代码块边界拆分教材类文本。"""
    pieces: list[str] = []
    buffer: list[str] = []
    in_code_block = False

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            buffer.append(line)
            continue
        if not in_code_block and not line.strip() and buffer:
            pieces.append("\n".join(buffer).strip())
            buffer = []
            continue
        buffer.append(line)

    if buffer:
        pieces.append("\n".join(buffer).strip())
    return [piece for piece in pieces if piece]


def build_chunk_records(
    *,
    drafts: list[ChunkDraft],
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    doc_type: str,
    doc_title: str,
    security_domain: list[str],
) -> list[dict[str, object]]:
    """把中间 chunk 结果映射为 ORM 可用记录字典。"""
    id_map = {draft.local_id: uuid.uuid4() for draft in drafts}
    records: list[dict[str, object]] = []

    for draft in drafts:
        chunk_id = id_map[draft.local_id]
        parent_chunk_id = id_map[draft.parent_local_id] if draft.parent_local_id else None
        metadata = dict(draft.metadata)
        metadata["chunk_id"] = str(chunk_id)
        metadata["parent_chunk_id"] = str(parent_chunk_id) if parent_chunk_id else None
        record = {
            "id": chunk_id,
            "document_id": document_id,
            "version_id": version_id,
            "parent_chunk_id": parent_chunk_id,
            "chunk_index": draft.chunk_index,
            "chunk_type": draft.chunk_type,
            "text": draft.text,
            "normalized_text": draft.normalized_text,
            "chunk_hash": draft.chunk_hash,
            "doc_type": doc_type,
            "doc_title": doc_title,
            "chapter": draft.chapter,
            "section": draft.section,
            "article_no": draft.article_no,
            "page_start": draft.page_start,
            "page_end": draft.page_end,
            "security_domain": list(security_domain),
            "keywords": list(draft.keywords),
            "metadata": metadata,
            "is_active": True,
        }
        records.append(record)
    return records
