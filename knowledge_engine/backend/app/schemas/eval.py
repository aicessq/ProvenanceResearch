"""eval 相关 Pydantic schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EvalRunRequest(BaseModel):
    """Phase 10 评测运行请求。"""

    dataset_name: str = Field(default="golden-dataset", min_length=1, max_length=255)
    dataset_path: str | None = Field(default=None)


class EvalRunResponse(BaseModel):
    """Phase 10 评测运行结果摘要。"""

    run_id: str
    dataset_name: str
    total_count: int
    recall_at_k: float
    mrr: float
    citation_accuracy: float
    refusal_accuracy: float
    average_latency_ms: float
    status: str
