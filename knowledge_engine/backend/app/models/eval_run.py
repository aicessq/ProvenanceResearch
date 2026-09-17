"""eval_runs 表 ORM 模型。"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.eval_dataset import EvalDataset
    from app.models.eval_run_item import EvalRunItem


class EvalRun(Base):
    """评测运行主表。"""

    __tablename__ = "eval_runs"
    __table_args__ = (
        Index("idx_eval_runs_dataset_id", "dataset_id"),
        Index("idx_eval_runs_status", "status"),
        Index("idx_eval_runs_created_at", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("eval_datasets.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    recall_at_k: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    mrr: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    citation_accuracy: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    answer_groundedness: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    refusal_accuracy: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    average_latency_ms: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    dataset: Mapped["EvalDataset"] = relationship(back_populates="runs")
    items: Mapped[list["EvalRunItem"]] = relationship(back_populates="run")
