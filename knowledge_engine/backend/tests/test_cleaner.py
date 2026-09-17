"""Phase 3 清洗服务测试。"""

from __future__ import annotations

from app.services.cleaner_service import (
    clean_page_text,
    clean_parsed_document,
    normalize_whitespace,
    remove_repeated_headers_footers,
)
from app.services.parser_service import ParsedDocument, ParsedPage


def test_normalize_whitespace_unifies_newlines() -> None:
    text = "line1\r\nline2\rline3  \n"
    assert normalize_whitespace(text) == "line1\nline2\nline3"


def test_remove_repeated_headers_footers_preserves_body() -> None:
    pages = [
        ParsedPage(page_number=1, text="页眉示例\n第一段正文\n第 1 页"),
        ParsedPage(page_number=2, text="页眉示例\n第二段正文\n第 2 页"),
    ]

    cleaned_pages = remove_repeated_headers_footers(pages)

    assert cleaned_pages[0].text == "第一段正文"
    assert cleaned_pages[1].text == "第二段正文"


def test_clean_page_text_keeps_identifiers() -> None:
    text = "第二十一条  \r\nGB/T 22239\r\nCVE-2024-12345\r\n"
    cleaned = clean_page_text(text)

    assert "第二十一条" in cleaned
    assert "GB/T 22239" in cleaned
    assert "CVE-2024-12345" in cleaned


def test_clean_parsed_document_preserves_page_numbers() -> None:
    document = ParsedDocument(
        title="测试文档",
        pages=[
            ParsedPage(page_number=1, text="页眉示例\n第一段\n第 1 页"),
            ParsedPage(page_number=2, text="页眉示例\n第二段\n第 2 页"),
        ],
        metadata={"source_type": "pdf"},
    )

    cleaned = clean_parsed_document(document)

    assert cleaned.pages[0].page_number == 1
    assert cleaned.pages[1].page_number == 2
    assert cleaned.metadata["cleaned"] == "true"
    assert cleaned.pages[0].text == "第一段"
    assert cleaned.pages[1].text == "第二段"
