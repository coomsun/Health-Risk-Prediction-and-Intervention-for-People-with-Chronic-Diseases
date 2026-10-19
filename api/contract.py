"""统一响应信封、错误码、异常处理器与耗时中间件。

信封结构（冻结契约，见 `_设计规格.md` 第 5 节）::

    {"code":0,"message":"ok","data":<payload>,"traceId":"<uuid>","timestamp":<ms>}

所有响应（含错误响应）都带 `X-Response-Time`（毫秒，保留两位小数）
与 `X-Trace-Id`（与信封 traceId 相同），便于前端与日志对账。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# ---------------------------------------------------------------- 错误码表
# 与 docs/接口文档.md「错误码表」一节严格一致。
CODE_OK = 0
CODE_INVALID_PARAM = 400
#: 鉴权失败（未带令牌 / 令牌无效 / 令牌过期）。
#: 不能复用 CODE_INVALID_PARAM，否则前端会把"缺少令牌"误解成"参数取值越界"。
CODE_UNAUTHORIZED = 401
CODE_NOT_FOUND = 404
CODE_METHOD_NOT_ALLOWED = 405
CODE_INTERNAL_ERROR = 500
CODE_MODEL_NOT_READY = 1001
CODE_PREDICT_FAILED = 1002
CODE_DB_UNAVAILABLE = 1003

ERROR_MESSAGES = {
    CODE_OK: "ok",
    CODE_INVALID_PARAM: "参数校验失败",
    CODE_UNAUTHORIZED: "鉴权失败",
    CODE_NOT_FOUND: "接口或资源不存在",
    CODE_METHOD_NOT_ALLOWED: "请求方法不被支持",
    CODE_INTERNAL_ERROR: "服务器内部错误",
    CODE_MODEL_NOT_READY: "模型未就绪",
    CODE_PREDICT_FAILED: "预测执行失败",
    CODE_DB_UNAVAILABLE: "数据库未就绪",
}


class ApiError(Exception):
    """业务异常：接口显式抛出，由统一处理器转换成信封响应。"""

    def __init__(
        self,
        code: int,
        message: str | None = None,
        http_status: int = 400,
        data: Any = None,
    ) -> None:
        self.code = code
        self.message = message or ERROR_MESSAGES.get(code, "未知错误")
        self.http_status = http_status
        self.data = data
        super().__init__(self.message)


def now_ms() -> int:
    """当前毫秒时间戳。"""
    return int(time.time() * 1000)


def envelope(
    data: Any = None,
    *,
    code: int = CODE_OK,
    message: str = "ok",
    trace_id: str | None = None,
) -> dict[str, Any]:
    """构造统一响应信封。"""
    return {
        "code": code,
        "message": message,
        "data": data,
        "traceId": trace_id or uuid.uuid4().hex,
        "timestamp": now_ms(),
    }


def trace_id_of(request: Request) -> str:
    """取当前请求的 traceId（由中间件写入 request.state）。"""
    trace_id = getattr(request.state, "trace_id", None)
    return trace_id or uuid.uuid4().hex


def ok(request: Request, data: Any) -> dict[str, Any]:
    """成功信封速写。"""
    return envelope(data, trace_id=trace_id_of(request))


def _error_response(request: Request, code: int, message: str, http_status: int, data: Any = None) -> JSONResponse:
    payload = envelope(data, code=code, message=message, trace_id=trace_id_of(request))
    headers = {"X-Trace-Id": payload["traceId"]}
    return JSONResponse(content=payload, status_code=http_status, headers=headers)


def _format_validation_error(exc: RequestValidationError) -> tuple[str, list[dict[str, Any]]]:
    """把 pydantic 校验错误整理成中文提示 + 结构化明细。"""
    details: list[dict[str, Any]] = []
    for item in exc.errors():
        loc = ".".join(str(part) for part in item.get("loc", ()) if part not in ("body", "query", "path"))
        details.append(
            {
                "loc": loc or "body",
                "msg": item.get("msg", ""),
                "type": item.get("type", ""),
            }
        )
    if not details:
        return "参数校验失败", details
    message = "参数校验失败：" + "；".join(f"{d['loc']} {d['msg']}" for d in details)
    return message, details


def install(app: FastAPI) -> None:
    """为 app 挂载耗时中间件与全部异常处理器（在创建 app 之后调用一次）。"""

    @app.middleware("http")
    async def response_time_middleware(request: Request, call_next):
        """为每个请求注入 traceId，并在响应头写入 X-Response-Time。"""
        request.state.trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - 兜底：任何未捕获异常也返回信封而不是裸 500
            elapsed_ms = (time.perf_counter() - start) * 1000
            payload = envelope(
                {"error": type(exc).__name__, "detail": str(exc)},
                code=CODE_INTERNAL_ERROR,
                message=f"{ERROR_MESSAGES[CODE_INTERNAL_ERROR]}：{type(exc).__name__}",
                trace_id=request.state.trace_id,
            )
            return JSONResponse(
                content=payload,
                status_code=500,
                headers={
                    "X-Response-Time": f"{elapsed_ms:.2f}",
                    "X-Trace-Id": request.state.trace_id,
                },
            )
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time"] = f"{elapsed_ms:.2f}"
        response.headers["X-Trace-Id"] = request.state.trace_id
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return _error_response(request, exc.code, exc.message, exc.http_status, exc.data)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        message, details = _format_validation_error(exc)
        return _error_response(request, CODE_INVALID_PARAM, message, 400, {"errors": details})

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = CODE_NOT_FOUND if exc.status_code == 404 else exc.status_code
        if code == CODE_NOT_FOUND:
            message = f"{ERROR_MESSAGES[CODE_NOT_FOUND]}：{request.url.path}"
        elif isinstance(exc.detail, str) and exc.detail:
            message = exc.detail
        else:
            message = ERROR_MESSAGES.get(code, "请求失败")
        return _error_response(request, code, message, exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(
            request,
            CODE_INTERNAL_ERROR,
            f"{ERROR_MESSAGES[CODE_INTERNAL_ERROR]}：{type(exc).__name__}",
            500,
            {"detail": str(exc)},
        )
