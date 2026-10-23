"""Origin checks, security headers and request size limits."""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 64 * 1024
_INLINE_SCRIPT_RE = re.compile(
    r"<script(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)


def require_same_origin(request: Request) -> None:
    """Reject state-changing requests that do not come from the app's own origin."""
    expected: str = request.app.state.settings.app_origin
    origin = request.headers.get("origin")
    if origin is not None:
        if origin != expected:
            raise HTTPException(status_code=403, detail="cross-origin request rejected")
        return
    referer = request.headers.get("referer")
    if referer:
        parts = urlsplit(referer)
        if f"{parts.scheme}://{parts.netloc}" == expected:
            return
    raise HTTPException(status_code=403, detail="missing Origin header")


def inline_script_hashes(static_dir: Path) -> list[str]:
    """Hash inline scripts of the built SPA so CSP can allow exactly those."""
    hashes: set[str] = set()
    if static_dir.is_dir():
        for html in static_dir.rglob("*.html"):
            for body in _INLINE_SCRIPT_RE.findall(html.read_text(encoding="utf-8")):
                digest = hashlib.sha256(body.encode("utf-8")).digest()
                hashes.add(f"'sha256-{base64.b64encode(digest).decode()}'")
    return sorted(hashes)


def build_csp(script_hashes: list[str], form_targets: list[str] | None = None) -> str:
    scripts = " ".join(["'self'", *script_hashes])
    forms = " ".join(["'self'", *(form_targets or [])])
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src {scripts}",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "manifest-src 'self'",
            "worker-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
            f"form-action {forms}",
        ]
    )


class SecurityMiddleware:
    """Adds hardening headers to every response and caps request bodies."""

    def __init__(self, app: ASGIApp, csp: str, hsts: bool) -> None:
        self.app = app
        headers = [
            (b"content-security-policy", csp.encode()),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"same-origin"),
            (b"x-frame-options", b"DENY"),
            (b"cross-origin-opener-policy", b"same-origin"),
            (b"cross-origin-resource-policy", b"same-origin"),
            (
                b"permissions-policy",
                b"camera=(), microphone=(), geolocation=(), payment=(), usb=()",
            ),
        ]
        if hsts:
            headers.append((b"strict-transport-security", b"max-age=31536000"))
        self.headers = headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
            await _plain(send, 413, b"request body too large", self.headers)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    raise HTTPException(status_code=413, detail="request body too large")
            return message

        path: str = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in self.headers if k not in existing]
                if path.startswith(("/api/", "/auth/")) and b"cache-control" not in existing:
                    extra.append((b"cache-control", b"no-store"))
                message["headers"] = [*message.get("headers", []), *extra]
            await send(message)

        await self.app(scope, limited_receive, send_with_headers)


async def _plain(send: Send, status: int, body: bytes, headers: list[tuple[bytes, bytes]]) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"text/plain; charset=utf-8"), *headers],
        }
    )
    await send({"type": "http.response.body", "body": body})
