# app/middleware/security_headers.py

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response



class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Injects standard security headers into every response.

    These headers instruct browsers on how to safely handle responses
    from this API — they do not change application behavior, only
    client-side (browser) enforcement.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src  'self'; frame-ancestors 'none'"
        )

        # Only advertise HSTS over actual HTTPS connections — sending it
        # over plain HTTP in local dev is harmless but meaningless, and
        # in production it should only apply once TLS is confirmed.
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response