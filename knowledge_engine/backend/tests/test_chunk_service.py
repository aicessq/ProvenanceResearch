"""Phase 4 结构化切分服务测试。"""

from __future__ import annotations

import uuid
from pathlib import Path

from app.services.chunk_service import build_chunk_records, generate_chunks
from app.services.parser_service import ParsedDocument, ParsedPage, parse_markdown, parse_txt
from app.utils.hash_utils import calculate_chunk_hash, normalize_chunk_text

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_law_document_chunks_preserve_article_numbers() -> None:
    parsed = parse_txt(FIXTURES_DIR / "law_sample.txt", title="网络安全法样例")
    drafts = generate_chunks(
        document=parsed,
        doc_type="law",
        document_id="doc-1",
        version_id="ver-1",
        file_hash="filehash",
        doc_title="网络安全法样例",
    )

    parent_chunks = [draft for draft in drafts if draft.chunk_type == "parent"]
    child_chunks = [draft for draft in drafts if draft.chunk_type == "child"]

    assert parent_chunks
    assert child_chunks
    assert all(chunk.article_no for chunk in child_chunks)
    assert any("第一条" in chunk.text for chunk in child_chunks)
    assert any("第二条" in chunk.text for chunk in child_chunks)


def test_long_article_splits_into_multiple_child_chunks() -> None:
    long_article_text = "第一条 " + "网络安全要求。" * 400
    document = ParsedDocument(
        title="长条款样例",
        pages=[ParsedPage(page_number=1, text=long_article_text)],
        metadata={"source_type": "txt"},
    )

    drafts = generate_chunks(
        document=document,
        doc_type="law",
        document_id="doc-2",
        version_id="ver-2",
        file_hash="filehash",
        doc_title="长条款样例",
    )
    child_chunks = [draft for draft in drafts if draft.chunk_type == "child"]

    assert len(child_chunks) >= 2
    assert all(chunk.article_no == "第一条" for chunk in child_chunks)


def test_textbook_document_creates_parent_child_chunks() -> None:
    parsed = parse_markdown(FIXTURES_DIR / "textbook_sample.md", title="教材样例")
    drafts = generate_chunks(
        document=parsed,
        doc_type="textbook",
        document_id="doc-3",
        version_id="ver-3",
        file_hash="filehash",
        doc_title="教材样例",
    )

    parent_chunks = [draft for draft in drafts if draft.chunk_type == "parent"]
    child_chunks = [draft for draft in drafts if draft.chunk_type == "child"]

    assert parent_chunks
    assert child_chunks
    assert any(chunk.parent_local_id for chunk in child_chunks)
    assert any(chunk.section for chunk in parent_chunks)


def test_fallback_chunker_handles_plain_text() -> None:
    parsed = parse_txt(FIXTURES_DIR / "plain_note.txt", title="普通说明")
    drafts = generate_chunks(
        document=parsed,
        doc_type="other",
        document_id="doc-4",
        version_id="ver-4",
        file_hash="filehash",
        doc_title="普通说明",
    )

    assert drafts
    assert drafts[0].chunk_type == "parent"
    assert any(draft.chunk_type == "child" for draft in drafts)


def test_chunk_hash_is_stable_for_whitespace_variants() -> None:
    text_a = "第一条  网络安全要求\n\n第二行"
    text_b = "第一条 网络安全要求\r\n第二行"

    assert calculate_chunk_hash(normalize_chunk_text(text_a)) == calculate_chunk_hash(normalize_chunk_text(text_b))


def test_build_chunk_records_populates_parent_chunk_id_and_metadata() -> None:
    parsed = parse_txt(FIXTURES_DIR / "law_sample.txt", title="网络安全法样例")
    drafts = generate_chunks(
        document=parsed,
        doc_type="law",
        document_id="doc-5",
        version_id="ver-5",
        file_hash="filehash",
        doc_title="网络安全法样例",
    )
    records = build_chunk_records(
        drafts=drafts,
        document_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        doc_type="law",
        doc_title="网络安全法样例",
        security_domain=["compliance"],
    )

    assert records
    assert all(record["chunk_hash"] for record in records)
    assert all("chunk_type" in record["metadata"] for record in records)
    child_records = [record for record in records if record["chunk_type"] == "child"]
    assert child_records
    assert any(record["parent_chunk_id"] is not None for record in child_records)
