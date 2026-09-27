"""Security headers, a request-size ceiling, and a leak-proof 500.

One ASGI-level middleware, deliberately boring:

- Every response gets the standard hardening headers. The CSP is strict
  because the built client needs nothing external: scripts and styles come
  from this origin, the API is same-origin, and images are local or data:
  URIs. `frame-ancestors` is the one knob you configure — it lists the sites
  allowed to embed the chat in an iframe (widget.js), and replaces the
  legacy X-Frame-Options.
- HSTS only when the request arrived over TLS (directly or via the proxy's
  X-Forwarded-Proto), so a plain-http dev server never pins itself.
- Bodies larger than MAX_BODY_BYTES are refused up front with a 413. The
  chat schema already caps turns and lengths; this stops a multi-megabyte
  body before pydantic ever parses it.
- Unhandled exceptions become the same generic JSON error the chat stream
  uses. Tracebacks go to the log, never to the visitor.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 256 * 1024

STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
}


def content_security_policy(frame_ancestors: str) -> str:
    return "; ".join(
        (
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "connect-src 'self'",
            "font-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            f"frame-ancestors {frame_ancestors}",
        )
    )


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, frame_ancestors: str) -> None:
        super().__init__(app)
        self._csp = content_security_policy(frame_ancestors)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            response: Response = JSONResponse(
                status_code=413, content={"error": "Request body too large."}
            )
        else:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception("Unhandled error on %s %s", request.method, request.url.path)
                response = JSONResponse(
                    status_code=500, content={"error": "Unexpected server error."}
                )
        response.headers.update(STATIC_HEADERS)
        response.headers["Content-Security-Policy"] = self._csp
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        if scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def install_security(app: FastAPI, frame_ancestors: str) -> None:
    app.add_middleware(SecurityMiddleware, frame_ancestors=frame_ancestors)
