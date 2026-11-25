"""应用入口：中间件、错误处理、路由挂载、静态资源、优雅停机。"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.deps import check_rate_limit
from app.api.routes import auth, dashboard, erp
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import get_logger, new_request_id, request_id_var, setup_logging

settings = get_settings()
setup_logging(settings.log_level)
logger = get_logger("app.request")

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app_start", extra={"env": settings.environment, "db": settings.database_url.split("@")[-1]})
    yield
    logger.info("app_shutdown", extra={"note": "connections closed"})


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="工业零部件经销 ERP · 经营分析与 AI 洞察演示系统（数据为确定性模拟数据）",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,      # 显式来源，不用通配符
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

register_error_handlers(app)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """注入 request_id、结构化访问日志与限流。"""
    rid = request.headers.get("X-Request-ID") or new_request_id()
    request.state.request_id = rid
    token = request_id_var.set(rid)
    started = time.perf_counter()
    if request.url.path.startswith("/api"):
        check_rate_limit(request)      # 每 IP 每分钟限流，超限直接 429
    try:
        response = await call_next(request)
    except Exception:
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        logger.error("request_failed", extra={"path": request.url.path, "method": request.method,
                                              "elapsed_ms": elapsed})
        raise
    finally:
        request_id_var.reset(token)
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = rid
    if not request.url.path.startswith(("/assets", "/docs", "/openapi.json")):
        logger.info("request", extra={"path": request.url.path, "method": request.method,
                                       "status": response.status_code, "elapsed_ms": elapsed})
    return response


@app.get("/health", tags=["运维"], summary="存活探针")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@app.get("/ready", tags=["运维"], summary="就绪探针（校验数据库连通）")
def ready() -> JSONResponse:
    from app.db.session import get_engine

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return JSONResponse({"status": "ready", "database": "ok"})
    except Exception as exc:  # noqa: BLE001
        logger.error("readiness_failed", extra={"error": str(exc)[:200]})
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "error"})


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(dashboard.router, prefix=settings.api_prefix)
app.include_router(erp.router, prefix=settings.api_prefix)

WEB_DIR = ROOT / "web"
if WEB_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(str(WEB_DIR / "index.html"))
