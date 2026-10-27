"""Runtime configuration, loaded only from environment variables."""

from __future__ import annotations

import logging
import re
from functools import cached_property
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from tunnelgate.passwords import is_valid_hash
from tunnelgate.validation import normalize_hostname

log = logging.getLogger(__name__)
AuthMode = Literal["oidc", "password"]
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

    oidc_issuer: AnyHttpUrl | None = None
    oidc_client_id: str | None = Field(default=None, min_length=1, max_length=255)
    oidc_client_secret: SecretStr | None = None
    oidc_require_mfa: bool = True
    basic_auth_username: str | None = None
    basic_auth_password: SecretStr | None = None
    basic_auth_password_hash: SecretStr | None = None
    app_url: AnyHttpUrl
    allowed_groups: Annotated[list[str], NoDecode] = Field(default_factory=list)
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
        for group in value:
            if not _GROUP_RE.fullmatch(group):
                raise ValueError(f"invalid group name: {group!r}")
        return value

    @field_validator("basic_auth_username")
    @classmethod
    def _username_valid(cls, value: str | None) -> str | None:
        if value is not None and not _GROUP_RE.fullmatch(value):
            raise ValueError("invalid BASIC_AUTH_USERNAME")
        return value

    @field_validator("basic_auth_password_hash")
    @classmethod
    def _hash_valid(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not is_valid_hash(value.get_secret_value()):
            raise ValueError(
                "BASIC_AUTH_PASSWORD_HASH is not a hash from 'tunnelgate hash-password'"
            )
        return value

    @field_validator("basic_auth_password")
    @classmethod
    def _password_valid(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value():
            raise ValueError("BASIC_AUTH_PASSWORD must not be empty")
        return value

    @model_validator(mode="after")
    def _auth_mode(self) -> Settings:
        oidc_vars = (self.oidc_issuer, self.oidc_client_id, self.oidc_client_secret)
        oidc_any = any(v is not None for v in oidc_vars)
        basic_secret = self.basic_auth_password_hash or self.basic_auth_password
        basic_any = self.basic_auth_username is not None or basic_secret is not None
        if oidc_any and (not all(v is not None for v in oidc_vars) or not self.allowed_groups):
            raise ValueError(
                "OIDC needs OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET and ALLOWED_GROUPS"
            )
        if not oidc_any:
            if not basic_any:
                raise ValueError(
                    "configure OIDC (OIDC_ISSUER, ...) or BASIC_AUTH_USERNAME and a password"
                )
            if self.basic_auth_username is None or basic_secret is None:
                raise ValueError(
                    "password login needs BASIC_AUTH_USERNAME and "
                    "BASIC_AUTH_PASSWORD_HASH or BASIC_AUTH_PASSWORD"
                )
        elif basic_any:
            log.error("both OIDC and BASIC_AUTH_* are set; using OIDC and ignoring BASIC_AUTH_*")
        if not oidc_any and self.basic_auth_password_hash and self.basic_auth_password:
            log.error(
                "both BASIC_AUTH_PASSWORD_HASH and BASIC_AUTH_PASSWORD are set; using the hash"
            )
        return self

    @model_validator(mode="after")
    def _https_only(self) -> Settings:
        for name in ("oidc_issuer", "app_url"):
            url = getattr(self, name)
            if url is not None and url.scheme != "https" and not self.allow_insecure_http:
                raise ValueError(f"{name.upper()} must use https")
        if urlsplit(str(self.app_url)).path not in ("", "/"):
            raise ValueError("APP_URL must not contain a path")
        return self

    @property
    def auth_mode(self) -> AuthMode:
        return "oidc" if self.oidc_issuer is not None else "password"

    @property
    def password_check(self) -> tuple[Literal["hash", "plain"], str]:
        """The configured password secret, preferring the hash."""
        if self.basic_auth_password_hash is not None:
            return "hash", self.basic_auth_password_hash.get_secret_value()
        if self.basic_auth_password is None:
            raise RuntimeError("password login is not configured")
        return "plain", self.basic_auth_password.get_secret_value()

    @cached_property
    def app_origin(self) -> str:
        parts = urlsplit(str(self.app_url))
        return f"{parts.scheme}://{parts.netloc}"

    @cached_property
    def app_host(self) -> str:
        return urlsplit(str(self.app_url)).hostname or ""

    @cached_property
    def issuer(self) -> str:
        return "" if self.oidc_issuer is None else str(self.oidc_issuer).rstrip("/")

    @cached_property
    def issuer_origin(self) -> str:
        parts = urlsplit(self.issuer)
        return f"{parts.scheme}://{parts.netloc}" if self.issuer else ""

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
