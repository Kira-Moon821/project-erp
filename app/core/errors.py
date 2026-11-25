"""类型化错误体系 + 全局异常处理。

客户端只会拿到规范化的错误结构，永远不会看到堆栈或数据库内部细节。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """业务异常基类：所有对外错误都走这里。"""

    code: str = "app_error"
    status_code: int = 400

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AuthError(AppError):
    code = "unauthorized"
    status_code = 401


class PermissionError_(AppError):
    code = "forbidden"
    status_code = 403


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404


class ConflictError(AppError):
    code = "conflict"
    status_code = 409


class BusinessRuleError(AppError):
    """业务规则不满足，例如库存不足、重复下单。"""

    code = "business_rule_violation"
    status_code = 422


class RateLimitError(AppError):
    code = "rate_limited"
    status_code = 429


class UpstreamError(AppError):
    code = "upstream_failed"
    status_code = 502


def _payload(code: str, message: str, request: Request, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": getattr(request.state, "request_id", None),
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):  # noqa: ANN202
        return JSONResponse(status_code=exc.status_code, content=_payload(exc.code, exc.message, request, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):  # noqa: ANN202
        return JSONResponse(
            status_code=422,
            content=_payload(
                "invalid_request",
                "请求参数校验失败",
                request,
                {"errors": [
                    {"loc": [str(x) for x in err.get("loc", [])], "msg": err.get("msg", ""), "type": err.get("type", "")}
                    for err in exc.errors()
                ]},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):  # noqa: ANN202
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(status_code=exc.status_code, content=_payload(code, str(exc.detail), request))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # noqa: ANN202
        # 内部细节只进日志，不回传客户端
        from app.core.logging import get_logger

        get_logger("app.error").exception("unhandled_exception", extra={"path": request.url.path})
        return JSONResponse(status_code=500, content=_payload("internal_error", "服务内部错误，请稍后重试", request))
