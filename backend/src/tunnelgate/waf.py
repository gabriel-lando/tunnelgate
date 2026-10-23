"""Manage the single Tunnelgate block rule per zone."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from tunnelgate.cloudflare import JSON, CloudflareClient
from tunnelgate.locks import LockManager
from tunnelgate.validation import ValidationError, is_hostname, is_wildcard

log = logging.getLogger(__name__)

RULE_DESCRIPTION = "tunnelgate-managed"
_NOOP_HOST = "tunnelgate.invalid"
_IN_RE = re.compile(r"in \{([^}]*)\}")
_ENDS_RE = re.compile(r'ends_with\(lower\(http\.host\), "\.([^"\\]*)"\)')
_QUOTED_RE = re.compile(r'"([^"\\]*)"')
_MAX_EXPRESSION = 4096


class WafError(Exception):
    """The block rule could not be brought to the desired state."""


def build_expression(hosts: Iterable[str]) -> str:
    """Build the block expression. Every entry is validated, so quoting tricks are impossible.

    Plain hosts are matched exactly; wildcard routes (*.x.example.com) match any subdomain.
    The Host header is lowercased so case variations cannot slip past the rule.
    """
    clean = sorted(set(hosts))
    plain, suffixes = [], []
    for host in clean:
        if is_hostname(host):
            plain.append(host)
        elif is_wildcard(host):
            suffixes.append(host[2:])
        else:
            raise ValidationError(f"refusing to place invalid hostname in WAF rule: {host!r}")
    parts: list[str] = []
    if plain:
        parts.append("(lower(http.host) in {" + " ".join(f'"{h}"' for h in plain) + "})")
    parts.extend(f'ends_with(lower(http.host), ".{s}")' for s in suffixes)
    if not parts:
        return f'(http.host eq "{_NOOP_HOST}")'
    expression = " or ".join(parts)
    if len(expression) > _MAX_EXPRESSION:
        raise WafError("too many blocked hostnames for a single rule in this zone")
    return expression


def parse_expression(expression: str) -> set[str]:
    hosts: set[str] = set()
    for group in _IN_RE.findall(expression):
        hosts |= {h for h in _QUOTED_RE.findall(group) if h != _NOOP_HOST and is_hostname(h)}
    hosts |= {f"*.{s}" for s in _ENDS_RE.findall(expression) if is_wildcard(f"*.{s}")}
    return hosts


def find_rule(ruleset: JSON | None) -> JSON | None:
    if not ruleset:
        return None
    for rule in ruleset.get("rules") or []:
        if rule.get("description") == RULE_DESCRIPTION:
            return rule  # type: ignore[no-any-return]
    return None


def blocked_from_ruleset(ruleset: JSON | None) -> set[str]:
    rule = find_rule(ruleset)
    if not rule or not rule.get("enabled", True):
        return set()
    return parse_expression(str(rule.get("expression", "")))


class WafManager:
    def __init__(self, cf: CloudflareClient, locks: LockManager) -> None:
        self._cf = cf
        self._locks = locks

    async def blocked_hosts(self, zone_id: str) -> set[str]:
        return blocked_from_ruleset(await self._cf.get_waf_entrypoint(zone_id))

    async def update(
        self, zone_id: str, block: Iterable[str] = (), allow: Iterable[str] = ()
    ) -> set[str]:
        """Read-modify-write the zone's block list under a cross-process lock.

        The ruleset returned by the write is checked and the write retried, so a concurrent
        change made outside Tunnelgate cannot silently undo a block.
        """
        block, allow = set(block), set(allow)
        async with self._locks.hold(f"waf-{zone_id}"):
            for _ in range(3):
                ruleset = await self._cf.get_waf_entrypoint(zone_id)
                current = blocked_from_ruleset(ruleset)
                desired = (current | block) - allow
                existing = find_rule(ruleset)
                if desired == current and (existing is not None or not desired):
                    return current
                rule: JSON = {
                    "action": "block",
                    "expression": build_expression(desired),
                    "description": RULE_DESCRIPTION,
                    "enabled": bool(desired),
                }
                if ruleset is None:
                    written = await self._cf.create_waf_entrypoint(zone_id, rule)
                elif existing is None:
                    written = await self._cf.add_waf_rule(zone_id, ruleset["id"], rule)
                else:
                    written = await self._cf.update_waf_rule(
                        zone_id, ruleset["id"], existing["id"], rule
                    )
                if blocked_from_ruleset(written) == desired:
                    return desired
                log.warning("WAF rule in zone %s did not match after write; retrying", zone_id)
        raise WafError("the block rule did not reach the requested state")
