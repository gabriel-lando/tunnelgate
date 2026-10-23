"""JSON API consumed by the SPA."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import Response

from tunnelgate.auth import User, me_response, require_csrf, require_user
from tunnelgate.cloudflare import CloudflareError
from tunnelgate.schemas import (
    About,
    BlockRequest,
    CloneRequest,
    ConfirmRequest,
    Denied,
    Me,
    OperationResult,
    RemoveRequest,
    State,
)
from tunnelgate.service import TunnelService

TunnelId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
_ERRORS = {
    401: {"description": "Not signed in"},
    403: {"model": Denied, "description": "Signed in but not authorized, or CSRF failure"},
}


def _svc(request: Request) -> TunnelService:
    svc: TunnelService = request.app.state.service
    return svc


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api", responses=_ERRORS)  # type: ignore[arg-type]

    @router.get("/me", response_model=Me)
    async def me(request: Request) -> Response:
        return await me_response(request)

    @router.get("/state", response_model=State)
    async def state(
        request: Request,
        _: Annotated[User, Depends(require_user)],
        refresh: Annotated[bool, Query()] = False,
    ) -> State:
        return await _svc(request).state(force=refresh)

    @router.get("/about", response_model=About)
    async def about(request: Request, _: Annotated[User, Depends(require_user)]) -> About:
        settings = request.app.state.settings
        svc = _svc(request)
        try:
            token = await svc.cf.verify_token()
            st = await svc.state()
            return About(
                version=settings.version,
                commit=settings.commit,
                cloudflare_ok=True,
                token_status=str(token.get("status")),
                token_expires_on=token.get("expires_on"),
                zones=[z.name for z in st.zones],
            )
        except CloudflareError:
            return About(
                version=settings.version,
                commit=settings.commit,
                cloudflare_ok=False,
                token_status=None,
                token_expires_on=None,
                zones=[],
            )

    @router.post("/routes/block", response_model=OperationResult)
    async def block(
        request: Request, body: BlockRequest, user: Annotated[User, Depends(require_csrf)]
    ) -> OperationResult:
        svc = _svc(request)
        blocked = await svc.set_blocked(
            body.hostname, body.blocked, user.username, body.confirm_critical
        )
        return OperationResult(blocked=blocked, state=svc.cached_state())

    @router.post("/tunnels/{tunnel_id}/block-all", response_model=OperationResult)
    async def block_tunnel(
        request: Request,
        tunnel_id: TunnelId,
        body: ConfirmRequest,
        user: Annotated[User, Depends(require_csrf)],
    ) -> OperationResult:
        _confirmed(body)
        svc = _svc(request)
        res = await svc.block_tunnel(tunnel_id, user.username)
        return OperationResult(blocked=res.blocked, skipped=res.skipped, state=svc.cached_state())

    @router.post("/kill-all", response_model=OperationResult)
    async def kill_all(
        request: Request, body: ConfirmRequest, user: Annotated[User, Depends(require_csrf)]
    ) -> OperationResult:
        _confirmed(body)
        svc = _svc(request)
        res = await svc.kill_all(user.username)
        return OperationResult(blocked=res.blocked, skipped=res.skipped, state=svc.cached_state())

    @router.post("/tunnels/{tunnel_id}/routes/clone", response_model=OperationResult)
    async def clone(
        request: Request,
        tunnel_id: TunnelId,
        body: CloneRequest,
        user: Annotated[User, Depends(require_csrf)],
    ) -> OperationResult:
        host = await _svc(request).clone_route(tunnel_id, body, user.username)
        return OperationResult(message=host)

    @router.post("/tunnels/{tunnel_id}/routes/remove", response_model=OperationResult)
    async def remove(
        request: Request,
        tunnel_id: TunnelId,
        body: RemoveRequest,
        user: Annotated[User, Depends(require_csrf)],
    ) -> OperationResult:
        await _svc(request).remove_route(
            tunnel_id, body.hostname, body.path, body.confirm, user.username
        )
        return OperationResult()

    @router.post("/tunnels/{tunnel_id}/undo", response_model=OperationResult)
    async def undo(
        request: Request,
        tunnel_id: TunnelId,
        body: ConfirmRequest,
        user: Annotated[User, Depends(require_csrf)],
    ) -> OperationResult:
        _confirmed(body)
        await _svc(request).undo(tunnel_id, user.username)
        return OperationResult()

    return router


def _confirmed(body: ConfirmRequest) -> None:
    if not body.confirm:
        raise HTTPException(status_code=409, detail="confirmation required")
