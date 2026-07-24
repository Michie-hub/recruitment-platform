"""
Application entrypoint. Creates and configures the FastAPI app instance.

Kept deliberately thin: no business logic lives here. This file wires
together config, logging, and (in later milestones) routers/middleware.
"""

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.middleware.security_headers import SecurityHeadersMiddleware
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.candidates import router as candidates_router
from app.api.v1.routes.jobs import router as jobs_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.rate_limit import limiter
from app.core.exceptions import register_exception_handlers

configure_logging()
logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Application factory — makes it possible to spin up multiple app instances for testing."""
    app = FastAPI(
        title="Enterprise AI Recruitment Platform",
        version="0.1.0",
        description="AI-powered recruitment platform API",
    )
    
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    app.include_router(auth_router)
    app.include_router(jobs_router)
    app.include_router(candidates_router)
    
    app.add_middleware(SecurityHeadersMiddleware)
    register_exception_handlers(app)
    
    @app.get("/health", tags=["system"])
    def health_check() -> dict[str, str]:
        """Liveness/readiness probe used by Docker healthchecks and load balancers."""
        return {"status": "ok", "environment": settings.environment}

    logger.info("Application startup complete | environment=%s", settings.environment)
    return app


app = create_app()
