"""query_logs 表 ORM 模型。"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.feedback import Feedback


class QueryLog(Base):
    """查询日志表。"""

    __tablename__ = "query_logs"
    __table_args__ = (
        Index("idx_query_logs_created_at", text("created_at DESC")),
        Index("idx_query_logs_intent", "intent"),
        Index("idx_query_logs_safety_action", "safety_action"),
        Index("idx_query_logs_risk_type", "risk_type"),
        Index("idx_query_logs_filters_gin", "filters", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    safety_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    retrieved_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    reranked_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    feedback_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))

    feedback_entries: Mapped[list["Feedback"]] = relationship(back_populates="query_log")
