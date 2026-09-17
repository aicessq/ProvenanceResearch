"""最小集成测试：验证 PostgreSQL / Redis / Qdrant 真实连通性。

设计说明（教学向）
==================

1. 这组测试默认**不会**随 `pytest` 自动运行——它们带有 `integration` 标记，
   而 pyproject.toml 中 addopts 设置了 `-m 'not integration'`。
   需要时显式运行：`pytest -m integration`。
2. 它们用于 Phase 0 的“基础服务联通性验证”验收：
   在 docker compose up 拉起基础设施后，从宿主机用 localhost 跑这组测试，
   即可复现验证 PG/Redis/Qdrant 连接正常。
3. 这条集成测试通道是严格验收：依赖不可达必须失败，不能用 skip 伪装成通过。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = str(Path(__file__).resolve().parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


def _assert_reachable(check_fn) -> None:
    """调用检查函数；依赖不可达时让集成验收明确失败。"""
    try:
        ok = check_fn()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"服务不可达：{exc}")
    assert ok, "服务未连接成功，请确认真实基础设施已启动"


@pytest.mark.integration
def test_postgres_connection() -> None:
    """验证 PostgreSQL 可连接并执行 SELECT 1。"""
    from app.db.session import check_database_connection

    _assert_reachable(check_database_connection)
    assert check_database_connection() is True


@pytest.mark.integration
def test_redis_connection() -> None:
    """验证 Redis 可连接并响应 PING。"""
    from app.dependencies import check_redis_connection

    _assert_reachable(check_redis_connection)
    assert check_redis_connection() is True


@pytest.mark.integration
def test_qdrant_connection() -> None:
    """验证 Qdrant 可连接并能列出集合。"""
    from app.dependencies import check_qdrant_connection

    _assert_reachable(check_qdrant_connection)
    assert check_qdrant_connection() is True


@pytest.mark.integration
def test_health_ready_all_ok(client) -> None:
    """验证 /health/ready 在基础设施齐全时返回 status=ok。"""
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok", f"部分组件未就绪：{body['components']}"
