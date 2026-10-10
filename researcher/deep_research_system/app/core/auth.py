"""JWT 认证（硬化轮）：HS256（pyjwt），受保护路由必须携带 Bearer token。

- `AUTH_ENABLED=true` 时未认证请求一律 401（problem+json），不静默放行；
  未配置强主密钥/引导账号时**显式拒绝**（auth_not_configured），不回退匿名。
- `AUTH_ENABLED=false` 仅用于本机开发/联调（服务默认仅本机监听——design.md §9）；
  开放到网络前必须 AUTH_ENABLED=true 并配置 AUTH_SECRET_KEY（≥32 字符）与
  AUTH_BOOTSTRAP_USER/AUTH_BOOTSTRAP_PASSWORD。
- token 只含 sub/iat/exp，短 TTL；密钥只在启动环境，不进日志/GET。
"""

from __future__ import annotations

import hmac
import os
import time

import jwt as pyjwt

ALGORITHM = "HS256"
MIN_SECRET_LENGTH = 32


class AuthConfigError(Exception):
    """认证配置缺失/弱：显式失败，不静默放行也不用临时密钥。"""

    def __init__(self, message: str) -> None:
        self.code = "auth_not_configured"
        super().__init__(message)


class AuthError(Exception):
    """凭证/令牌不合法（映射 401）。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _env() -> dict:
    return os.environ


def auth_enabled(environ: dict | None = None) -> bool:
    env = environ if environ is not None else _env()
    return (env.get("AUTH_ENABLED") or "false").strip().lower() == "true"


def _require_secret(environ: dict) -> str:
    secret = (environ.get("AUTH_SECRET_KEY") or "").strip()
    if len(secret) < MIN_SECRET_LENGTH:
        raise AuthConfigError(f"AUTH_SECRET_KEY 缺失或弱于 {MIN_SECRET_LENGTH} 字符；拒绝启用认证（不回退匿名）")
    return secret


def issue_token(username: str, password: str, *, environ: dict | None = None) -> tuple[str, int]:
    """验证 bootstrap 账号并签发 JWT。返回 (token, expires_in)。"""
    env = environ if environ is not None else _env()
    secret = _require_secret(env)
    expected_user = (env.get("AUTH_BOOTSTRAP_USER") or "").strip()
    expected_pass = (env.get("AUTH_BOOTSTRAP_PASSWORD") or "").strip()
    if not expected_user or not expected_pass:
        raise AuthConfigError("AUTH_BOOTSTRAP_USER/AUTH_BOOTSTRAP_PASSWORD 未配置；拒绝签发 token")
    user_ok = hmac.compare_digest(username.encode("utf-8"), expected_user.encode("utf-8"))
    pass_ok = hmac.compare_digest(password.encode("utf-8"), expected_pass.encode("utf-8"))
    if not (user_ok and pass_ok):
        raise AuthError("invalid_credentials", "用户名或口令错误")
    ttl = int((env.get("AUTH_TOKEN_TTL_SECONDS") or "3600").strip() or 3600)
    now = int(time.time())
    token = pyjwt.encode({"sub": expected_user, "iat": now, "exp": now + ttl}, secret, algorithm=ALGORITHM)
    return token, ttl


def verify_token(token: str, *, environ: dict | None = None) -> dict:
    """校验 Bearer token（严格 HS256），返回 claims。"""
    env = environ if environ is not None else _env()
    secret = _require_secret(env)
    try:
        claims = pyjwt.decode(token, secret, algorithms=[ALGORITHM])
    except pyjwt.ExpiredSignatureError as exc:
        raise AuthError("token_expired", "token 已过期") from exc
    except pyjwt.InvalidTokenError as exc:
        raise AuthError("token_invalid", "token 非法") from exc
    return dict(claims)
