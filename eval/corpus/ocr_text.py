#!/usr/bin/env python3
"""扫描件 OCR 补录页级镜像（P3b 云 OCR 路线，2026-10-12 用户批准收录）。

对 `text_layer_ok=false` 的官方公报扫描件：pymupdf 逐页渲染 PNG → 百度 OCR
（通用文字识别-标准含位置版）→ 生成/覆盖 `text/<doc_id>.pages.jsonl` 页级镜像，
每行带 `"text_source": "ocr:baidu:general"` 以示与原生文本层区分（溯源如实）。

用法（knowledge_engine/.venv：需 pymupdf + httpx）：
  python eval/corpus/ocr_text.py --doc-id zh_esign_2015 --out-dir /tmp/staging   # 试跑不落库
  python eval/corpus/ocr_text.py                                              # 全部扫描件补录
  python eval/corpus/ocr_text.py --record                                     # 补录并回写 manifest.text_source

纪律：
- 出站门先行（design.md §9）：ocr 能力未授权显式失败，绝不"先传再说"；
- 任一页 OCR 失败即中止该文档且不写部分镜像（不伪造完整性）；
- manifest 的 text_layer_ok 保持如实（PDF 原生层确实没有文本），text_source=ocr 单独记录；
- 改动镜像/manifest 会使 P4 冻结件的数据指纹失效——补录后需另立 round2 冻结件再跑分。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
REPO_ROOT = CORPUS_DIR.parents[1]
MANIFEST = CORPUS_DIR / "manifest.jsonl"
PDF_DIR = CORPUS_DIR / "pdf"

TEXT_SOURCE = "ocr:baidu:general"


def _require_outbound() -> None:
    # runner 同款轻量门检（OutboundGate 不依赖 vault/loguru，KE venv 可跑）；
    # 指纹身份与配置面 check_outbound 同源：provider/endpoint/model 取 OCR_* 配置
    sys.path.insert(0, str(REPO_ROOT / "researcher" / "deep_research_system"))
    from app.services.outbound_gate import OutboundGate

    gate = OutboundGate.from_env()
    provider = (os.environ.get("OCR_PROVIDER") or "unset").strip() or "unset"
    endpoint = (os.environ.get("OCR_BASE_URL") or "unset").strip() or "unset"
    model = (os.environ.get("OCR_MODEL") or "").strip()
    allowed, reason = gate.check("ocr", provider=provider, endpoint=endpoint, model=model)
    if not allowed:
        raise SystemExit(f"出站未授权（ocr: {reason}）；OCR 补录会外送页面图像，需先完成出站授权")


def _require_credentials() -> tuple[str, str]:
    key = (os.environ.get("OCR_API_KEY") or "").strip()
    secret = (os.environ.get("OCR_API_SECRET") or "").strip()
    if not key or not secret:
        raise SystemExit("缺 OCR_API_KEY/OCR_API_SECRET；拒绝以空凭证出站")
    return key, secret


def render_pages_png(pdf_path: Path, dpi: int) -> list[bytes]:
    import pymupdf  # noqa: PLC0415 — 延迟导入

    doc = pymupdf.open(pdf_path)
    try:
        return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]
    finally:
        doc.close()


async def ocr_doc(doc_id: str, pdf_path: Path, out_dir: Path, *, dpi: int, api_key: str, secret_key: str) -> dict:
    sys.path.insert(0, str(REPO_ROOT))
    from providers.ocr.baidu import BaiduOCRProvider

    pngs = render_pages_png(pdf_path, dpi)
    provider = BaiduOCRProvider(api_key=api_key, secret_key=secret_key)
    rows = []
    for page_number, png in enumerate(pngs, start=1):
        result = await provider.recognize(png, page_number=page_number)
        text = result.text.strip("\n")
        rows.append(
            {
                "doc_id": doc_id,
                "page": page_number,
                "text": text,
                "char_count": len(text),
                "text_source": TEXT_SOURCE,
            }
        )
        print(f"  {doc_id} p{page_number}/{len(pngs)}: {len(text)} 字符")

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{doc_id}.pages.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    total = sum(r["char_count"] for r in rows)
    blanks = sum(1 for r in rows if r["char_count"] < 20)
    return {
        "doc_id": doc_id,
        "pages": len(rows),
        "total_chars": total,
        "near_blank_pages": blanks,
        "mirror": str(out),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc-id", action="append", help="只补录指定 doc_id（可重复）；默认全部 text_layer_ok=false 条目")
    ap.add_argument("--out-dir", default=str(CORPUS_DIR / "text"), help="镜像输出目录（默认 text/；试跑可指向临时目录）")
    ap.add_argument("--dpi", type=int, default=200, help="页渲染分辨率（默认 200）")
    ap.add_argument("--record", action="store_true", help="补录后把 text_source=ocr 回写 manifest.jsonl")
    args = ap.parse_args()

    _require_outbound()
    api_key, secret_key = _require_credentials()

    entries = [json.loads(l) for l in MANIFEST.read_text(encoding="utf-8").splitlines() if l.strip()]
    targets = [e for e in entries if args.doc_id and e["doc_id"] in args.doc_id] if args.doc_id else [
        e for e in entries if not e.get("text_layer_ok")
    ]
    if not targets:
        print("没有需要补录的条目。")
        return 0

    out_dir = Path(args.out_dir)
    done = []
    for entry in targets:
        doc_id = entry["doc_id"]
        pdf_path = PDF_DIR / entry["filename"]
        if not pdf_path.exists():
            print(f"[MISS] {doc_id}: 缺少原资产 {pdf_path}")
            return 1
        print(f"{doc_id}（{entry['title']}）…")
        try:
            stats = asyncio.run(ocr_doc(doc_id, pdf_path, out_dir, dpi=args.dpi, api_key=api_key, secret_key=secret_key))
        except Exception as exc:  # 任一页失败 → 中止该文档，不写部分镜像
            print(f"[FAIL] {doc_id}: {type(exc).__name__}: {exc}")
            return 1
        done.append(stats)
        print(f"  → {stats['pages']} 页 / {stats['total_chars']} 字符 / 近空白 {stats['near_blank_pages']} 页")

    if args.record:
        done_ids = {s["doc_id"] for s in done}
        with MANIFEST.open("w", encoding="utf-8") as f:
            for entry in entries:
                if entry["doc_id"] in done_ids:
                    entry["text_source"] = "ocr"
                    notes = entry.get("notes") or ""
                    mark = f"OCR 补录：{TEXT_SOURCE}（2026-10-12）"
                    entry["notes"] = f"{notes}；{mark}" if notes else mark
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"已回写 text_source=ocr 到 manifest（{len(done)} 条）。")
        print("注意：manifest 变更会使 round1 冻结件数据指纹失效，跑分前需另立 round2 冻结件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
