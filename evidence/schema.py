"""Evidence Schema v2（P3c 文本链路，多模态字段留空占位）。

字段语义以 docs/design.md §2 为准（schema_version=2，公共接口不得静默改变语义）：

- source_type: kb_chunk / web / paper / asset
- modality:   text / image / mixed
- provenance: KB 必须 doc/version/chunk/index 身份；web 必须规范 URL+fetched_at；
              paper 必须 arxiv_id+明确版本（可用时 DOI/正文 URL）
- locator:    page/chunk/url/section（文本链路）；artifact/block/region/bbox/asset
              为 P3b 多模态占位字段，本轮允许为空但校验形状
- extraction: native_text / ocr / vision / provider_text；无可靠置信度时为 None，不伪造
- raw_text:   抽取文本；禁止用 Agent 摘要或视觉推断回填；
              content_scope=snippet/abstract/fulltext/region，禁止以摘要冒充全文
- citation_id: 回答/任务内稳定，前缀 K/W/A/I；由完整来源身份+版本+位置+内容 hash
              生成并检测冲突，不只对标题或未版本化 URL 做短 hash

内容一律视为不可信数据（untrusted=True），不得提升成系统指令。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

SCHEMA_VERSION = 2

SOURCE_TYPES = ("kb_chunk", "web", "paper", "asset")
MODALITIES = ("text", "image", "mixed")
CONTENT_SCOPES = ("snippet", "abstract", "fulltext", "region")
EXTRACTION_METHODS = ("native_text", "ocr", "vision", "provider_text")

# citation_id 前缀：K=kb_chunk，W=web，A=paper(arXiv)，I=asset(图像)
CITATION_PREFIXES = {"kb_chunk": "K", "web": "W", "paper": "A", "asset": "I"}


class EvidenceValidationError(ValueError):
    """Evidence 不满足 schema v2 约束。"""


@dataclass(frozen=True)
class Locator:
    """证据位置。文本链路用 page/chunk/url/section；多模态字段 P3b 填充。"""

    page: int | None = None            # 1 起始页码
    chunk: str | None = None
    url: str | None = None
    section: str | None = None
    # ---- P3b 多模态占位（本轮留空，形状已校验）----
    artifact_id: str | None = None
    block_id: str | None = None
    region_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None  # 旋转校正 0-1 坐标
    rotation: float | None = None
    asset_id: str | None = None
    asset_hash: str | None = None

    def validate(self) -> None:
        if self.page is not None and self.page < 1:
            raise EvidenceValidationError(f"页码必须从 1 开始: {self.page}")
        if self.bbox is not None:
            if len(self.bbox) != 4 or any(not (0.0 <= v <= 1.0) for v in self.bbox):
                raise EvidenceValidationError(f"bbox 必须是 4 个 0-1 坐标: {self.bbox}")

    def position_key(self) -> str:
        parts = [self.page, self.chunk, self.url, self.section, self.block_id, self.region_id, self.bbox]
        return "|".join("" if p is None else str(p) for p in parts)


@dataclass(frozen=True)
class Provenance:
    """来源身份。按 source_type 必填字段不同（见 validate）。"""

    provider: str                      # knowledge_engine / tavily / arxiv ...
    title: str = ""
    content_hash: str = ""             # raw_text 或资产内容的 sha256
    # kb_chunk 身份
    doc_id: str | None = None
    doc_title: str | None = None
    doc_version: str | None = None
    chunk_id: str | None = None
    index_identity: str | None = None  # EmbeddingIdentity.key() 或索引名
    # web 身份
    canonical_url: str | None = None
    fetched_at: str | None = None
    # paper 身份
    arxiv_id: str | None = None
    arxiv_version: str | None = None
    doi: str | None = None
    fulltext_url: str | None = None

    def identity_key(self, source_type: str) -> str:
        """完整来源身份 + 版本：citation_id 生成与去重的依据。"""
        if source_type == "kb_chunk":
            return f"kb:{self.doc_id}:{self.doc_version}:{self.chunk_id}:{self.index_identity}"
        if source_type == "web":
            return f"web:{self.canonical_url}:{self.content_hash}"
        if source_type == "paper":
            base = f"paper:arxiv:{self.arxiv_id}:{self.arxiv_version}"
            return f"{base}:{self.doi}" if self.doi else base
        return f"asset:{self.content_hash}"


@dataclass(frozen=True)
class Extraction:
    """抽取方式。置信度只在有可靠来源时填，禁止伪造数值。"""

    method: str                        # native_text / ocr / vision / provider_text
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    preprocess_version: str | None = None
    raw_response_ref: str | None = None
    confidence: float | None = None

    def validate(self) -> None:
        if self.method not in EXTRACTION_METHODS:
            raise EvidenceValidationError(f"非法 extraction.method: {self.method}")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise EvidenceValidationError(f"confidence 必须在 [0,1]: {self.confidence}")


@dataclass(frozen=True)
class Score:
    """原始分只在相应召回列表内解释；RRF 与 rerank 分另存，不跨供应商比较。"""

    raw: float | None = None
    raw_channel: str | None = None     # vector / keyword / tavily ...
    rrf: float | None = None
    rerank: float | None = None


@dataclass(frozen=True)
class Evidence:
    """统一、版本化的证据对象。所有来源同构，不为新来源建第二套结构。"""

    citation_id: str
    source_id: str                     # Source Registry 登记 id
    source_type: str
    modality: str
    content_scope: str
    raw_text: str | None
    provenance: Provenance
    locator: Locator
    extraction: Extraction
    score: Score | None = None
    schema_version: int = SCHEMA_VERSION
    untrusted: bool = True             # 检索内容永不可提升为系统指令
    derived_observations: tuple[str, ...] = field(default_factory=tuple)  # P3b 视觉占位

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise EvidenceValidationError(f"schema_version 必须为 {SCHEMA_VERSION}")
        if self.source_type not in SOURCE_TYPES:
            raise EvidenceValidationError(f"非法 source_type: {self.source_type}")
        if self.modality not in MODALITIES:
            raise EvidenceValidationError(f"非法 modality: {self.modality}")
        if self.content_scope not in CONTENT_SCOPES:
            raise EvidenceValidationError(f"非法 content_scope: {self.content_scope}")
        if not self.citation_id or not self.source_id:
            raise EvidenceValidationError("citation_id/source_id 不能为空")
        expected_prefix = CITATION_PREFIXES[self.source_type]
        if not self.citation_id.startswith(expected_prefix):
            raise EvidenceValidationError(
                f"citation_id 前缀应为 {expected_prefix}: {self.citation_id}"
            )
        if not self.provenance.content_hash:
            raise EvidenceValidationError("provenance.content_hash 不能为空")
        self._validate_source_identity()
        self.locator.validate()
        self.extraction.validate()
        if self.modality == "text" and self.raw_text is None:
            raise EvidenceValidationError("text 模态的 raw_text 不能为空")
        if self.content_scope == "fulltext" and not (self.raw_text or "").strip():
            raise EvidenceValidationError("fulltext 范围必须有正文文本（禁止以摘要冒充全文）")

    def _validate_source_identity(self) -> None:
        p = self.provenance
        if self.source_type == "kb_chunk":
            missing = [
                name
                for name, val in (
                    ("doc_id", p.doc_id),
                    ("doc_version", p.doc_version),
                    ("chunk_id", p.chunk_id),
                    ("index_identity", p.index_identity),
                )
                if not val
            ]
            if missing:
                raise EvidenceValidationError(f"kb_chunk 缺来源身份字段: {missing}")
        elif self.source_type == "web":
            if not p.canonical_url or not p.fetched_at:
                raise EvidenceValidationError("web 证据必须含 canonical_url 与 fetched_at")
        elif self.source_type == "paper":
            if not p.arxiv_id or not p.arxiv_version:
                raise EvidenceValidationError("paper 证据必须含 arxiv_id 与明确版本")

    def make_citation_id(self) -> str:
        """由完整来源身份、版本、位置及内容 hash 生成稳定 citation_id。"""
        return make_citation_id(self.source_type, self.provenance, self.locator)


def make_citation_id(source_type: str, provenance: Provenance, locator: Locator) -> str:
    if source_type not in CITATION_PREFIXES:
        raise EvidenceValidationError(f"非法 source_type: {source_type}")
    material = "|".join(
        (
            provenance.identity_key(source_type),
            provenance.content_hash,
            locator.position_key(),
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"{CITATION_PREFIXES[source_type]}{digest}"
