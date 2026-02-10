"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import router
from .analytics import router as analytics_router
from .reviews import router as reviews_router
from .users import router as users_router
from .db import close_db, get_engine
from .logging_setup import setup_logging
from .settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    settings = get_settings()
    setup_logging(settings.log_level)

    logger.info(
        "service_starting",
        extra={
            "version": "1.0.0",
            "host": settings.host,
            "port": settings.port,
        },
    )

    # Initialize database connection pool
    _ = get_engine()

    yield

    # Cleanup
    await close_db()
    logger.info("service_stopped")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Ingest API",
        description="Audio chunk ingestion service for SalesControl",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware (disabled by default)
    if settings.cors_enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Custom exception handlers
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Return 422 with detailed validation errors."""
        logger.warning(
            "validation_error",
            extra={"errors": exc.errors(), "path": request.url.path},
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.errors()},
        )

    # Include API routes
    app.include_router(router)
    app.include_router(analytics_router)
    app.include_router(reviews_router)
    app.include_router(users_router)

    return app


def main() -> None:
    """Run the application."""
    settings = get_settings()
    setup_logging(settings.log_level)

    uvicorn.run(
        "ingest_api.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,  # We use structured logging instead
    )


if __name__ == "__main__":
    main()
