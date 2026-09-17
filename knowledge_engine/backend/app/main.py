"""FastAPI 应用入口。

设计说明（教学向）
==================

1. 为什么应用入口要尽量“薄”？
   规格 §3.2 要求“API 层不得写业务主逻辑”。main.py 只负责：
   - 创建 FastAPI 实例；
   - 配置日志；
   - 注册路由；
   - 注册全局异常处理（Phase 0 仅做最小兜底，统一错误响应在后续 Phase 完善）。
   真正的业务逻辑放在 services 层。

2. 为什么 /health 直接挂在根路径，而不是 /api/v1/health？
   规格 §17.1 明确为 `GET /health`（无前缀），常被容器编排直接探活，
   因此单独挂载在根路径。其余业务接口后续挂在 /api/v1 前缀下。

3. 启动方式：
   - 本地开发：uvicorn app.main:app --reload
   - Docker：容器内执行 uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import documents, eval, health, query, upload
from app.config import get_settings
from app.logging_config import setup_logging

# 在创建应用前完成日志初始化，保证后续 logger 输出格式一致
settings = get_settings()
setup_logging(debug=settings.debug)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    description="网络安全领域 RAG 知识库系统（当前已完成到 Phase 10：评测体系与量化指标接口）",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# FastAPI 0.139 当前环境下，先聚合 APIRouter 再 include 的写法会保留 _IncludedRouter，
# 没有在 app.routes 中展开成真实 APIRoute；因此这里显式逐个注册业务 router。
def _include_router_expanded(router, *, prefix: str = "") -> None:
    """兼容当前 FastAPI 版本，显式展开 APIRouter 中的 APIRoute。"""
    for route in router.routes:
        if not hasattr(route, "endpoint") or not hasattr(route, "methods"):
            continue
        app.add_api_route(
            f"{prefix}{route.path}",
            route.endpoint,
            methods=list(route.methods or []),
            response_model=getattr(route, "response_model", None),
            status_code=getattr(route, "status_code", None),
            tags=list(getattr(route, "tags", []) or []),
            dependencies=list(getattr(route, "dependencies", []) or []),
            summary=getattr(route, "summary", None),
            description=getattr(route, "description", None),
            response_description=getattr(route, "response_description", "Successful Response"),
            responses=getattr(route, "responses", None),
            deprecated=getattr(route, "deprecated", None),
            operation_id=getattr(route, "operation_id", None),
            name=getattr(route, "name", None),
            include_in_schema=getattr(route, "include_in_schema", True),
        )


_include_router_expanded(health.router, prefix="/api/v1")
_include_router_expanded(upload.router, prefix="/api/v1")
_include_router_expanded(documents.router, prefix="/api/v1")
_include_router_expanded(query.router, prefix="/api/v1")
_include_router_expanded(eval.router, prefix="/api/v1")


# ---- 根路径健康检查 ----
# 规格 §17.1 要求 GET /health 返回 {"status":"ok"}，挂在根路径
@app.get("/health")
def health_root() -> dict[str, str]:
    """根路径存活探针，与规格 §17.1 完全一致。"""
    return {"status": "ok"}


# ---- 全局异常兜底 ----
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """保持业务异常的标准顶层 ``error`` 响应信封。"""
    content = exc.detail
    if not (isinstance(content, dict) and "error" in content):
        content = {
            "error": {
                "code": "http_error",
                "message": str(content),
                "details": {},
            }
        }
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


# Phase 0 仅做最小统一兜底：未捕获的异常返回 internal_error，
# 避免把内部堆栈透出给用户（规格 §2.14 / §3.3）。
# 完整的统一错误响应体系在后续 Phase 落地。
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理的异常: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "服务器内部错误，请稍后重试",
                "details": {},
            }
        },
    )
