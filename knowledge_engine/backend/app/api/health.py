"""健康检查接口。

设计说明（教学向）
==================

1. 为什么分两个健康检查接口？
   - GET /health：**存活探针（liveness）**，只要进程能响应就返回 ok。
     不依赖任何外部服务，常用于容器编排（Docker/K8s）判断“进程是否还活着”。
     规格 §17.1 要求其返回 {"status": "ok"}。
   - GET /health/ready：**就绪探针（readiness）**，额外探活 PostgreSQL / Redis / Qdrant，
     用于判断“服务是否可以接收真实流量”。Phase 0 验收要求三者连接正常，
     本接口正是该验收的可复现验证手段。

2. 为什么 /health/ready 不在某个组件挂掉时返回 500？
   就绪探针应返回 200 并在 body 中标明各组件状态，
   方便运维/脚本区分“服务整体不可用”与“某个组件不可用”。
   编排系统可根据 overall=false 把流量摘除，而不必依赖 HTTP 状态码。

3. API 层不写业务逻辑：这里只做“调用 dependencies 中的连接检查函数 + 组装结果”，
   不直接拼连接串、不直接发 SQL/命令。
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel

from app.dependencies import (
    check_celery_worker_connection,
    check_qdrant_connection,
    check_redis_connection,
)
from app.db.session import check_database_connection

router = APIRouter(tags=["health"])


# ---- 响应模型 ----
class HealthResponse(BaseModel):
    """存活探针响应：与规格 §17.1 完全一致。"""

    status: str


class ComponentStatus(BaseModel):
    """单个基础设施组件的连通状态。"""

    connected: bool
    latency_ms: float | None = None
    worker_count: int | None = None
    required_tasks_registered: bool | None = None


class ReadyResponse(BaseModel):
    """就绪探针响应：汇总各组件状态。"""

    status: str  # "ok" 或 "degraded"
    components: dict[str, ComponentStatus]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """存活探针：进程存活即返回 ok，不依赖外部服务。"""
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=ReadyResponse)
def health_ready() -> ReadyResponse:
    """就绪探针：探活 PostgreSQL / Redis / Qdrant 并汇总状态。"""
    components: dict[str, ComponentStatus] = {}

    # 逐个探活并记录耗时，便于排查“能连但很慢”的情况
    for name, check_fn in {
        "postgres": check_database_connection,
        "redis": check_redis_connection,
        "qdrant": check_qdrant_connection,
    }.items():
        start = time.perf_counter()
        try:
            connected = check_fn()
        except Exception:  # noqa: BLE001 - readiness 必须稳定返回降级状态
            connected = False
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        components[name] = ComponentStatus(connected=connected, latency_ms=latency_ms)

    start = time.perf_counter()
    try:
        connected, worker_count, required_tasks_registered = check_celery_worker_connection()
    except Exception:  # noqa: BLE001 - Worker 或 Broker 故障不能导致 500
        connected = False
        worker_count = None
        required_tasks_registered = None
    components["celery_worker"] = ComponentStatus(
        connected=connected,
        latency_ms=round((time.perf_counter() - start) * 1000, 2),
        worker_count=worker_count,
        required_tasks_registered=required_tasks_registered,
    )

    overall = all(c.connected for c in components.values()) and required_tasks_registered is True
    return ReadyResponse(
        status="ok" if overall else "degraded",
        components=components,
    )
