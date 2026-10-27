"""Strict validation for every value that reaches the Cloudflare API."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
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
_METADATA_NAMES = frozenset({"metadata", "metadata.google.internal"})
_METADATA_IPS = frozenset(
    ipaddress.ip_address(a) for a in ("fd00:ec2::254", "100.100.100.200", "168.63.129.16")
)
# Hosts some resolvers read as IPv4 in non-canonical form (127.1, 0x7f000001, 2130706433).
_NUMERIC_LABEL = r"(?:0x[0-9a-f]*|[0-9]+)"
_NUMERIC_HOST_RE = re.compile(rf"^{_NUMERIC_LABEL}(?:\.{_NUMERIC_LABEL})*$")
_IP_PATTERN_RE = re.compile(r"^(?=.*[0-9])[0-9.*?]+$")


def _compile_allow(pattern: str) -> re.Pattern[str]:
    """Compile a SERVICE_ALLOWLIST entry; wildcards never cross a dot or a colon.

    A leading "*." matches one or more labels. Patterns made only of digits, dots and
    wildcards are IPv4 patterns and match IPv4 literals only.
    """
    if pattern == "*":
        return re.compile(r"^.*$")
    host, _, port = pattern.partition(":")
    ip_like = bool(_IP_PATTERN_RE.fullmatch(host))
    star, one = (r"[0-9]{1,3}", r"[0-9]") if ip_like else (r"[a-z0-9-]*", r"[a-z0-9-]")
    regex = ""
    if host.startswith("*.") and not ip_like:
        regex, host = r"(?:[a-z0-9-]+\.)+", host[2:]
    for ch in host:
        regex += star if ch == "*" else one if ch == "?" else re.escape(ch)
    if port:
        regex += ":" + "".join(r"[0-9]+" if c == "*" else re.escape(c) for c in port)
    else:
        regex += r"(?::[0-9]+)?"
    return re.compile(f"^{regex}$")


def _is_ipv4(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).version == 4
    except ValueError:
        return False


@dataclass(frozen=True)
class ServicePolicy:
    """Where cloned routes may send traffic.

    The service is resolved by cloudflared, not by Tunnelgate, so names cannot be judged
    here; the allowlist is the real control. Loopback, link-local/metadata addresses, the
    app itself and the identity provider are always refused.
    """

    forbidden_hosts: frozenset[str] = frozenset()
    allowlist: tuple[str, ...] = ()
    _compiled: tuple[tuple[re.Pattern[str], bool], ...] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        compiled = tuple(
            (_compile_allow(p), bool(_IP_PATTERN_RE.fullmatch(p.partition(":")[0])))
            for p in self.allowlist
        )
        object.__setattr__(self, "_compiled", compiled)

    def check_host(self, host: str) -> str:
        """Refuse loopback, link-local, metadata, ambiguous numeric hosts and our own hosts."""
        host = host.lower().rstrip(".")
        if (
            host in _LOOPBACK_NAMES
            or host.endswith(".localhost")
            or host in _METADATA_NAMES
            or host in self.forbidden_hosts
        ):
            raise ValidationError(f"service host {host!r} is not allowed")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            if _NUMERIC_HOST_RE.fullmatch(host):
                raise ValidationError(f"service host {host!r} is ambiguous") from None
            return host
        mapped = getattr(ip, "ipv4_mapped", None) or ip
        if (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_unspecified
            or ip.is_multicast
            or ip in _METADATA_IPS
            or mapped in _METADATA_IPS
        ):
            raise ValidationError(f"service address {host} is not allowed")
        return host

    def check(self, service: str) -> str:
        parts = urlsplit(service)
        host = self.check_host(parts.hostname or "")
        if self._compiled:
            target = f"{host}:{parts.port}" if parts.port else host
            if not any(
                rx.fullmatch(target) and (not ip_pattern or _is_ipv4(host))
                for rx, ip_pattern in self._compiled
            ):
                raise ValidationError(f"service host {target} is not in SERVICE_ALLOWLIST")
        return service
