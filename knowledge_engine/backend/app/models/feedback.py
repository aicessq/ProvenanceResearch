"""feedback 表 ORM 模型。"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.query_log import QueryLog


class Feedback(Base):
    """用户反馈表。"""

    __tablename__ = "feedback"
    __table_args__ = (
        Index("idx_feedback_query_log_id", "query_log_id"),
        Index("idx_feedback_score", "score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_log_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("query_logs.id"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, server_default=text("NOW()"))

    query_log: Mapped["QueryLog"] = relationship(back_populates="feedback_entries")
