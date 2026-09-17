"""文本清洗服务。

Phase 3 只做“保守清洗”：
- 统一换行
- 去除多余空白
- 去除重复页眉页脚
- 尽量修复 PDF 抽取造成的断行

本阶段不做结构化切分、章节抽取或内容改写。
"""

from __future__ import annotations

import re
from collections import Counter

from app.services.parser_service import ParsedDocument, ParsedPage


def normalize_whitespace(text: str) -> str:
    """统一换行并清理每行尾部空白。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def repair_broken_lines(text: str) -> str:
    """保守修复 PDF 抽取中明显被断开的正文行。"""
    lines = text.split("\n")
    merged: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            merged.append("")
            continue

        if not merged:
            merged.append(stripped)
            continue

        previous = merged[-1]
        if not previous:
            merged.append(stripped)
            continue

        if _should_merge_lines(previous, stripped):
            merged[-1] = f"{previous} {stripped}"
        else:
            merged.append(stripped)

    return "\n".join(merged).strip()


def clean_page_text(text: str) -> str:
    """清洗单页文本，但尽量不破坏结构。"""
    normalized = normalize_whitespace(text)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    return repair_broken_lines(normalized)


def remove_repeated_headers_footers(pages: list[ParsedPage]) -> list[ParsedPage]:
    """删除多页中重复出现的页眉/页脚。"""
    if len(pages) <= 1:
        return pages

    header_candidates = [page.text.splitlines()[0].strip() for page in pages if page.text.splitlines()]
    footer_candidates = [page.text.splitlines()[-1].strip() for page in pages if page.text.splitlines()]

    repeated_headers = {
        value for value, count in Counter(header_candidates).items() if value and count >= 2 and _looks_like_noise(value)
    }
    repeated_footers = {
        value for value, count in Counter(footer_candidates).items() if value and count >= 2 and _looks_like_noise(value)
    }

    cleaned_pages: list[ParsedPage] = []
    for page in pages:
        lines = page.text.splitlines()
        if lines and lines[0].strip() in repeated_headers:
            lines = lines[1:]
        if lines and (lines[-1].strip() in repeated_footers or _looks_like_page_number_footer(lines[-1].strip())):
            lines = lines[:-1]
        cleaned_pages.append(
            ParsedPage(
                page_number=page.page_number,
                text="\n".join(lines),
                tables=list(page.tables),
                images=list(page.images),
            )
        )
    return cleaned_pages


def clean_parsed_document(document: ParsedDocument) -> ParsedDocument:
    """对解析结果做文档级清洗，并保留页码映射。"""
    header_footer_cleaned = remove_repeated_headers_footers(document.pages)
    cleaned_pages = [
        ParsedPage(
            page_number=page.page_number,
            text=clean_page_text(page.text),
            tables=list(page.tables),
            images=list(page.images),
        )
        for page in header_footer_cleaned
    ]

    metadata = dict(document.metadata)
    metadata["cleaned"] = "true"
    return ParsedDocument(title=document.title, pages=cleaned_pages, metadata=metadata)


def _should_merge_lines(previous: str, current: str) -> bool:
    """判断两行是否应合并为同一段正文。"""
    if previous.endswith((":", "：", ";", "；", "#", "```", "|")):
        return False
    if current.startswith(("#", "-", "*", ">", "|", "```")):
        return False
    if re.match(r"^(第[一二三四五六七八九十百千]+条|\d+(\.\d+)*[.)]?|GB/T\s*\d+|CVE-\d{4}-\d+)", current):
        return False
    if previous.endswith(("-", "/")):
        return False
    return previous[-1] not in "。！？.!?;；:" and current[:1] not in "0123456789"


def _looks_like_page_number_footer(value: str) -> bool:
    """识别不同页码值但相同模式的页脚。"""
    return bool(re.fullmatch(r"第\s*\d+\s*页", value) or re.fullmatch(r"[-—–]?\s*\d+\s*[-—–]?", value))


def _looks_like_noise(value: str) -> bool:
    """粗略判断页眉页脚候选是否像噪声而非正文。"""
    if len(value) > 80:
        return False
    if re.search(r"第\s*\d+\s*页", value):
        return True
    if re.fullmatch(r"\d+", value):
        return True
    return True
