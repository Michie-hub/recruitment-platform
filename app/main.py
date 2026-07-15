"""
Application entrypoint. Creates and configures the FastAPI app instance.

Kept deliberately thin: no business logic lives here. This file wires
together config, logging, and (in later milestones) routers/middleware.
"""

from fastapi import FastAPI

from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.jobs import router as jobs_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Application factory — makes it possible to spin up multiple app instances for testing."""
    app = FastAPI(
        title="Enterprise AI Recruitment Platform",
        version="0.1.0",
        description="AI-powered recruitment platform API",
    )

    app.include_router(auth_router)
    app.include_router(jobs_router)

    @app.get("/health", tags=["system"])
    def health_check() -> dict[str, str]:
        """Liveness/readiness probe used by Docker healthchecks and load balancers."""
        return {"status": "ok", "environment": settings.environment}

    logger.info("Application startup complete | environment=%s", settings.environment)
    return app


app = create_app()
