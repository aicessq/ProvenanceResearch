"""problem+json 错误（design.md §8）：/api/v1 错误统一 `application/problem+json`。

兼容期约束：非 /api/v1 路径保持既有错误形状不变
（HTTPException → {detail}，RequestValidationError → {detail:[...]}，
BaseAppError/未捕获 → {code,message,details}），旧接口回归不受影响。
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import BaseAppError
from app.schemas.response import error_response

PROBLEM_MEDIA_TYPE = "application/problem+json"

_TITLES = {
    400: "Bad Request",
    404: "Not Found",
    409: "Conflict",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def is_v1_path(request: Request) -> bool:
    return request.url.path.startswith("/api/v1")


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    detail: str,
    title: str | None = None,
) -> JSONResponse:
    payload = {
        "type": "about:blank",
        "title": title or _TITLES.get(status, "Error"),
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
        "code": code,
    }
    return JSONResponse(status_code=status, content=payload, media_type=PROBLEM_MEDIA_TYPE)


class V1Problem(Exception):
    """v1 路由显式抛出的业务错误。"""

    def __init__(self, *, status: int, code: str, detail: str, title: str | None = None) -> None:
        self.status = status
        self.code = code
        self.detail = detail
        self.title = title
        super().__init__(detail)


def install_error_handlers(app) -> None:
    """注册路径分支的异常处理器：/api/v1 → problem+json，其余保持旧形状。"""

    @app.exception_handler(V1Problem)
    async def _v1_problem(request: Request, exc: V1Problem):
        return problem_response(request, status=exc.status, code=exc.code, detail=exc.detail, title=exc.title)

    @app.exception_handler(HTTPException)
    async def _http_exception(request: Request, exc: HTTPException):
        if is_v1_path(request):
            return problem_response(
                request,
                status=exc.status_code,
                code="http_error",
                detail=str(exc.detail),
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        if is_v1_path(request):
            return problem_response(
                request,
                status=422,
                code="validation_error",
                detail=str(exc.errors())[:500],
            )
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})

    @app.exception_handler(BaseAppError)
    async def _app_error(request: Request, exc: BaseAppError):
        if is_v1_path(request):
            return problem_response(
                request,
                status=exc.status_code,
                code=exc.code,
                detail=exc.message,
            )
        return JSONResponse(status_code=exc.status_code, content=error_response(exc.code, exc.message, exc.details))
