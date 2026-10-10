"""硬化轮契约（roadmap 硬化验收：未认证请求被拒、限流生效、指标可查）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core import rate_limit as rate_limit_module
from app.core.auth import AuthConfigError, AuthError, issue_token, verify_token
from app.core.rate_limit import RateLimiter
from main import create_application

SECRET = "x" * 48


def auth_env(monkeypatch, *, enabled: str = "true", secret: str = SECRET) -> None:
    monkeypatch.setenv("AUTH_ENABLED", enabled)
    monkeypatch.setenv("AUTH_SECRET_KEY", secret)
    monkeypatch.setenv("AUTH_BOOTSTRAP_USER", "admin")
    monkeypatch.setenv("AUTH_BOOTSTRAP_PASSWORD", "correct-horse")
    monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "60")


def test_unauthenticated_requests_are_rejected(monkeypatch) -> None:
    auth_env(monkeypatch)
    with TestClient(create_application()) as client:
        missing = client.get("/api/v1/tasks")
        assert missing.status_code == 401
        assert missing.headers["content-type"].startswith("application/problem+json")
        assert missing.json()["code"] == "auth_required"

        bad = client.get("/api/v1/tasks", headers={"Authorization": "Bearer not-a-jwt"})
        assert bad.status_code == 401
        assert bad.json()["code"] == "token_invalid"

        token_resp = client.post("/api/v1/auth/token", json={"username": "admin", "password": "correct-horse"})
        assert token_resp.status_code == 200
        token = token_resp.json()["access_token"]
        ok = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200  # 带合法 token 放行


def test_bad_credentials_and_weak_secret_fail_explicitly(monkeypatch) -> None:
    auth_env(monkeypatch)
    with TestClient(create_application()) as client:
        wrong = client.post("/api/v1/auth/token", json={"username": "admin", "password": "nope"})
        assert wrong.status_code == 401
        assert wrong.json()["code"] == "invalid_credentials"

    monkeypatch.setenv("AUTH_SECRET_KEY", "short")
    with TestClient(create_application()) as client:
        unconfigured = client.post("/api/v1/auth/token", json={"username": "admin", "password": "correct-horse"})
        assert unconfigured.status_code == 503
        assert unconfigured.json()["code"] == "auth_not_configured"  # 不用弱密钥签发

        guarded = client.get("/api/v1/tasks", headers={"Authorization": "Bearer x"})
        assert guarded.status_code == 503  # 不静默放行


def test_auth_disabled_keeps_local_dev_open(monkeypatch) -> None:
    auth_env(monkeypatch, enabled="false")
    with TestClient(create_application()) as client:
        assert client.get("/api/v1/tasks").status_code == 200


def test_issue_and_verify_token_roundtrip(monkeypatch) -> None:
    auth_env(monkeypatch)
    token, ttl = issue_token("admin", "correct-horse")
    assert ttl == 60
    claims = verify_token(token)
    assert claims["sub"] == "admin"
    monkeypatch.setenv("AUTH_BOOTSTRAP_USER", "other")
    try:
        issue_token("admin", "correct-horse")
        raise AssertionError("应当拒绝")
    except AuthError as exc:
        assert exc.code == "invalid_credentials"


def test_rate_limiter_buckets_and_retry_after(monkeypatch) -> None:
    clock = {"now": 0.0}
    limiter = RateLimiter(
        enabled=True,
        limits_per_minute={"query": 2, "ingest": 1, "default": 5},
        clock=lambda: clock["now"],
    )
    assert limiter.check("query", "ip-1")[0] is True
    assert limiter.check("query", "ip-1")[0] is True
    allowed, retry_after = limiter.check("query", "ip-1")
    assert allowed is False and retry_after >= 1  # 429 需带 Retry-After

    assert limiter.check("ingest", "ip-1")[0] is True  # 分桶独立
    assert limiter.check("query", "ip-2")[0] is True  # 分客户端独立

    clock["now"] = 61.0
    assert limiter.check("query", "ip-1")[0] is True  # 下一窗口恢复


def test_rate_limit_enforced_over_http(monkeypatch) -> None:
    auth_env(monkeypatch, enabled="false")
    monkeypatch.setattr(
        rate_limit_module,
        "rate_limiter",
        RateLimiter(enabled=True, limits_per_minute={"query": 1, "ingest": 1, "default": 100}),
    )
    with TestClient(create_application()) as client:
        first = client.post("/api/v1/tasks", json={"query": "问题一"})
        assert first.status_code == 201
        second = client.post("/api/v1/tasks", json={"query": "问题二"})
        assert second.status_code == 429
        assert second.headers.get("Retry-After")
        assert second.json()["code"] == "rate_limited"
        assert client.get("/api/v1/tasks").status_code == 200  # default 桶不受 query 桶影响


def test_metrics_endpoint_counts_auth_failures(monkeypatch) -> None:
    auth_env(monkeypatch)
    with TestClient(create_application()) as client:
        client.get("/api/v1/tasks")  # 401
        body = client.get("/api/v1/metrics").text
        assert "auth_failures_total" in body
        assert "http_requests_total" in body
        assert "task_terminal_total" in body
        assert int([l for l in body.splitlines() if l.startswith("auth_failures_total ")][0].split()[-1]) >= 1
