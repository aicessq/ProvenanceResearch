"""eval 本地确定性检索基线（retriever: local-bigram-v1）。

对 `eval/corpus/text/*.pages.jsonl` 页文本做确定性词面打分（字符 bigram 覆盖 +
《标题》/条文号短语加成），不使用 embedding（embedding 是云能力；design.md 允许
本地 FTS/RRF）。产出与 tools 同构的 kb_chunk Evidence（doc_id/版本/chunk 身份），
走 evidence.store 登记，citation_id 由完整身份计算。

打分为纯函数、无随机性：同语料同查询永远同排名，满足"可复现 runner"。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evidence.registry import content_hash  # noqa: E402
from evidence.schema import Evidence, Extraction, Locator, Provenance, Score  # noqa: E402
from evidence.store import register_with_computed_id  # noqa: E402

RETRIEVER_VERSION = "local-bigram-v1"

_FULLWIDTH_MAP = {ord(c): ord(c) - 0xFEE0 for c in "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"}
_FULLWIDTH_MAP[ord("　")] = ord(" ")

_TITLE_RE = re.compile(r"《([^《》]{2,})》")
_CLAUSE_RE = re.compile(r"第[一二三四五六七八九十百千0-9]+条")


def normalize(text: str) -> str:
    """全角→半角、小写、去空白（与引用闸门的字面匹配口径一致）。"""
    return "".join(text.translate(_FULLWIDTH_MAP).lower().split())


def _bigrams(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for i in range(len(text) - 1):
        bg = text[i : i + 2]
        counts[bg] = counts.get(bg, 0) + 1
    return counts


@dataclass(frozen=True)
class CorpusHit:
    doc_id: str
    page: int
    score: float
    text: str
    title: str
    lang: str

    @property
    def chunk_id(self) -> str:
        return f"{self.doc_id}:p{self.page}"


class CorpusIndex:
    """语料页索引：manifest.jsonl（身份/标题）+ text/*.pages.jsonl（页文本）。"""

    def __init__(self, corpus_dir: str | Path) -> None:
        self._dir = Path(corpus_dir)
        self._titles: dict[str, str] = {}
        self._langs: dict[str, str] = {}
        self._versions: dict[str, str] = {}
        self._pages: list[tuple[str, int, str, str]] = []  # (doc_id, page, norm_text, raw_text)
        self._load()

    def _load(self) -> None:
        for line in (self._dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            doc_id = item["doc_id"]
            self._titles[doc_id] = item.get("title") or doc_id
            self._langs[doc_id] = item.get("lang") or ""
            self._versions[doc_id] = (item.get("sha256") or "")[:12]
        for path in sorted((self._dir / "text").glob("*.pages.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                text = item.get("text") or ""
                if not text.strip():
                    continue  # 扫描件无文本层：如实缺席，不伪造
                self._pages.append(
                    (item["doc_id"], int(item["page"]), normalize(text), text)
                )

    @property
    def manifest_versions(self) -> dict[str, str]:
        return dict(self._versions)

    def search(self, query: str, top_k: int = 20) -> list[CorpusHit]:
        """确定性打分：bigram 覆盖 + 《标题》命中 + 条文号命中；分数并列按 doc_id,page 定序。"""
        norm_query = normalize(query)
        if not norm_query:
            return []
        q_bigrams = set(_bigrams(norm_query))
        titles = [normalize(t) for t in _TITLE_RE.findall(query)]
        clauses = [normalize(c) for c in _CLAUSE_RE.findall(query)]
        phrase = norm_query

        scored: list[tuple[float, str, int]] = []
        for doc_id, page, norm_text, _raw in self._pages:
            hits = sum(1 for bg in q_bigrams if bg in norm_text)
            score = float(hits)
            if len(phrase) >= 4 and phrase in norm_text:
                score += 5.0
            title_norm = normalize(self._titles.get(doc_id, ""))
            if title_norm and any(t and t in title_norm for t in titles):
                score += 5.0
            for clause in clauses:
                if clause and clause in norm_text:
                    score += 4.0
            if score > 0:
                scored.append((score, doc_id, page))

        scored.sort(key=lambda x: (-x[0], x[1], x[2]))
        by_key = {(doc_id, page): (norm, raw) for doc_id, page, norm, raw in self._pages}
        hits: list[CorpusHit] = []
        for score, doc_id, page in scored[:top_k]:
            norm, raw = by_key[(doc_id, page)]
            hits.append(
                CorpusHit(
                    doc_id=doc_id,
                    page=page,
                    score=score,
                    text=raw,
                    title=self._titles.get(doc_id, doc_id),
                    lang=self._langs.get(doc_id, ""),
                )
            )
        return hits

    def build_evidence(self, hit: CorpusHit, store: Any, index_identity: str) -> Evidence:
        """与 tools/kb_search 同构的 kb_chunk Evidence（doc/version/chunk 身份齐全）。"""
        ev = Evidence(
            citation_id="",  # register_with_computed_id 重算
            source_id=f"kb:{hit.doc_id}:{self._versions.get(hit.doc_id, '')}",
            source_type="kb_chunk",
            modality="text",
            content_scope="fulltext",
            raw_text=hit.text,
            provenance=Provenance(
                provider="eval_corpus",
                title=hit.title,
                content_hash=content_hash(hit.text),
                doc_id=hit.doc_id,
                doc_title=hit.title,
                doc_version=self._versions.get(hit.doc_id, ""),
                chunk_id=hit.chunk_id,
                index_identity=index_identity,
            ),
            locator=Locator(page=hit.page, chunk=hit.chunk_id),
            extraction=Extraction(method="native_text", provider="eval_corpus"),
            score=Score(raw=hit.score, raw_channel="kb_local_bigram"),
        )
        return register_with_computed_id(store, ev)
