"""API 限流（硬化轮）：进程内固定窗口计数（query/ingest 分桶）。

单实例部署裁决（decisions 2026-10-10 多实例边界）——分布式限流/队列/Redis 锁是
明确非目标；进程重启窗口清零可接受。桶：`query`（提问类 POST）、`ingest`（配置/
入库写操作）、`default`（其余）。429 携带 Retry-After。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

DEFAULT_QUERY_PER_MINUTE = 20
DEFAULT_INGEST_PER_MINUTE = 10
DEFAULT_DEFAULT_PER_MINUTE = 120


@dataclass
class RateLimiter:
    enabled: bool = True
    limits_per_minute: dict[str, int] = field(
        default_factory=lambda: {
            "query": DEFAULT_QUERY_PER_MINUTE,
            "ingest": DEFAULT_INGEST_PER_MINUTE,
            "default": DEFAULT_DEFAULT_PER_MINUTE,
        }
    )
    clock: callable = time.monotonic
    _windows: dict[tuple[str, str], tuple[int, int]] = field(default_factory=dict)

    @classmethod
    def from_env(cls, environ: dict | None = None) -> "RateLimiter":
        env = environ if environ is not None else os.environ

        def limit(name: str, default: int) -> int:
            raw = (env.get(name) or "").strip()
            try:
                return int(raw) if raw else default
            except ValueError:
                return default

        return cls(
            enabled=(env.get("RATE_LIMIT_ENABLED") or "true").strip().lower() != "false",
            limits_per_minute={
                "query": limit("RATE_LIMIT_QUERY_PER_MINUTE", DEFAULT_QUERY_PER_MINUTE),
                "ingest": limit("RATE_LIMIT_INGEST_PER_MINUTE", DEFAULT_INGEST_PER_MINUTE),
                "default": limit("RATE_LIMIT_DEFAULT_PER_MINUTE", DEFAULT_DEFAULT_PER_MINUTE),
            },
        )

    def check(self, bucket: str, client_key: str) -> tuple[bool, int]:
        """返回 (allowed, retry_after_seconds)。"""
        if not self.enabled:
            return True, 0
        limit = self.limits_per_minute.get(bucket) or self.limits_per_minute["default"]
        now = int(self.clock() // 60)
        key = (bucket, client_key)
        window, count = self._windows.get(key, (now, 0))
        if window != now:
            window, count = now, 0
        count += 1
        self._windows[key] = (window, count)
        if count > limit:
            retry_after = 60 - int(self.clock() % 60)
            return False, max(1, retry_after)
        return True, 0


rate_limiter = RateLimiter.from_env()
