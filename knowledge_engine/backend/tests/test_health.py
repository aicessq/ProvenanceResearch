"""健康检查接口测试。

对应验收项：GET /health 返回 200 且 body 为 {"status": "ok"}。
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    """/health 应返回 200 且 body 为 {"status":"ok"}。"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready_shape(client: TestClient, monkeypatch) -> None:
    """/health/ready 应返回 200，且包含全部依赖组件状态字段。"""
    monkeypatch.setattr("app.api.health.check_database_connection", lambda: True)
    monkeypatch.setattr("app.api.health.check_redis_connection", lambda: True)
    monkeypatch.setattr("app.api.health.check_qdrant_connection", lambda: True)
    monkeypatch.setattr(
        "app.api.health.check_celery_worker_connection",
        lambda: (True, 1, True),
    )

    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    components = body["components"]
    assert set(components.keys()) == {"postgres", "redis", "qdrant", "celery_worker"}
    for info in components.values():
        assert isinstance(info["connected"], bool)
    assert components["postgres"]["worker_count"] is None
    assert components["postgres"]["required_tasks_registered"] is None
    assert components["celery_worker"]["worker_count"] == 1
    assert components["celery_worker"]["required_tasks_registered"] is True


def test_health_ready_degrades_when_required_tasks_are_missing(client: TestClient, monkeypatch) -> None:
    """Worker 在线但关键任务未完整注册时应降级。"""
    monkeypatch.setattr("app.api.health.check_database_connection", lambda: True)
    monkeypatch.setattr("app.api.health.check_redis_connection", lambda: True)
    monkeypatch.setattr("app.api.health.check_qdrant_connection", lambda: True)
    monkeypatch.setattr(
        "app.api.health.check_celery_worker_connection",
        lambda: (True, 1, False),
    )

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    celery = response.json()["components"]["celery_worker"]
    assert celery["connected"] is True
    assert celery["required_tasks_registered"] is False


def test_health_ready_degrades_when_celery_check_raises(client: TestClient, monkeypatch) -> None:
    """Celery 探活异常不应导致 500。"""
    monkeypatch.setattr("app.api.health.check_database_connection", lambda: True)
    monkeypatch.setattr("app.api.health.check_redis_connection", lambda: True)
    monkeypatch.setattr("app.api.health.check_qdrant_connection", lambda: True)

    def raise_celery_error():
        raise RuntimeError("worker unavailable")

    monkeypatch.setattr("app.api.health.check_celery_worker_connection", raise_celery_error)

    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    celery = response.json()["components"]["celery_worker"]
    assert celery == {
        "connected": False,
        "latency_ms": celery["latency_ms"],
        "worker_count": None,
        "required_tasks_registered": None,
    }
