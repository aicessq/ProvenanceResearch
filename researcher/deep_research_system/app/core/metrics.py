"""进程内指标（硬化轮）：Prometheus 文本格式暴露，零依赖。

指标：http_requests_total{status}、auth_failures_total、rate_limited_total、
task_terminal_total{status}。单实例内存计数（与单实例裁决一致）。
"""

from __future__ import annotations

import threading
from collections import Counter


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._http_requests: Counter[tuple[str]] = Counter()
        self._auth_failures = 0
        self._rate_limited = 0
        self._task_terminal: Counter[tuple[str]] = Counter()

    def inc_http(self, status: int) -> None:
        with self._lock:
            self._http_requests[(str(status),)] += 1

    def inc_auth_failure(self) -> None:
        with self._lock:
            self._auth_failures += 1

    def inc_rate_limited(self) -> None:
        with self._lock:
            self._rate_limited += 1

    def inc_task_terminal(self, status: str) -> None:
        with self._lock:
            self._task_terminal[(status,)] += 1

    def render(self) -> str:
        with self._lock:
            lines = [
                "# HELP http_requests_total HTTP requests by status",
                "# TYPE http_requests_total counter",
            ]
            for (status,), count in sorted(self._http_requests.items()):
                lines.append(f'http_requests_total{{status="{status}"}} {count}')
            lines += ["# HELP auth_failures_total Authentication failures", "# TYPE auth_failures_total counter"]
            lines.append(f"auth_failures_total {self._auth_failures}")
            lines += ["# HELP rate_limited_total Requests rejected by rate limiter", "# TYPE rate_limited_total counter"]
            lines.append(f"rate_limited_total {self._rate_limited}")
            lines += ["# HELP task_terminal_total Terminal task outcomes", "# TYPE task_terminal_total counter"]
            for (status,), count in sorted(self._task_terminal.items()):
                lines.append(f'task_terminal_total{{status="{status}"}} {count}')
            return "\n".join(lines) + "\n"


metrics = Metrics()


class MetricsMiddleware:
    """最小 ASGI 中间件：按状态码计数（放在 setup_middlewares 注册）。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status_holder = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            metrics.inc_http(status_holder["status"])
