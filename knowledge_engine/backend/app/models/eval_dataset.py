"""eval_datasets 表 ORM 模型。"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.eval_dataset_item import EvalDatasetItem
    from app.models.eval_run import EvalRun


class EvalDataset(Base):
    """评测数据集定义表。"""

    __tablename__ = "eval_datasets"
    __table_args__ = (
        Index("idx_eval_datasets_status", "status"),
        Index("idx_eval_datasets_created_at", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default=text("'active'"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))

    items: Mapped[list["EvalDatasetItem"]] = relationship(back_populates="dataset")
    runs: Mapped[list["EvalRun"]] = relationship(back_populates="dataset")
