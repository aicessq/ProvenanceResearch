#!/usr/bin/env python3
"""从 pdf/<filename> 提取页级文本镜像 text/<doc_id>.pages.jsonl，并统计文本层质量。

用法（需要 PyMuPDF，仓库内 knowledge_engine/.venv 已装）：
  knowledge_engine/.venv/bin/python eval/corpus/extract_text.py            # 生成镜像 + 打印统计
  knowledge_engine/.venv/bin/python eval/corpus/extract_text.py --record   # 同时把 pages/text_layer_ok/blank_page_ratio 回写 manifest

输出行格式：{"doc_id","page","text","char_count"}，page 从 1 开始、保留真实页码。

支持两类原资产：
- PDF（pymupdf 逐页 get_text）
- RFC 规范格式 .txt：按换页符 \\f 切页（RFC 文本自带 [Page N] 分页），去掉末尾空段。

统计口径：单页 <20 字符计为近空白；blank_page_ratio > 0.3 判 text_layer_ok=false（疑似扫描件）。
"""

import argparse
import json
import sys
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
MANIFEST = CORPUS_DIR / "manifest.jsonl"
PDF_DIR = CORPUS_DIR / "pdf"
TEXT_DIR = CORPUS_DIR / "text"

NEAR_BLANK_THRESHOLD = 20   # 单页字符数低于此值视为近空白
BAD_BLANK_RATIO = 0.3       # 高于此比例判定 text_layer_ok=false


def extract_pdf(path: Path) -> list[str]:
    import pymupdf  # noqa: PLC0415 — 延迟导入，保证 --help 不依赖 pymupdf
    doc = pymupdf.open(path)
    try:
        return [page.get_text() for page in doc]
    finally:
        doc.close()


def extract_txt_pages(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    pages = raw.split("\f")
    while pages and not pages[-1].strip():
        pages.pop()
    # 统一换行为 \n，保持字节内容忠实（\r\n 与 \r 归一为 \n）
    return [p.replace("\r\n", "\n").replace("\r", "\n") for p in pages]


def process(entry: dict) -> dict:
    doc_id = entry["doc_id"]
    path = PDF_DIR / entry["filename"]
    if not path.exists():
        return {"doc_id": doc_id, "error": f"缺少原资产 {path}"}
    pages = extract_pdf(path) if path.suffix.lower() == ".pdf" else extract_txt_pages(path)

    out = TEXT_DIR / f"{doc_id}.pages.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with out.open("w", encoding="utf-8") as f:
        for i, text in enumerate(pages, start=1):
            text = text.strip("\n")  # 仅去掉页首尾换行，正文不动
            f.write(json.dumps({"doc_id": doc_id, "page": i, "text": text,
                                "char_count": len(text)}, ensure_ascii=False) + "\n")
            total += len(text)

    blank = sum(1 for t in pages if len(t.strip()) < NEAR_BLANK_THRESHOLD)
    ratio = (blank / len(pages)) if pages else 1.0
    return {
        "doc_id": doc_id,
        "pages": len(pages),
        "total_chars": total,
        "avg_chars_per_page": round(total / len(pages), 1) if pages else 0,
        "near_blank_pages": blank,
        "blank_page_ratio": round(ratio, 4),
        "text_layer_ok": bool(pages) and ratio <= BAD_BLANK_RATIO,
        "mirror": str(out.relative_to(CORPUS_DIR)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record", action="store_true", help="把 pages/text_layer_ok/blank_page_ratio 回写 manifest.jsonl")
    args = ap.parse_args()

    entries = [json.loads(l) for l in MANIFEST.read_text(encoding="utf-8").splitlines() if l.strip()]
    stats, errors = [], []
    for entry in entries:
        s = process(entry)
        (errors if "error" in s else stats).append(s)
        if "error" in s:
            print(f"[MISS] {s['doc_id']}: {s['error']}")
            continue
        flag = "" if s["text_layer_ok"] else "  <-- text_layer_ok=false（疑似扫描件，需人工裁决）"
        print(f"{s['doc_id']:28s} pages={s['pages']:4d} chars={s['total_chars']:7d} "
              f"avg={s['avg_chars_per_page']:7.1f} blank_ratio={s['blank_page_ratio']:.2%}{flag}")
        if args.record:
            entry["pages"] = s["pages"]
            entry["text_layer_ok"] = s["text_layer_ok"]
            entry["blank_page_ratio"] = s["blank_page_ratio"]

    if args.record:
        with MANIFEST.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"\n已回写 {len(stats)} 条统计到 manifest.jsonl")

    if errors:
        print(f"\n{len(errors)} 个文档缺原资产，先运行 download_corpus.py。")
        return 1
    flagged = [s for s in stats if not s["text_layer_ok"]]
    if flagged:
        print(f"\n注意：{len(flagged)} 篇 blank_page_ratio>{BAD_BLANK_RATIO:.0%}，已标记 text_layer_ok=false，需用户决定剔除或改用 OCR 路线：")
        for s in flagged:
            print(f"  {s['doc_id']} (ratio={s['blank_page_ratio']:.2%})")
    print("\n页级文本镜像提取完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
