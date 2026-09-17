"""评测接口。

Phase 10 提供 `/eval/run`，用于执行一轮 golden dataset 评测，
并把 run / item 结果落到数据库，方便后续比较系统迭代效果。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.eval import EvalRunRequest, EvalRunResponse
from app.services.eval_service import run_eval

router = APIRouter(prefix="/eval", tags=["eval"])


@router.post("/run", response_model=EvalRunResponse)
def run_eval_endpoint(
    request: EvalRunRequest,
    db: Session = Depends(get_db),
) -> EvalRunResponse:
    """执行一轮评测。"""
    try:
        kwargs = {"db": db, "dataset_name": request.dataset_name}
        if request.dataset_path:
            kwargs["dataset_path"] = request.dataset_path
        summary = run_eval(**kwargs)
        return EvalRunResponse(
            run_id=summary.run_id,
            dataset_name=summary.dataset_name,
            total_count=summary.total_count,
            recall_at_k=summary.recall_at_k,
            mrr=summary.mrr,
            citation_accuracy=summary.citation_accuracy,
            refusal_accuracy=summary.refusal_accuracy,
            average_latency_ms=summary.average_latency_ms,
            status=summary.status,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "invalid_request",
                    "message": str(exc),
                    "details": {},
                }
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "internal_error",
                    "message": "评测执行失败，请稍后重试",
                    "details": {"reason": str(exc)},
                }
            },
        ) from exc
