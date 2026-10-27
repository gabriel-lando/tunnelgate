"""OIDC login (Authorization Code + PKCE) and session-based authorization."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import math
import secrets
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

import httpx
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from joserfc.errors import JoseError

from tunnelgate.config import Settings
from tunnelgate.passwords import verify_password, verify_plain
from tunnelgate.schemas import LoginRequest
from tunnelgate.security import require_same_origin
from tunnelgate.store import Store

log = logging.getLogger(__name__)

_POSSESSION_FACTORS = frozenset({"otp", "hwk", "swk", "pop", "sms", "sc"})
DeniedReason = Literal["group", "mfa"]


@dataclass(frozen=True)
class User:
    username: str
    name: str
    groups: list[str]
    csrf: str
    exp: float
    sid: str


def has_mfa(amr: object) -> bool:
    if not isinstance(amr, list):
        return False
    methods = {str(m) for m in amr}
    return "mfa" in methods or ("pwd" in methods and bool(methods & _POSSESSION_FACTORS))


def authorize(settings: Settings, groups: list[str], amr: object) -> DeniedReason | None:
    if not any(g.casefold() in settings.allowed_groups_folded for g in groups):
        return "group"
    if settings.oidc_require_mfa and not has_mfa(amr):
        return "mfa"
    return None


async def current_user(request: Request) -> User | None:
    """Return the signed-in user; the cookie must be signed, unexpired and still registered."""
    data = request.session.get("user")
    if not isinstance(data, dict):
        return None
    try:
        user = User(
            username=str(data["username"]),
            name=str(data["name"]),
            groups=[str(g) for g in data["groups"]],
            csrf=str(data["csrf"]),
            exp=float(data["exp"]),
            sid=str(data["sid"]),
        )
    except KeyError, TypeError, ValueError:
        request.session.clear()
        return None
    store: Store = request.app.state.store
    if user.exp <= time.time() or not await store.session_active(user.sid):
        request.session.clear()
        return None
    return user


async def require_user(request: Request) -> User:
    user = await current_user(request)
    if user is not None:
        return user
    denied = request.session.get("denied")
    if isinstance(denied, dict):
        raise HTTPException(status_code=403, detail="forbidden")
    raise HTTPException(status_code=401, detail="unauthenticated")


def require_csrf(request: Request, user: User = Depends(require_user)) -> User:
    require_same_origin(request)
    token = request.headers.get("x-csrf-token", "")
    if not token or not hmac.compare_digest(token, user.csrf):
        raise HTTPException(status_code=403, detail="invalid CSRF token")
    return user


def _error_page(title: str, message: str, status: int) -> HTMLResponse:
    body = (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title><body style='font-family:system-ui,sans-serif;"
        "max-width:32rem;margin:4rem auto;padding:0 1rem;line-height:1.5'>"
        f"<h1>{title}</h1><p>{message}</p><p><a href='/'>Back to Tunnelgate</a></p></body></html>"
    )
    return HTMLResponse(body, status_code=status)


async def _start_session(
    request: Request,
    store: Store,
    settings: Settings,
    *,
    username: str,
    name: str,
    groups: list[str],
) -> None:
    request.session.clear()
    sid = secrets.token_urlsafe(32)
    expires = time.time() + settings.session_max_age
    await store.create_session(sid, username, expires)
    request.session["user"] = {
        "username": username,
        "name": name,
        "groups": groups,
        "csrf": secrets.token_urlsafe(32),
        "exp": expires,
        "sid": sid,
    }
    await store.audit(username, "login", "tunnelgate", "ok")


async def _end_session(request: Request, store: Store) -> None:
    user = await current_user(request)
    if user is not None:
        await store.delete_session(user.sid)
        await store.audit(user.username, "logout", "tunnelgate", "ok")
    request.session.clear()


def build_router(settings: Settings, store: Store) -> APIRouter:
    if settings.auth_mode == "password":
        return _password_router(settings, store)
    return _oidc_router(settings, store)


class LoginThrottle:
    """Global backoff after repeated failures (one account, and no trustworthy client IP)."""

    free_failures = 5
    max_delay = 300.0

    def __init__(self) -> None:
        self.failures = 0
        self.not_before = 0.0

    def retry_after(self, now: float) -> int:
        return max(0, math.ceil(self.not_before - now))

    def failed(self, now: float) -> None:
        self.failures += 1
        if self.failures >= self.free_failures:
            delay = min(2.0 ** (self.failures - self.free_failures), self.max_delay)
            self.not_before = now + delay

    def succeeded(self) -> None:
        self.failures = 0
        self.not_before = 0.0


def check_credentials(settings: Settings, username: str, password: str) -> bool:
    """Constant-effort check: the password is verified even when the username is wrong."""
    expected_user = settings.basic_auth_username or ""
    user_ok = hmac.compare_digest(
        hashlib.sha256(username.encode()).digest(), hashlib.sha256(expected_user.encode()).digest()
    )
    kind, secret = settings.password_check
    password_ok = (
        verify_password(password, secret) if kind == "hash" else verify_plain(password, secret)
    )
    return user_ok and password_ok


def _password_router(settings: Settings, store: Store) -> APIRouter:
    router = APIRouter(prefix="/auth", include_in_schema=False)
    throttle = LoginThrottle()
    # One check at a time: bounds scrypt memory/CPU and makes the throttle race-free.
    lock = asyncio.Lock()

    @router.get("/login")
    async def login_page(request: Request) -> Response:
        target = "/" if await current_user(request) is not None else "/login"
        return RedirectResponse(target, status_code=303)

    @router.post("/login", dependencies=[Depends(require_same_origin)])
    async def login(request: Request, body: LoginRequest) -> Response:
        async with lock:
            wait = throttle.retry_after(time.monotonic())
            if wait:
                await store.audit(body.username, "login", "tunnelgate", "throttled")
                return JSONResponse(
                    {"detail": "too many attempts", "retry_after": wait},
                    status_code=429,
                    headers={"Retry-After": str(wait)},
                )
            ok = await asyncio.to_thread(check_credentials, settings, body.username, body.password)
            if ok:
                throttle.succeeded()
            else:
                throttle.failed(time.monotonic())
        if not ok:
            await store.audit(body.username, "login", "tunnelgate", "denied", reason="credentials")
            return JSONResponse({"detail": "invalid credentials"}, status_code=401)
        await _start_session(
            request, store, settings, username=body.username, name=body.username, groups=[]
        )
        return Response(status_code=204)

    @router.post("/logout", dependencies=[Depends(require_same_origin)])
    async def logout(request: Request) -> Response:
        then = request.query_params.get("then")
        await _end_session(request, store)
        return RedirectResponse("/login" if then == "login" else "/signed-out", status_code=303)

    return router


def _oidc_router(settings: Settings, store: Store) -> APIRouter:
    oauth = OAuth()
    oauth.register(
        "oidc",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret.get_secret_value()
        if settings.oidc_client_secret
        else None,
        server_metadata_url=f"{settings.issuer}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile email groups", "code_challenge_method": "S256"},
    )
    client: Any = oauth.create_client("oidc")
    router = APIRouter(prefix="/auth", include_in_schema=False)

    @router.get("/login")
    async def login(request: Request) -> Response:
        if await current_user(request) is not None:
            return RedirectResponse("/", status_code=303)
        request.session.pop("denied", None)
        try:
            response: Response = await client.authorize_redirect(
                request, settings.redirect_uri, max_age=settings.session_max_age
            )
        except (OAuthError, httpx.HTTPError, ValueError) as exc:
            log.warning("identity provider unavailable: %s", type(exc).__name__)
            return _error_page(
                "Sign-in unavailable",
                "The identity provider could not be reached. Use the break-glass CLI if needed.",
                503,
            )
        return response

    @router.get("/callback")
    async def callback(request: Request) -> Response:
        try:
            metadata = await client.load_server_metadata()
            if str(metadata.get("issuer", "")).rstrip("/") != settings.issuer:
                raise OAuthError(error="issuer_mismatch", description="discovery issuer mismatch")
            token = await client.authorize_access_token(request)
            claims = token.get("userinfo") or {}
            if str(claims.get("iss", "")).rstrip("/") != settings.issuer:
                raise OAuthError(error="invalid_iss", description="unexpected issuer")
            aud = claims.get("aud")
            auds = aud if isinstance(aud, list) else [aud]
            if settings.oidc_client_id not in auds:
                raise OAuthError(error="invalid_aud", description="unexpected audience")
            userinfo = await client.userinfo(token=token)
        except (OAuthError, JoseError, httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("login failed: %s", type(exc).__name__)
            request.session.clear()
            return _error_page(
                "Sign-in failed", "The sign-in could not be completed. Try again.", 400
            )

        if userinfo.get("sub") != claims.get("sub"):
            request.session.clear()
            return _error_page("Sign-in failed", "Identity provider returned mismatched data.", 400)
        auth_time = claims.get("auth_time")
        if (
            isinstance(auth_time, (int, float))
            and time.time() - auth_time > settings.session_max_age
        ):
            request.session.clear()
            return _error_page(
                "Sign-in failed", "Please sign in again at the identity provider.", 400
            )

        username = str(
            claims.get("preferred_username")
            or userinfo.get("preferred_username")
            or claims.get("sub")
        )[:128]
        name = str(userinfo.get("name") or claims.get("name") or username)[:128]
        raw_groups = userinfo.get("groups", claims.get("groups")) or []
        groups = [str(g)[:128] for g in raw_groups][:200] if isinstance(raw_groups, list) else []
        reason = authorize(settings, groups, claims.get("amr", userinfo.get("amr")))

        if reason is not None:
            request.session.clear()
            request.session["denied"] = {"username": username, "reason": reason}
            await store.audit(
                username, "login", "tunnelgate", "denied", reason=reason, groups=groups
            )
            return RedirectResponse("/denied", status_code=303)

        await _start_session(request, store, settings, username=username, name=name, groups=groups)
        return RedirectResponse("/", status_code=303)

    @router.post("/logout")
    async def logout(request: Request) -> Response:
        require_same_origin(request)
        then = "login" if request.query_params.get("then") == "login" else "signed-out"
        await _end_session(request, store)
        back = f"{settings.app_origin}/" if then == "login" else f"{settings.app_origin}/signed-out"
        try:
            metadata = await client.load_server_metadata()
            end_session = metadata.get("end_session_endpoint")
        except OAuthError, httpx.HTTPError, ValueError:
            end_session = None
        if isinstance(end_session, str) and _same_origin(end_session, settings.issuer_origin):
            query = urlencode(
                {"client_id": settings.oidc_client_id, "post_logout_redirect_uri": back}
            )
            target = f"{end_session}?{query}"
        else:
            target = f"{settings.issuer}/logout?{urlencode({'rd': back})}"
        return RedirectResponse(target, status_code=303)

    return router


def _same_origin(url: str, origin: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and f"{parts.scheme}://{parts.netloc}" == origin


async def me_response(request: Request) -> Response:
    """Shape /api/me so the SPA can tell 'sign in' (401) from 'not allowed' (403)."""
    user = await current_user(request)
    if user is not None:
        return JSONResponse(
            {
                "username": user.username,
                "name": user.name,
                "groups": user.groups,
                "csrf_token": user.csrf,
                "expires_at": user.exp,
            }
        )
    denied = request.session.get("denied")
    if isinstance(denied, dict) and denied.get("reason") in ("group", "mfa"):
        return JSONResponse(
            {
                "error": "forbidden",
                "reason": denied["reason"],
                "username": str(denied.get("username")),
            },
            status_code=403,
        )
    mode = request.app.state.settings.auth_mode
    return JSONResponse({"error": "unauthenticated", "auth": mode}, status_code=401)
