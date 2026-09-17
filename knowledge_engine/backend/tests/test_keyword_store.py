"""Phase 5 keyword store 测试。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.services.keyword_store import KeywordStore

pytestmark = pytest.mark.integration


def create_document_version_records(db_session):
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    document = Document(
        id=document_id,
        title="网络安全法样例",
        doc_type="law",
        source_filename="law_sample.txt",
        storage_path="backend/tests/fixtures/law_sample.txt",
        current_version_id=None,
        status="active",
        security_domain=["compliance"],
        tags=[],
    )
    version = DocumentVersion(
        id=version_id,
        document_id=document_id,
        version_no=1,
        file_hash="hash",
        file_size=128,
        mime_type="text/plain",
        storage_path="backend/tests/fixtures/law_sample.txt",
        version_status="active",
    )
    db_session.add(document)
    db_session.add(version)
    db_session.flush()
    document.current_version_id = version_id
    db_session.commit()
    return document, version


def test_keyword_store_updates_search_tsv_only_for_child_chunks(db_session) -> None:
    document, version = create_document_version_records(db_session)
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()

    parent_chunk = Chunk(
        id=parent_id,
        document_id=document.id,
        version_id=version.id,
        parent_chunk_id=None,
        chunk_index=0,
        chunk_type="parent",
        text="第一章 总则",
        normalized_text="第一章 总则",
        chunk_hash="parent-hash",
        doc_type="law",
        doc_title="网络安全法样例",
        chapter="第一章 总则",
        section=None,
        article_no=None,
        page_start=1,
        page_end=1,
        security_domain=["compliance"],
        keywords=[],
        metadata={},
        is_active=True,
    )
    child_chunk = Chunk(
        id=child_id,
        document_id=document.id,
        version_id=version.id,
        parent_chunk_id=parent_id,
        chunk_index=1,
        chunk_type="child",
        text="第一条 为了规范网络安全工作，制定本法。",
        normalized_text="第一条 为了规范网络安全工作，制定本法。",
        chunk_hash="child-hash",
        doc_type="law",
        doc_title="网络安全法样例",
        chapter="第一章 总则",
        section="第一节 适用范围",
        article_no="第一条",
        page_start=1,
        page_end=1,
        security_domain=["compliance"],
        keywords=[],
        metadata={},
        is_active=True,
    )
    db_session.add(parent_chunk)
    db_session.add(child_chunk)
    db_session.commit()

    store = KeywordStore.from_db(db_session)
    updated_count = store.update_child_chunk_search_vectors([parent_id, child_id])
    db_session.commit()

    parent_search = db_session.execute(text("SELECT search_tsv::text FROM chunks WHERE id = :chunk_id"), {"chunk_id": parent_id}).scalar()
    child_search = db_session.execute(text("SELECT search_tsv::text FROM chunks WHERE id = :chunk_id"), {"chunk_id": child_id}).scalar()

    assert updated_count == 1
    assert parent_search is None
    assert child_search is not None
    assert "第一条" in child_search


def test_keyword_store_keeps_inactive_chunk_unmodified(db_session) -> None:
    document, version = create_document_version_records(db_session)
    chunk_id = uuid.uuid4()
    chunk = Chunk(
        id=chunk_id,
        document_id=document.id,
        version_id=version.id,
        parent_chunk_id=None,
        chunk_index=0,
        chunk_type="child",
        text="CVE-2024-0001 样例",
        normalized_text="CVE-2024-0001 样例",
        chunk_hash="inactive-hash",
        doc_type="note",
        doc_title="漏洞笔记",
        chapter=None,
        section=None,
        article_no=None,
        page_start=1,
        page_end=1,
        security_domain=["vuln"],
        keywords=[],
        metadata={},
        is_active=False,
    )
    db_session.add(chunk)
    db_session.commit()

    store = KeywordStore.from_db(db_session)
    updated_count = store.update_child_chunk_search_vectors([chunk_id])
    db_session.commit()

    child_search = db_session.execute(text("SELECT search_tsv::text FROM chunks WHERE id = :chunk_id"), {"chunk_id": chunk_id}).scalar()

    assert updated_count == 0
    assert child_search is None
