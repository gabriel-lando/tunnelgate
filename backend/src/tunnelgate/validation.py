"""Strict validation for every value that reaches the Cloudflare API."""

from __future__ import annotations

import fnmatch
import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
_HOSTNAME_RE = re.compile(rf"^(?:{_LABEL}\.)+{_LABEL}$")
_WILDCARD_RE = re.compile(rf"^\*\.(?:{_LABEL}\.)+{_LABEL}$")
_SUBDOMAIN_RE = re.compile(rf"^(?:{_LABEL}\.)*{_LABEL}$")
_SERVICE_SCHEMES = frozenset({"http", "https", "tcp", "ssh", "rdp"})
_PRINTABLE_RE = re.compile(r"^[\x21-\x7e]+$")


class ValidationError(ValueError):
    """Raised when user or API supplied data fails validation."""


def is_hostname(value: str) -> bool:
    return len(value) <= 253 and bool(_HOSTNAME_RE.fullmatch(value))


def is_wildcard(value: str) -> bool:
    return len(value) <= 253 and bool(_WILDCARD_RE.fullmatch(value))


def normalize_hostname(value: str) -> str:
    """Lowercase and validate a plain (non-wildcard) hostname."""
    host = value.strip().lower().rstrip(".")
    if not is_hostname(host):
        raise ValidationError(f"invalid hostname: {value!r}")
    return host


def build_hostname(subdomain: str, zone: str) -> str:
    sub = subdomain.strip().lower().strip(".")
    if not _SUBDOMAIN_RE.fullmatch(sub):
        raise ValidationError("invalid subdomain")
    return normalize_hostname(f"{sub}.{zone}")


def hostname_in_zone(hostname: str, zone: str) -> bool:
    return hostname == zone or hostname.endswith(f".{zone}")


def zone_for(hostname: str, zones: dict[str, str]) -> str | None:
    """Return the zone name (longest suffix match) for a hostname."""
    host = hostname[2:] if hostname.startswith("*.") else hostname
    best: str | None = None
    for name in zones:
        if hostname_in_zone(host, name) and (best is None or len(name) > len(best)):
            best = name
    return best


def validate_service(value: str) -> str:
    """Accept only well-formed origin URLs for new ingress rules."""
    service = value.strip()
    if len(service) > 2048 or not _PRINTABLE_RE.fullmatch(service):
        raise ValidationError("invalid service URL")
    parts = urlsplit(service)
    if parts.scheme not in _SERVICE_SCHEMES:
        raise ValidationError("service scheme must be http, https, tcp, ssh or rdp")
    if not parts.hostname or parts.username or parts.password:
        raise ValidationError("service must have a host and no credentials")
    try:
        _ = parts.port
    except ValueError as exc:
        raise ValidationError("invalid service port") from exc
    if parts.scheme not in {"http", "https"} and (parts.path not in ("", "/") or parts.query):
        raise ValidationError("non-HTTP services cannot have a path")
    if parts.fragment:
        raise ValidationError("service must not contain a fragment")
    return service


def validate_path(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if len(value) > 256 or not _PRINTABLE_RE.fullmatch(value):
        raise ValidationError("invalid path")
    return value


def validate_optional_hostname(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    return normalize_hostname(value)


def normalize_route_hostname(value: str) -> str:
    """Normalize a plain or wildcard (*.example.com) route hostname."""
    host = value.strip().lower().rstrip(".")
    if is_wildcard(host):
        return host
    return normalize_hostname(host)


_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})


@dataclass(frozen=True)
class ServicePolicy:
    """Where cloned routes may send traffic.

    The service is resolved by cloudflared, not by Tunnelgate, so names cannot be judged
    here; the allowlist is the real control. Loopback, link-local/metadata addresses, the
    app itself and the identity provider are always refused.
    """

    forbidden_hosts: frozenset[str] = frozenset()
    allowlist: tuple[str, ...] = ()

    def check(self, service: str) -> str:
        parts = urlsplit(service)
        host = (parts.hostname or "").lower().rstrip(".")
        if host in _LOOPBACK_NAMES or host in self.forbidden_hosts:
            raise ValidationError(f"service host {host!r} is not allowed")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and (
            ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast
        ):
            raise ValidationError(f"service address {host} is not allowed")
        if self.allowlist:
            target = f"{host}:{parts.port}" if parts.port else host
            if not any(
                fnmatch.fnmatchcase(target, p) or fnmatch.fnmatchcase(host, p)
                for p in self.allowlist
            ):
                raise ValidationError(f"service host {target} is not in SERVICE_ALLOWLIST")
        return service
