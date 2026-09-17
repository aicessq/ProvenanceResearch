"""eval_run_items 表 ORM 模型。"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.eval_dataset_item import EvalDatasetItem
    from app.models.eval_run import EvalRun


class EvalRunItem(Base):
    """评测运行样本结果表。"""

    __tablename__ = "eval_run_items"
    __table_args__ = (
        Index("idx_eval_run_items_run_id", "run_id"),
        Index("idx_eval_run_items_dataset_item_id", "dataset_item_id"),
        Index("idx_eval_run_items_refusal_triggered", "refusal_triggered"),
        Index("idx_eval_run_items_citation_passed", "citation_passed"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("eval_runs.id"), nullable=False)
    dataset_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("eval_dataset_items.id"), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    reranked_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    refusal_triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("FALSE"))
    recall_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("FALSE"))
    reciprocal_rank: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    citation_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    groundedness_score: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))

    run: Mapped["EvalRun"] = relationship(back_populates="items")
    dataset_item: Mapped["EvalDatasetItem"] = relationship(back_populates="run_items")
