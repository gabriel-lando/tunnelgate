"""Runtime configuration, loaded only from environment variables."""

from __future__ import annotations

import re
from functools import cached_property
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from tunnelgate.validation import normalize_hostname

_ACCOUNT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_GROUP_RE = re.compile(r"^[\w .@\-]{1,128}$")


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class CloudflareSettings(BaseSettings):
    """Settings needed to talk to the Cloudflare API (server and CLI)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    cf_api_token: SecretStr
    cf_account_id: str
    cf_api_base: str = "https://api.cloudflare.com/client/v4"
    critical_hosts: Annotated[list[str], NoDecode] = Field(default_factory=list)
    data_dir: Path = Field(default=Path("/data"), alias="TUNNELGATE_DATA_DIR")

    @field_validator("cf_account_id")
    @classmethod
    def _account_id(cls, value: str) -> str:
        value = value.strip().lower()
        if not _ACCOUNT_ID_RE.fullmatch(value):
            raise ValueError("CF_ACCOUNT_ID must be a 32-character hex string")
        return value

    @field_validator("cf_api_base")
    @classmethod
    def _api_base(cls, value: str) -> str:
        if urlsplit(value).scheme != "https":
            raise ValueError("CF_API_BASE must use https")
        return value.rstrip("/")

    @field_validator("critical_hosts", mode="before")
    @classmethod
    def _critical(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("critical_hosts")
    @classmethod
    def _critical_valid(cls, value: list[str]) -> list[str]:
        return [normalize_hostname(h) for h in value]


class Settings(CloudflareSettings):
    """Full settings for the web server."""

    oidc_issuer: AnyHttpUrl
    oidc_client_id: str = Field(min_length=1, max_length=255)
    oidc_client_secret: SecretStr
    oidc_require_mfa: bool = True
    app_url: AnyHttpUrl
    allowed_groups: Annotated[list[str], NoDecode]
    service_allowlist: Annotated[list[str], NoDecode] = Field(default_factory=list)
    session_secret: SecretStr | None = None
    session_max_age: int = Field(default=8 * 3600, ge=300, le=7 * 24 * 3600)
    static_dir: Path = Field(default=Path("/app/static"), alias="TUNNELGATE_STATIC_DIR")
    version: str = Field(default="dev", alias="TUNNELGATE_VERSION")
    commit: str = Field(default="unknown", alias="TUNNELGATE_COMMIT")
    allow_insecure_http: bool = Field(default=False, alias="TUNNELGATE_ALLOW_INSECURE_HTTP")

    @field_validator("session_secret")
    @classmethod
    def _secret_length(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("SESSION_SECRET must be at least 32 characters")
        return value

    @field_validator("service_allowlist", mode="before")
    @classmethod
    def _allowlist(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("service_allowlist")
    @classmethod
    def _allowlist_valid(cls, value: list[str]) -> list[str]:
        for pattern in value:
            if not re.fullmatch(r"[a-z0-9.*?\-]+(:[0-9*]+)?", pattern.lower()):
                raise ValueError(f"invalid SERVICE_ALLOWLIST pattern: {pattern!r}")
        return [p.lower() for p in value]

    @field_validator("allowed_groups", mode="before")
    @classmethod
    def _groups(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("allowed_groups")
    @classmethod
    def _groups_valid(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("ALLOWED_GROUPS must list at least one group")
        for group in value:
            if not _GROUP_RE.fullmatch(group):
                raise ValueError(f"invalid group name: {group!r}")
        return value

    @model_validator(mode="after")
    def _https_only(self) -> Settings:
        for name in ("oidc_issuer", "app_url"):
            url = getattr(self, name)
            if url.scheme != "https" and not self.allow_insecure_http:
                raise ValueError(f"{name.upper()} must use https")
        if urlsplit(str(self.app_url)).path not in ("", "/"):
            raise ValueError("APP_URL must not contain a path")
        return self

    @cached_property
    def app_origin(self) -> str:
        parts = urlsplit(str(self.app_url))
        return f"{parts.scheme}://{parts.netloc}"

    @cached_property
    def app_host(self) -> str:
        return urlsplit(str(self.app_url)).hostname or ""

    @cached_property
    def issuer(self) -> str:
        return str(self.oidc_issuer).rstrip("/")

    @cached_property
    def issuer_origin(self) -> str:
        parts = urlsplit(self.issuer)
        return f"{parts.scheme}://{parts.netloc}"

    @cached_property
    def issuer_host(self) -> str:
        return urlsplit(self.issuer).hostname or ""

    @cached_property
    def redirect_uri(self) -> str:
        return f"{self.app_origin}/auth/callback"

    @cached_property
    def allowed_groups_folded(self) -> frozenset[str]:
        return frozenset(g.casefold() for g in self.allowed_groups)

    @cached_property
    def critical_hostnames(self) -> frozenset[str]:
        return frozenset({self.issuer_host, *self.critical_hosts} - {""})

    @property
    def secure_cookies(self) -> bool:
        return self.app_url.scheme == "https"
