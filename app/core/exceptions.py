"""
Centralized error handling.

Why this exists: without it, unhandled exceptions (DB connection drops,
Redis timeouts, S3/MinIO failures, bugs) bubble up to FastAPI's default
handler, which in DEBUG-ish conditions can leak stack traces, file paths,
and internal exception messages to the client. That's an information
disclosure risk (attackers learn your stack, library versions, file
layout) and it's also just an inconsistent API contract — some errors
return {"detail": "..."} from FastAPI/Starlette defaults, others might
return something else entirely depending on where they were raised.

This module gives every error response the same shape:

    {"error": {"code": "...", "message": "..."}}

and guarantees raw exception internals never reach the client, while
still logging the full exception server-side for debugging.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """
    Base class for application-raised errors (as opposed to framework or
    library errors like SQLAlchemyError). Services/repositories should
    raise subclasses of this rather than generic Exception, so the error
    handler below can map them to the right status code deliberately
    instead of guessing.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "app_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFoundError(AppError):
    """Raise when a requested resource doesn't exist (job, candidate, etc.)."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class ConflictError(AppError):
    """Raise for state conflicts — e.g. duplicate email on registration."""

    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"


class ForbiddenError(AppError):
    """
    Raise for authorization failures that are more specific than the
    generic require_role() 403 — e.g. 'you don't own this job posting.'
    """

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "forbidden"


def _error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    """
    Call this once from create_app(). Registers all handlers in one place
    so main.py doesn't accumulate a growing pile of @app.exception_handler
    decorators mixed in with routing/middleware setup.
    """

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        # AppError subclasses are expected, "known" errors — log at info,
        # not error, since these aren't bugs, they're normal control flow
        # (e.g. a 404 for a job that was deleted is not a system failure).
        logger.info(
            "app_error | path=%s | code=%s | message=%s",
            request.url.path,
            exc.error_code,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.error_code, exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic validation errors include the field path and a message
        # per failing field. This is safe to return as-is — it describes
        # what's wrong with the CLIENT'S input, not internal system state
        # — so unlike the catch-all handler below, exposing detail here
        # is helpful, not a leak.
        logger.info(
            "validation_error | path=%s | errors=%s",
            request.url.path,
            exc.errors(),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_body(
                "validation_error",
                "Request validation failed. See 'fields' for details.",
            )
            | {"fields": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # Catches HTTPException raised anywhere (auth failures, explicit
        # aborts) that isn't one of our AppError subclasses, and normalizes
        # it to the same {"error": {...}} shape instead of Starlette's
        # default {"detail": "..."}.
        #
        # headers=exc.headers matters: FastAPI's own default handler
        # preserves any custom headers attached to an HTTPException (e.g.
        # the login route's headers={"WWW-Authenticate": "Bearer"} on a
        # 401). Building a JSONResponse from scratch without passing
        # exc.headers through silently drops them — caught by an
        # integration test asserting on the actual response headers,
        # which no unit or service-layer test could have seen, since
        # this only exists once the exception crosses the route boundary.
        logger.info(
            "http_exception | path=%s | status=%s | detail=%s",
            request.url.path,
            exc.status_code,
            exc.detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body("http_error", str(exc.detail)),
            headers=exc.headers,
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_db_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # Database errors (connection drops, constraint violations that
        # slipped past application-level checks, timeouts) are logged with
        # full detail server-side — exc_info=True captures the traceback —
        # but the client only ever sees a generic message. Returning the
        # real SQLAlchemy error message risks leaking table/column names,
        # query structure, or driver-level connection strings.
        logger.error(
            "database_error | path=%s | exc=%s",
            request.url.path,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_error_body(
                "service_unavailable",
                "A database error occurred. Please try again shortly.",
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # The final catch-all. Anything reaching here is, by definition,
        # a bug or an unanticipated failure (Redis down, MinIO unreachable,
        # a genuine code error) — nothing about it is safe to show the
        # client. Full traceback goes to the logs via exc_info=True; the
        # client gets a generic 500 with no exception message, no file
        # paths, no library names.
        logger.error(
            "unhandled_exception | path=%s | exc=%s",
            request.url.path,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(
                "internal_error",
                "An unexpected error occurred. Please try again later.",
            ),
        )
