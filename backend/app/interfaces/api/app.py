"""FastAPI application factory with startup validation."""

from __future__ import annotations

import logging
import os
import sys

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings
from app.infrastructure.persistence.database import db_manager
from app.interfaces.api.routes.artifacts import router as artifacts_router
from app.interfaces.api.routes.conversations import router as conversations_router
from app.interfaces.api.routes.health import router as health_router
from app.interfaces.api.routes.intent import router as intent_router
from app.interfaces.api.routes.projects import router as projects_router
from app.interfaces.api.routes.reports import router as reports_router
from app.interfaces.api.routes.tasks import router as tasks_router
from app.interfaces.api.routes.traces import router as traces_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> None:
    """Application lifespan — startup & shutdown."""
    # ── Startup ──

    # Validate LLM configuration with prominent warnings
    llm_warnings = settings.validate_llm_config()
    if llm_warnings:
        banner = "=" * 60
        print(f"\n{banner}", file=sys.stderr)
        print("⚠️  LLM CONFIGURATION WARNING", file=sys.stderr)
        print(banner, file=sys.stderr)
        for msg in llm_warnings:
            print(f"  🔶 {msg}", file=sys.stderr)
            logger.warning("🔶 %s", msg)
        print(banner, file=sys.stderr)
        print("  💡 所有 LLM 调用将回退到 Mock 模式，生成随机数据！", file=sys.stderr)
        print(f"{banner}\n", file=sys.stderr)

    # Database
    await db_manager.initialize()

    logger.info(
        "🚀 %s v%s started (env=%s, llm=%s, mock=%s)",
        settings.app_name, "0.1.0",
        settings.app_env.value,
        settings.llm_provider.value,
        not bool(settings.effective_api_key),
    )

    yield

    # ── Shutdown ──
    await db_manager.dispose()
    logger.info("🛑 Server shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="AI Competitive Analysis Assistant Backend",
        lifespan=lifespan,
    )

    # CORS — 从环境变量读取前端地址，开发环境默认 localhost:3000
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(health_router, prefix="/api")
    app.include_router(intent_router, prefix="/api")
    app.include_router(projects_router, prefix="/api")
    app.include_router(conversations_router, prefix="/api")
    app.include_router(artifacts_router, prefix="/api")
    app.include_router(reports_router, prefix="/api")
    app.include_router(tasks_router, prefix="/api")
    app.include_router(traces_router, prefix="/api")

    return app
