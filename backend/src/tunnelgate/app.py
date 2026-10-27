"""FastAPI application factory."""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from tunnelgate import api, auth
from tunnelgate.cloudflare import CloudflareClient, CloudflareError
from tunnelgate.config import Settings
from tunnelgate.locks import LockManager
from tunnelgate.security import SecurityMiddleware, build_csp, inline_script_hashes
from tunnelgate.service import (
    ConfirmationRequiredError,
    ConflictError,
    NotFoundError,
    PartialBlockError,
    TunnelService,
)
from tunnelgate.store import Store
from tunnelgate.validation import ServicePolicy, ValidationError
from tunnelgate.waf import WafError

log = logging.getLogger(__name__)
_SPA_FALLBACK = "200.html"


class SPAStaticFiles(StaticFiles):
    """Serve the built SPA; unknown client routes get the fallback shell."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path.startswith(("api/", "auth/")) or path in ("api", "auth"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        try:
            response = await super().get_response(path, scope)
        except Exception as exc:
            if getattr(exc, "status_code", None) != 404:
                raise
            response = await super().get_response(_SPA_FALLBACK, scope)
        if response.status_code == 404:
            response = await super().get_response(_SPA_FALLBACK, scope)
        if path.startswith("_app/immutable/"):
            response.headers["cache-control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["cache-control"] = "no-cache"
        return response


def _session_secret(settings: Settings) -> str:
    if settings.session_secret is not None:
        log.warning("SESSION_SECRET is set: fixed secret in use; recommended for development only")
        return settings.session_secret.get_secret_value()
    return secrets.token_urlsafe(48)


def create_app(
    settings: Settings | None = None,
    cf_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.data_dir)
    cf = CloudflareClient(
        settings.cf_api_token.get_secret_value(),
        settings.cf_account_id,
        settings.cf_api_base,
        transport=cf_transport,
    )
    policy = ServicePolicy(
        forbidden_hosts=frozenset({settings.app_host, settings.issuer_host} - {""}),
        allowlist=tuple(settings.service_allowlist),
    )
    if not settings.service_allowlist:
        log.warning(
            "SERVICE_ALLOWLIST is empty: cloned routes may point at any host cloudflared can reach"
        )
    service = TunnelService(
        cf, store, settings.critical_hostnames, LockManager(settings.data_dir), policy
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await cf.aclose()
        store.close()

    app = FastAPI(
        title="Tunnelgate",
        version=settings.version,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.service = service
    app.state.store = store

    app.include_router(auth.build_router(settings, store))
    app.include_router(api.build_router())

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(ValidationError)
    async def _validation(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(p) for p in e.get("loc", ())[1:]) for e in exc.errors()]
        return JSONResponse({"detail": "invalid request", "fields": fields}, status_code=422)

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ConflictError)
    async def _conflict(_: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ConfirmationRequiredError)
    async def _confirm(_: Request, exc: ConfirmationRequiredError) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "confirm": True}, status_code=409)

    @app.exception_handler(PartialBlockError)
    async def _partial(_: Request, exc: PartialBlockError) -> JSONResponse:
        return JSONResponse(
            {
                "detail": "some routes could not be blocked",
                "blocked": exc.blocked,
                "failed": exc.failed,
                "skipped": exc.skipped,
            },
            status_code=502,
        )

    @app.exception_handler(WafError)
    async def _waf(_: Request, exc: WafError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.exception_handler(CloudflareError)
    async def _cloudflare(_: Request, exc: CloudflareError) -> JSONResponse:
        return JSONResponse({"detail": f"Cloudflare API error: {exc.message}"}, status_code=502)

    static_dir = Path(settings.static_dir)
    if (static_dir / _SPA_FALLBACK).is_file():
        app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="spa")
    else:
        log.warning("no frontend build found at %s; serving API only", static_dir)

    hosts = [settings.app_host, "localhost", "127.0.0.1"]
    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret(settings),
        session_cookie="__Host-tunnelgate" if settings.secure_cookies else "tunnelgate",
        max_age=settings.session_max_age,
        path="/",
        same_site="lax",
        https_only=settings.secure_cookies,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    app.add_middleware(
        SecurityMiddleware,
        csp=build_csp(inline_script_hashes(static_dir), [o for o in [settings.issuer_origin] if o]),
        hsts=settings.secure_cookies,
    )
    return app


def openapi_schema() -> dict[str, object]:
    """OpenAPI document for the contract test; built without network or settings."""
    from fastapi.openapi.utils import get_openapi

    app = FastAPI(title="Tunnelgate", version="contract")
    app.include_router(api.build_router())
    return get_openapi(title=app.title, version=app.version, routes=app.routes)
