"""eval_dataset_items 表 ORM 模型。"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.sql import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.eval_dataset import EvalDataset
    from app.models.eval_run_item import EvalRunItem


class EvalDatasetItem(Base):
    """评测数据集样本表。"""

    __tablename__ = "eval_dataset_items"
    __table_args__ = (
        Index("idx_eval_dataset_items_dataset_id", "dataset_id"),
        Index("idx_eval_dataset_items_expected_doc_type", "expected_doc_type"),
        Index("idx_eval_dataset_items_expected_keywords_gin", "expected_keywords", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("eval_datasets.id"), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expected_doc_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb"))
    expected_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb"))
    expected_refusal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sql_text("FALSE"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("NOW()"))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("NOW()"))

    dataset: Mapped["EvalDataset"] = relationship(back_populates="items")
    run_items: Mapped[list["EvalRunItem"]] = relationship(back_populates="dataset_item")
