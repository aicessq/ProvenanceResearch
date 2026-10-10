"""PDF/图像入库流水线（P3b / design.md §7）。

逐页策略：**文本层 → 云 OCR → 云 vision** 逐级回退——
- 文本层非空：native_text 证据，**不再 OCR**（文本层与 OCR 不重复）。
- 无文本层：OCR 转录（页全文 + block 级 bbox 子证据）；OCR 失败且配置了 vision
  则 vision 兜底（图内文字/可观察/推断分开标注，推断不回填 raw_text）。
- 低置信度如实记入 extraction.confidence 并标 low_quality（不得被忽略）。
- **发布门**：任一必需页最终 failed → 不发布"完整"版本，失败页与原因显式报告；
  不默认把不完整文档当已完整入库。

页码/rotation/bbox/asset hash 从 PageAsset 全程带进 Evidence locator 与 provenance，
citation_id 由完整身份生成（evidence.store），可回指原 PDF 页/区域/资产。
（Celery 心跳/租约 fencing 与真实 KE 上传链路不在本模块——见 decisions 2026-10-11。）
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from evidence.registry import content_hash
from evidence.schema import Evidence, Extraction, Locator, Provenance, Score
from evidence.store import EvidenceStore, register_with_computed_id

LOW_QUALITY_CONFIDENCE = 0.5


@dataclass(frozen=True)
class PageAsset:
    """parser 输出的一页（文本层 + 渲染图像 + 旋转校正信息 + 页内图像资产）。"""

    page_number: int  # 1 起始
    text_layer: str = ""
    image: bytes | None = None
    rotation_degrees: float = 0.0
    asset_id: str = ""  # 页内图像资产（图注关联）
    asset_hash: str = ""
    asset_bbox: tuple[float, float, float, float] | None = None
    caption: str = ""  # 图注文本：与 asset 绑定在同一 Evidence，不切断联系


@dataclass
class PageOutcome:
    page_number: int
    method: str  # native_text / ocr / vision / failed
    evidence: list[Evidence] = field(default_factory=list)
    low_quality: bool = False
    failures: list[dict] = field(default_factory=list)


@dataclass
class DocumentOutcome:
    doc_id: str
    doc_version: str
    pages: list[PageOutcome] = field(default_factory=list)
    publishable: bool = True
    failure_report: list[dict] = field(default_factory=list)


def _asset_hash(asset: PageAsset) -> str:
    return asset.asset_hash or (hashlib.sha256(asset.image or b"").hexdigest() if asset.image else content_hash(asset.caption))


def _page_evidence(
    *,
    raw_text: str,
    method: str,
    provider: str,
    model: str,
    confidence: float | None,
    raw_response_ref: str | None,
    index_identity: str,
    doc_id: str,
    doc_title: str,
    doc_version: str,
    chunk_id: str,
    page_number: int,
    rotation_degrees: float,
    bbox: tuple[float, float, float, float] | None = None,
    modality: str = "text",
    content_scope: str = "fulltext",
    source_type: str = "kb_chunk",
    score: float | None = None,
) -> Evidence:
    text_for_hash = raw_text if raw_text else (chunk_id + content_scope)
    return Evidence(
        citation_id="",  # register_with_computed_id 重算
        source_id=f"kb:{doc_id}:{doc_version}",
        source_type=source_type,
        modality=modality,
        content_scope=content_scope,
        raw_text=raw_text or None,
        provenance=Provenance(
            provider=provider,
            title=doc_title,
            content_hash=content_hash(text_for_hash),
            doc_id=doc_id,
            doc_title=doc_title,
            doc_version=doc_version,
            chunk_id=chunk_id,
            index_identity=index_identity,
        ),
        locator=Locator(
            page=page_number,
            chunk=chunk_id,
            bbox=bbox,
            rotation=rotation_degrees or None,
        ),
        extraction=Extraction(
            method=method,
            provider=provider,
            model=model,
            confidence=confidence,
            raw_response_ref=raw_response_ref,
        ),
        score=Score(raw=score, raw_channel=f"ingest_{method}") if score is not None else None,
    )


def _asset_evidence(
    *,
    asset: PageAsset,
    method: str,
    provider: str,
    model: str,
    raw_response_ref: str | None,
    index_identity: str,
    doc_id: str,
    doc_title: str,
    doc_version: str,
    raw_text: str | None,
    derived: tuple[str, ...] = (),
    modality: str = "image",
) -> Evidence:
    return Evidence(
        citation_id="",
        source_id=f"asset:{doc_id}:{asset.asset_id or _asset_hash(asset)[:12]}",
        source_type="asset",
        modality=modality,
        content_scope="region",
        raw_text=raw_text,
        provenance=Provenance(
            provider=provider,
            title=asset.caption or doc_title,
            content_hash=_asset_hash(asset),
            doc_id=doc_id,
            doc_title=doc_title,
            doc_version=doc_version,
            chunk_id=asset.asset_id or f"{doc_id}:p{asset.page_number}:img",
            index_identity=index_identity,
        ),
        locator=Locator(
            page=asset.page_number,
            chunk=asset.asset_id or None,
            bbox=asset.asset_bbox,
            rotation=asset.rotation_degrees or None,
            asset_id=asset.asset_id or None,
            asset_hash=_asset_hash(asset),
        ),
        extraction=Extraction(method=method, provider=provider, model=model, raw_response_ref=raw_response_ref),
        derived_observations=derived,
    )


async def ingest_pages(
    pages: list[PageAsset],
    *,
    doc_id: str,
    doc_title: str,
    doc_version: str,
    index_identity: str,
    store: EvidenceStore,
    ocr: Any = None,
    vision: Any = None,
    require_pages: set[int] | None = None,
) -> DocumentOutcome:
    """逐页入库：native → OCR → vision 回退；返回可发布性与失败页报告。"""
    outcome = DocumentOutcome(doc_id=doc_id, doc_version=doc_version)
    required = require_pages if require_pages is not None else {p.page_number for p in pages}

    for page in sorted(pages, key=lambda p: p.page_number):
        result = PageOutcome(page_number=page.page_number, method="failed")

        # ---- 1) 文本层优先（不再 OCR，避免重复）----
        if page.text_layer.strip():
            ev = _page_evidence(
                raw_text=page.text_layer,
                method="native_text",
                provider="local_parser",
                model="text_layer",
                confidence=None,
                raw_response_ref=None,
                index_identity=index_identity,
                doc_id=doc_id,
                doc_title=doc_title,
                doc_version=doc_version,
                chunk_id=f"{doc_id}:p{page.page_number}",
                page_number=page.page_number,
                rotation_degrees=page.rotation_degrees,
            )
            result.evidence.append(register_with_computed_id(store, ev))
            result.method = "native_text"

        # ---- 2) OCR 兜底 ----
        elif ocr is not None and page.image:
            try:
                ocr_page = await ocr.recognize(page.image, page_number=page.page_number, rotation_degrees=page.rotation_degrees)
                page_text = ocr_page.text
                if page_text.strip():
                    min_conf = ocr_page.min_confidence
                    result.low_quality = min_conf is not None and min_conf < LOW_QUALITY_CONFIDENCE
                    parent = _page_evidence(
                        raw_text=page_text,
                        method="ocr",
                        provider=ocr_page.provider,
                        model=ocr_page.model,
                        confidence=min_conf,
                        raw_response_ref=ocr_page.raw_response_ref,
                        index_identity=index_identity,
                        doc_id=doc_id,
                        doc_title=doc_title,
                        doc_version=doc_version,
                        chunk_id=f"{doc_id}:p{page.page_number}",
                        page_number=page.page_number,
                        rotation_degrees=page.rotation_degrees,
                    )
                    result.evidence.append(register_with_computed_id(store, parent))
                    for block in sorted(ocr_page.blocks, key=lambda b: b.reading_order):
                        child = _page_evidence(
                            raw_text=block.text,
                            method="ocr",
                            provider=ocr_page.provider,
                            model=ocr_page.model,
                            confidence=block.confidence,
                            raw_response_ref=ocr_page.raw_response_ref,
                            index_identity=index_identity,
                            doc_id=doc_id,
                            doc_title=doc_title,
                            doc_version=doc_version,
                            chunk_id=f"{doc_id}:p{page.page_number}:b{block.reading_order}",
                            page_number=page.page_number,
                            rotation_degrees=page.rotation_degrees,
                            bbox=block.bbox,
                            content_scope="region",
                        )
                        result.evidence.append(register_with_computed_id(store, child))
                    result.method = "ocr"
                else:
                    result.failures.append({"stage": "ocr", "error": "empty_transcription"})
            except Exception as exc:  # noqa: BLE001 —— 单页失败不拖垮整文档
                result.failures.append({"stage": "ocr", "error": f"{type(exc).__name__}: {exc}"[:160]})

        # ---- 3) vision 兜底（OCR 失败或纯图像页）----
        if result.method == "failed" and vision is not None and page.image:
            try:
                asset_id = page.asset_id or f"{doc_id}:p{page.page_number}"
                vis = await vision.analyze(
                    page.image,
                    asset_id=asset_id,
                    question="转录图内文字，并分别列出可观察事实与推断",
                    page_number=page.page_number,
                    bbox=page.asset_bbox,
                )
                derived = tuple(
                    f"[{'inference' if o.kind == 'inference' else 'observation'}] {o.text}"
                    for o in vis.observations
                    if o.kind != "text_in_image"
                )
                ev = _asset_evidence(
                    asset=page,
                    method="vision",
                    provider=vis.provider,
                    model=vis.model,
                    raw_response_ref=vis.raw_response_ref,
                    index_identity=index_identity,
                    doc_id=doc_id,
                    doc_title=doc_title,
                    doc_version=doc_version,
                    raw_text=vis.transcribed_text or page.caption or None,
                    derived=derived,
                    modality="image",
                )
                result.evidence.append(register_with_computed_id(store, ev))
                result.method = "vision"
            except Exception as exc:  # noqa: BLE001
                result.failures.append({"stage": "vision", "error": f"{type(exc).__name__}: {exc}"[:160]})

        # ---- 页内图像资产（原生页也保留图注-资产关联）----
        if page.asset_id and result.method in ("native_text", "ocr"):
            asset_ev = _asset_evidence(
                asset=page,
                method="native_text" if result.method == "native_text" else "ocr",
                provider="local_parser" if result.method == "native_text" else "local_parser",
                model="asset_link",
                raw_response_ref=None,
                index_identity=index_identity,
                doc_id=doc_id,
                doc_title=doc_title,
                doc_version=doc_version,
                raw_text=page.caption or None,
            )
            result.evidence.append(register_with_computed_id(store, asset_ev))

        if result.method == "failed":
            result.failures.append({"stage": "page", "error": "all_stages_failed"})
            # 失败页一律报告；只有必需页失败才禁止发布"完整"版本
            outcome.failure_report.append({"page_number": page.page_number, "tried": result.failures})
            if page.page_number in required:
                outcome.publishable = False
        elif result.low_quality:
            outcome.failure_report.append(
                {"page_number": page.page_number, "tried": result.failures, "low_quality": True}
            )
        outcome.pages.append(result)

    return outcome
