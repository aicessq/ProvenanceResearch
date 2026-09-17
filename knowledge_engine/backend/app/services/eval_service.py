"""评测服务。

Phase 10 负责把系统从“能工作”升级为“能被量化评估”。
本模块复用真实 safety / rewrite / retrieve / answer 主链路的核心能力，
并把 run 级与 item 级结果持久化到数据库。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.eval_dataset import EvalDataset
from app.models.eval_dataset_item import EvalDatasetItem
from app.models.eval_run import EvalRun
from app.models.eval_run_item import EvalRunItem
from app.services.answer_generator import AnswerGenerator, EvidenceContext
from app.services.citation_checker import CitationChecker
from app.services.intent_classifier import IntentClassifier
from app.services.metadata_filter import MetadataFilter, MetadataFilterBuilder
from app.services.query_service import build_evidence_contexts
from app.services.query_rewriter import QueryRewriter
from app.services.retriever import HybridRetriever
from app.services.safety_guard import SafetyGuard
from app.services.term_expander import TermExpander

DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[3] / "eval" / "golden_dataset.jsonl"


@dataclass(slots=True)
class GoldenDatasetEntry:
    query: str
    expected_doc_type: str | None = None
    expected_keywords: list[str] = field(default_factory=list)
    expected_chunk_ids: list[str] = field(default_factory=list)
    expected_refusal: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class EvalItemComputation:
    query: str
    retrieved_chunk_ids: list[str]
    answer: str | None
    refusal_triggered: bool
    recall_hit: bool
    reciprocal_rank: float
    citation_passed: bool | None
    groundedness_score: float | None
    latency_ms: int
    error_message: str | None = None


@dataclass(slots=True)
class EvalRunSummary:
    run_id: str
    dataset_name: str
    total_count: int
    recall_at_k: float
    mrr: float
    citation_accuracy: float
    refusal_accuracy: float
    average_latency_ms: float
    status: str


def load_golden_dataset(path: str | Path = DEFAULT_DATASET_PATH) -> list[GoldenDatasetEntry]:
    """读取 JSONL golden dataset。"""
    dataset_path = Path(path)
    if not dataset_path.exists():
        raise ValueError(f"评测数据集不存在：{dataset_path}")
    entries: list[GoldenDatasetEntry] = []
    for raw_line in dataset_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        entries.append(
            GoldenDatasetEntry(
                query=str(payload["query"]),
                expected_doc_type=payload.get("expected_doc_type"),
                expected_keywords=list(payload.get("expected_keywords") or []),
                expected_chunk_ids=list(payload.get("expected_chunk_ids") or []),
                expected_refusal=bool(payload.get("expected_refusal", False)),
                metadata=dict(payload.get("metadata") or {}),
            )
        )
    return entries


def compute_recall_at_k(hits: list[bool]) -> float:
    """计算 Recall@K。"""
    if not hits:
        return 0.0
    return sum(1 for hit in hits if hit) / len(hits)


def compute_mrr(reciprocal_ranks: list[float]) -> float:
    """计算 MRR。"""
    if not reciprocal_ranks:
        return 0.0
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def compute_refusal_accuracy(expected: list[bool], actual: list[bool]) -> float:
    """计算拒答准确率。"""
    if not expected:
        return 0.0
    correct = sum(1 for expected_flag, actual_flag in zip(expected, actual, strict=True) if expected_flag == actual_flag)
    return correct / len(expected)


def run_eval(
    *,
    db: Session,
    dataset_name: str = "golden-dataset",
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
) -> EvalRunSummary:
    """执行一轮评测并把结果持久化。"""
    entries = load_golden_dataset(dataset_path)
    dataset = _get_or_create_dataset(db, dataset_name=dataset_name, dataset_path=dataset_path, entries=entries)
    run = EvalRun(
        dataset_id=dataset.id,
        status="running",
        total_count=len(entries),
        completed_count=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    retriever = HybridRetriever.from_db(db)
    answer_generator = AnswerGenerator()
    citation_checker = CitationChecker()

    results: list[EvalItemComputation] = []
    expected_refusal_flags: list[bool] = []
    actual_refusal_flags: list[bool] = []

    dataset_items = _sync_dataset_items(db, dataset=dataset, entries=entries)

    for dataset_item in dataset_items:
        started_at = time.perf_counter()
        try:
            computation = _evaluate_item(
                db=db,
                dataset_item=dataset_item,
                retriever=retriever,
                answer_generator=answer_generator,
                citation_checker=citation_checker,
            )
        except Exception as exc:  # noqa: BLE001
            computation = EvalItemComputation(
                query=dataset_item.query,
                retrieved_chunk_ids=[],
                answer=None,
                refusal_triggered=False,
                recall_hit=False,
                reciprocal_rank=0.0,
                citation_passed=False,
                groundedness_score=0.0,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                error_message=str(exc),
            )

        results.append(computation)
        expected_refusal_flags.append(dataset_item.expected_refusal)
        actual_refusal_flags.append(computation.refusal_triggered)
        _persist_run_item(db, run=run, dataset_item=dataset_item, computation=computation)
        run.completed_count += 1
        db.commit()

    recall_at_k = compute_recall_at_k([item.recall_hit for item in results])
    mrr = compute_mrr([item.reciprocal_rank for item in results])
    citation_accuracy = compute_recall_at_k([bool(item.citation_passed) for item in results if item.citation_passed is not None])
    refusal_accuracy = compute_refusal_accuracy(expected_refusal_flags, actual_refusal_flags)
    average_latency_ms = sum(item.latency_ms for item in results) / len(results) if results else 0.0

    run.status = "completed"
    run.recall_at_k = recall_at_k
    run.mrr = mrr
    run.citation_accuracy = citation_accuracy
    run.refusal_accuracy = refusal_accuracy
    run.answer_groundedness = citation_accuracy
    run.average_latency_ms = average_latency_ms
    run.finished_at = datetime.now(timezone.utc)
    db.commit()

    return EvalRunSummary(
        run_id=str(run.id),
        dataset_name=dataset.name,
        total_count=run.total_count,
        recall_at_k=float(recall_at_k),
        mrr=float(mrr),
        citation_accuracy=float(citation_accuracy),
        refusal_accuracy=float(refusal_accuracy),
        average_latency_ms=float(average_latency_ms),
        status=run.status,
    )


def _evaluate_item(
    *,
    db: Session,
    dataset_item: EvalDatasetItem,
    retriever: HybridRetriever,
    answer_generator: AnswerGenerator,
    citation_checker: CitationChecker,
) -> EvalItemComputation:
    started_at = time.perf_counter()
    query = dataset_item.query
    safety = SafetyGuard().evaluate(query)
    refusal_triggered = safety.action != "allow"

    if refusal_triggered:
        return EvalItemComputation(
            query=query,
            retrieved_chunk_ids=[],
            answer=safety.safe_response,
            refusal_triggered=True,
            recall_hit=False,
            reciprocal_rank=0.0,
            citation_passed=True if dataset_item.expected_refusal else False,
            groundedness_score=None,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
        )

    intent = IntentClassifier().classify(query)
    expanded_terms = TermExpander().expand(query)
    rewritten = QueryRewriter().rewrite(query, intent=intent, expanded_terms=expanded_terms)
    built_filters = MetadataFilterBuilder().build(
        explicit_filters={"doc_type": [dataset_item.expected_doc_type]} if dataset_item.expected_doc_type else {},
        suggested_doc_types=intent.suggested_doc_types,
    )
    retrieval = retriever.search(
        query=rewritten.rewritten_query,
        top_k=5,
        filters=MetadataFilter.from_input(built_filters.to_payload_dict()),
        debug=False,
        search_keywords=rewritten.search_keywords,
        sub_queries=rewritten.sub_queries,
    )
    retrieved_chunk_ids = [str(item.chunk_id) for item in retrieval.final_results]
    evidence_contexts = build_evidence_contexts(db, retrieval.final_results)
    generated = answer_generator.generate(query=query, evidence_contexts=evidence_contexts)
    checked = citation_checker.check(generated=generated, evidence_contexts=evidence_contexts)

    return EvalItemComputation(
        query=query,
        retrieved_chunk_ids=retrieved_chunk_ids,
        answer=checked.fixed_answer,
        refusal_triggered=False,
        recall_hit=_is_recall_hit(dataset_item.expected_chunk_ids, retrieved_chunk_ids),
        reciprocal_rank=_compute_reciprocal_rank(dataset_item.expected_chunk_ids, retrieved_chunk_ids),
        citation_passed=checked.passed,
        groundedness_score=1.0 if checked.passed else 0.0,
        latency_ms=int((time.perf_counter() - started_at) * 1000),
    )


def _build_evidence_contexts(db: Session, results) -> list[EvidenceContext]:
    parent_ids = {str(item.parent_chunk_id) for item in results if getattr(item, "parent_chunk_id", None)}
    parent_map = {parent_id: db.get(Chunk, parent_id) for parent_id in parent_ids}
    return [
        EvidenceContext(
            chunk_id=str(item.chunk_id),
            doc_title=item.doc_title,
            doc_type=item.doc_type,
            chunk_text=item.chunk_text,
            page_start=item.page_start,
            page_end=item.page_end,
            chapter=item.chapter,
            section=item.section,
            article_no=item.article_no,
            parent_chunk_id=str(item.parent_chunk_id) if getattr(item, "parent_chunk_id", None) else None,
            parent_text=(parent_map.get(str(item.parent_chunk_id)).text if parent_map.get(str(item.parent_chunk_id)) else item.chunk_text),
            score=item.score,
            source=item.source,
        )
        for item in results
    ]


def _is_recall_hit(expected_chunk_ids: list[str], retrieved_chunk_ids: list[str]) -> bool:
    if not expected_chunk_ids:
        return False
    expected_set = set(expected_chunk_ids)
    return any(chunk_id in expected_set for chunk_id in retrieved_chunk_ids)


def _compute_reciprocal_rank(expected_chunk_ids: list[str], retrieved_chunk_ids: list[str]) -> float:
    if not expected_chunk_ids:
        return 0.0
    expected_set = set(expected_chunk_ids)
    for index, chunk_id in enumerate(retrieved_chunk_ids, start=1):
        if chunk_id in expected_set:
            return 1.0 / index
    return 0.0


def _get_or_create_dataset(
    db: Session,
    *,
    dataset_name: str,
    dataset_path: str | Path,
    entries: list[GoldenDatasetEntry],
) -> EvalDataset:
    dataset = db.execute(select(EvalDataset).where(EvalDataset.name == dataset_name)).scalar_one_or_none()
    if dataset is None:
        dataset = EvalDataset(name=dataset_name, description="Phase 10 golden dataset", source_path=str(dataset_path), status="active")
        db.add(dataset)
        db.flush()
    dataset.source_path = str(dataset_path)
    dataset.updated_at = datetime.now(timezone.utc)
    _sync_dataset_items(db, dataset=dataset, entries=entries)
    db.commit()
    return dataset


def _sync_dataset_items(db: Session, *, dataset: EvalDataset, entries: list[GoldenDatasetEntry]) -> list[EvalDatasetItem]:
    """同步 JSONL 数据集样本，保留历史 run item 的外键引用。"""
    existing_items = db.execute(
        select(EvalDatasetItem).where(EvalDatasetItem.dataset_id == dataset.id).order_by(EvalDatasetItem.created_at.asc())
    ).scalars().all()
    synced_items: list[EvalDatasetItem] = []
    now = datetime.now(timezone.utc)
    for index, entry in enumerate(entries):
        if index < len(existing_items):
            item = existing_items[index]
            item.query = entry.query
            item.expected_doc_type = entry.expected_doc_type
            item.expected_keywords = entry.expected_keywords
            item.expected_chunk_ids = entry.expected_chunk_ids
            item.expected_refusal = entry.expected_refusal
            item.metadata_json = entry.metadata
            item.updated_at = now
        else:
            item = EvalDatasetItem(
                dataset_id=dataset.id,
                query=entry.query,
                expected_doc_type=entry.expected_doc_type,
                expected_keywords=entry.expected_keywords,
                expected_chunk_ids=entry.expected_chunk_ids,
                expected_refusal=entry.expected_refusal,
                metadata_json=entry.metadata,
            )
            db.add(item)
        synced_items.append(item)
    db.flush()
    return synced_items


def _persist_run_item(db: Session, *, run: EvalRun, dataset_item: EvalDatasetItem, computation: EvalItemComputation) -> None:
    db.add(
        EvalRunItem(
            run_id=run.id,
            dataset_item_id=dataset_item.id,
            query=computation.query,
            retrieved_chunk_ids=computation.retrieved_chunk_ids,
            reranked_chunk_ids=[],
            answer=computation.answer,
            refusal_triggered=computation.refusal_triggered,
            recall_hit=computation.recall_hit,
            reciprocal_rank=computation.reciprocal_rank,
            citation_passed=computation.citation_passed,
            groundedness_score=computation.groundedness_score,
            latency_ms=computation.latency_ms,
            error_message=computation.error_message,
        )
    )
