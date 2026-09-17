"""Phase 3 解析服务测试。"""

from __future__ import annotations

from pathlib import Path

import fitz

from app.services.parser_service import ParseError, parse_document, parse_markdown, parse_pdf, parse_txt

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def create_sample_pdf(path: Path) -> None:
    """生成一个稳定的小型测试 PDF。"""
    document = fitz.open()

    page1 = document.new_page()
    page1.insert_text((72, 72), "页眉示例\n第一段正文\n第二十一条 网络运营者应当履行义务\n第 1 页")

    page2 = document.new_page()
    page2.insert_text((72, 72), "页眉示例\n第二页正文\nCVE-2024-12345\n第 2 页")

    document.save(path)
    document.close()


def test_parse_pdf_preserves_page_numbers(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    create_sample_pdf(pdf_path)

    parsed = parse_pdf(pdf_path, title="测试 PDF")

    assert parsed.title == "测试 PDF"
    assert len(parsed.pages) == 2
    assert parsed.pages[0].page_number == 1
    assert parsed.pages[1].page_number == 2
    assert "第二十一条" in parsed.pages[0].text
    assert parsed.metadata["source_type"] == "pdf"


def test_parse_markdown_as_single_page() -> None:
    parsed = parse_markdown(FIXTURES_DIR / "sample.md")

    assert parsed.pages[0].page_number == 1
    assert len(parsed.pages) == 1
    assert "# 网络安全学习笔记" in parsed.pages[0].text
    assert "CVE-2024-12345" in parsed.pages[0].text


def test_parse_txt_as_single_page() -> None:
    parsed = parse_txt(FIXTURES_DIR / "sample.txt")

    assert len(parsed.pages) == 1
    assert parsed.pages[0].page_number == 1
    assert "第二十一条" in parsed.pages[0].text
    assert "GB/T 22239" in parsed.pages[0].text


def test_parse_document_dispatches_by_suffix() -> None:
    parsed = parse_document(FIXTURES_DIR / "sample.txt")

    assert parsed.metadata["source_type"] == "txt"
    assert parsed.pages[0].page_number == 1


def test_parse_broken_pdf_raises_parse_error() -> None:
    try:
        parse_document(FIXTURES_DIR / "broken.pdf")
    except ParseError as exc:
        assert "PDF" in str(exc)
    else:
        raise AssertionError("broken.pdf 应触发 ParseError")
