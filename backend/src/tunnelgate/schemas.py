"""API request and response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TunnelStatus = Literal["healthy", "degraded", "down", "inactive", "unknown"]
BlockDisabledReason = Literal["no_zone_access"]
OriginValue = bool | int | str | None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Route(BaseModel):
    hostname: str
    service: str | None
    path: str | None
    zone: str | None
    blocked: bool
    wildcard: bool
    critical: bool
    managed: bool = Field(description="Rule lives in a remotely managed ingress config")
    can_block: bool
    block_disabled_reason: BlockDisabledReason | None
    origin_request: dict[str, OriginValue | list[str] | dict[str, object]] = Field(
        default_factory=dict
    )


class Tunnel(BaseModel):
    id: str
    name: str
    status: TunnelStatus
    connections: int
    remote_managed: bool
    can_undo: bool
    routes: list[Route]


class Zone(BaseModel):
    id: str
    name: str


class State(BaseModel):
    tunnels: list[Tunnel]
    zones: list[Zone]
    generated_at: float


class Me(BaseModel):
    username: str
    name: str
    groups: list[str]
    csrf_token: str
    expires_at: float


class Denied(BaseModel):
    error: Literal["forbidden"] = "forbidden"
    reason: Literal["group", "mfa"]
    username: str


class About(BaseModel):
    version: str
    commit: str
    cloudflare_ok: bool
    token_status: str | None
    token_expires_on: str | None
    zones: list[str]


class BlockRequest(_Strict):
    hostname: str = Field(max_length=253)
    blocked: bool
    confirm_critical: bool = False


class ConfirmRequest(_Strict):
    confirm: bool = False


class CloneRequest(_Strict):
    source_hostname: str = Field(max_length=253)
    source_path: str | None = Field(default=None, max_length=256)
    subdomain: str = Field(min_length=1, max_length=200)
    zone_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    service: str = Field(min_length=1, max_length=2048)
    path: str | None = Field(default=None, max_length=256)
    origin_request: dict[str, OriginValue] = Field(default_factory=dict)
    create_blocked: bool = True


class RemoveRequest(_Strict):
    hostname: str = Field(max_length=253)
    path: str | None = Field(default=None, max_length=256)
    confirm: str = Field(max_length=253)


class OperationResult(BaseModel):
    ok: bool = True
    message: str = ""
    blocked: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(
        default_factory=list, description="Routes left open because they cannot be blocked"
    )
    state: State | None = Field(
        default=None, description="Updated state, when known without a new discovery"
    )


class PartialFailure(BaseModel):
    detail: str
    blocked: list[str]
    failed: list[str]
    skipped: list[str]
