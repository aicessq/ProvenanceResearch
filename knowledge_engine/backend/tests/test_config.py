"""配置与启动层面的基本验证。

对应验收项：至少一个配置/启动层面的基本验证。
覆盖：
- Settings 在无 .env 时可用默认值实例化；
- 派生连接串格式正确；
- FastAPI app 对象可正常创建且注册了根路径 /health。
"""

from __future__ import annotations

import sys
from pathlib import Path


def test_settings_defaults() -> None:
    """Settings 在无环境变量时应能用默认值实例化，并派生出合法连接串。"""
    # 确保导入路径
    backend_dir = str(Path(__file__).resolve().parent.parent)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from app.config import Settings

    s = Settings()  # type: ignore[call-arg]
    # 默认应用名
    assert s.app_name == "cybersec-rag-agent"
    # 派生属性：连接串必须包含主机与端口
    assert "localhost" in s.postgres_dsn
    assert "5432" in s.postgres_dsn
    assert s.redis_url.startswith("redis://")
    assert s.qdrant_url == "http://localhost:6333"


def test_app_object_has_health_route() -> None:
    """FastAPI app 应成功创建，并包含 /health 路由。"""
    backend_dir = str(Path(__file__).resolve().parent.parent)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from app.main import app

    # 收集所有已注册路由的 path
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/api/v1/health/ready" in paths
