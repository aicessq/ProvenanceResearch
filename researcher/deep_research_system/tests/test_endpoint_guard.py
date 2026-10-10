"""P2.5-0.1 模型端点 SSRF 防护测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.errors import EndpointNotAllowedError
from app.model_pool.endpoint_guard import validate_model_endpoint
from main import create_application


def test_allows_registered_provider_https_endpoint() -> None:
    base = validate_model_endpoint("deepseek", "https://api.deepseek.com/v1")
    assert base == "https://api.deepseek.com/v1"


def test_infers_provider_from_allowlisted_host() -> None:
    base = validate_model_endpoint("", "https://api.moonshot.cn/v1/")
    assert base == "https://api.moonshot.cn/v1"


@pytest.mark.parametrize(
    "provider,api_base",
    [
        ("deepseek", "https://localhost:3000/v1"),
        ("deepseek", "https://127.0.0.1/v1"),
        ("deepseek", "https://10.0.0.5/v1"),
        ("deepseek", "https://192.168.1.10/v1"),
        ("deepseek", "https://172.16.0.3/v1"),
        ("deepseek", "https://169.254.169.254/latest/meta-data"),
        ("deepseek", "file:///etc/passwd"),
        ("deepseek", "http://api.deepseek.com/v1"),
        ("deepseek", "https://evil.example.com/v1"),
        ("evil", "https://api.deepseek.com/v1"),
        ("", "https://evil.example.com/v1"),
        ("deepseek", "https://api.deepseek.com@evil.example.com/v1"),
        ("deepseek", "https://api.deepseek.com:8443/v1"),
        ("deepseek", ""),
    ],
)
def test_rejects_forbidden_targets(provider: str, api_base: str) -> None:
    with pytest.raises(EndpointNotAllowedError):
        validate_model_endpoint(provider, api_base)


def test_rejects_ip_literal_even_public() -> None:
    with pytest.raises(EndpointNotAllowedError):
        validate_model_endpoint("deepseek", "https://8.8.8.8/v1")


def test_models_test_route_rejects_before_any_outbound(monkeypatch) -> None:
    """路由级验收：非法目标在任何出站请求之前被拒绝。"""
    import httpx

    def _fail(*args, **kwargs):  # pragma: no cover - 防御断言
        raise AssertionError("非法端点不得发起出站请求")

    monkeypatch.setattr(httpx, "AsyncClient", _fail)

    app = create_application()
    with TestClient(app) as client:
        for api_base in (
            "https://localhost:3000/v1",
            "https://10.0.0.5/v1",
            "file:///etc/passwd",
            "https://evil.example.com/v1",
        ):
            resp = client.post(
                "/api/models/test",
                json={"model_name": "m", "api_key": "k", "api_base": api_base, "provider": "deepseek"},
            )
            assert resp.status_code == 400, api_base
            assert resp.json()["code"] == "ENDPOINT_NOT_ALLOWED"

        resp = client.post(
            "/api/models/test",
            json={"model_name": "m", "api_key": "k", "api_base": "https://evil.example.com/v1", "provider": "evil"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "ENDPOINT_NOT_ALLOWED"
