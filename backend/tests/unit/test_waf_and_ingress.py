from __future__ import annotations

import pytest

from tunnelgate.service import (
    ConflictError,
    NotFoundError,
    apply_origin_overrides,
    insert_before_catch_all,
    remove_ingress_rule,
    validate_tunnel_id,
)
from tunnelgate.validation import ValidationError
from tunnelgate.waf import blocked_from_ruleset, build_expression, find_rule, parse_expression


def test_build_and_parse_expression_roundtrip() -> None:
    expr = build_expression({"b.example.com", "a.example.com"})
    assert expr == '(lower(http.host) in {"a.example.com" "b.example.com"})'
    assert parse_expression(expr) == {"a.example.com", "b.example.com"}
    assert build_expression([]) == '(http.host eq "tunnelgate.invalid")'
    assert parse_expression(build_expression([])) == set()
    mixed = build_expression({"a.example.com", "*.apps.example.com"})
    assert mixed == (
        '(lower(http.host) in {"a.example.com"}) or ends_with(lower(http.host), ".apps.example.com")'
    )
    assert parse_expression(mixed) == {"a.example.com", "*.apps.example.com"}


@pytest.mark.parametrize(
    "bad", ['a.com" or true or "', "a.com)", "*.*.example.com", "a b.com", "", '*.com"']
)
def test_build_expression_rejects_injection(bad: str) -> None:
    with pytest.raises(ValidationError):
        build_expression({bad})


def test_expression_length_limit() -> None:
    from tunnelgate.waf import WafError

    with pytest.raises(WafError):
        build_expression({f"host{i}.example.com" for i in range(300)})


def test_parse_ignores_garbage() -> None:
    expr = '(lower(http.host) in {"ok.example.com" "bad host" "x\\"y"}) or ends_with(lower(http.host), ".bad host")'
    assert parse_expression(expr) == {"ok.example.com"}


def test_blocked_from_ruleset() -> None:
    assert blocked_from_ruleset(None) == set()
    rs = {
        "rules": [
            {"description": "other", "expression": '(http.host in {"x.example.com"})'},
            {
                "id": "r",
                "description": "tunnelgate-managed",
                "enabled": True,
                "expression": '(http.host in {"a.example.com"})',
            },
        ]
    }
    assert find_rule(rs)["id"] == "r"  # type: ignore[index]
    assert blocked_from_ruleset(rs) == {"a.example.com"}
    rs["rules"][1]["enabled"] = False
    assert blocked_from_ruleset(rs) == set()


def test_ingress_helpers() -> None:
    ingress = [{"hostname": "a.example.com", "service": "http://a"}, {"service": "http_status:404"}]
    new = insert_before_catch_all(ingress, {"hostname": "b.example.com", "service": "http://b"})
    assert [r.get("hostname") for r in new] == ["a.example.com", "b.example.com", None]
    assert ingress[-1] == {"service": "http_status:404"}  # original untouched
    assert [r.get("hostname") for r in remove_ingress_rule(new, "a.example.com", None)] == [
        "b.example.com",
        None,
    ]
    with pytest.raises(NotFoundError):
        remove_ingress_rule(new, "zzz.example.com", None)
    with pytest.raises(ConflictError):
        insert_before_catch_all([{"hostname": "a.example.com", "service": "x"}], {"hostname": "b"})
    with pytest.raises(ConflictError):
        insert_before_catch_all([], {"hostname": "b"})


def test_origin_overrides_cannot_drop_protections() -> None:
    base = {"access": {"required": True}, "ipRules": [{"prefix": "10.0.0.0/8"}]}
    for key in ("access", "ipRules", "proxyType", "caPool"):
        with pytest.raises(ValidationError):
            apply_origin_overrides(base, {key: None})
    with pytest.raises(ValidationError):
        apply_origin_overrides(
            {}, {"httpHostHeader": "app.example.com"}, frozenset({"app.example.com"})
        )


def test_insert_before_covering_wildcard() -> None:
    ingress = [
        {"hostname": "a.example.com"},
        {"hostname": "*.apps.example.com"},
        {"service": "http_status:404"},
    ]
    out = insert_before_catch_all(ingress, {"hostname": "x.apps.example.com"})
    assert [r.get("hostname") for r in out] == [
        "a.example.com",
        "x.apps.example.com",
        "*.apps.example.com",
        None,
    ]
    out = insert_before_catch_all(ingress, {"hostname": "x.example.com"})
    assert [r.get("hostname") for r in out][-2] == "x.example.com"


def test_origin_overrides() -> None:
    base = {"noTLSVerify": True, "access": {"required": True}}
    out = apply_origin_overrides(
        base, {"noTLSVerify": None, "connectTimeout": 15, "originServerName": "X.example.com"}
    )
    assert out == {
        "access": {"required": True},
        "connectTimeout": 15,
        "originServerName": "x.example.com",
    }
    assert base == {"noTLSVerify": True, "access": {"required": True}}
    assert apply_origin_overrides({"httpHostHeader": "a.example.com"}, {"httpHostHeader": ""}) == {}
    for bad in (
        {"noTLSVerify": 1},
        {"connectTimeout": True},
        {"connectTimeout": 9999},
        {"httpHostHeader": 5},
        {"httpHostHeader": "bad host"},
        {"caPool": "/etc/ssl"},
    ):
        with pytest.raises(ValidationError):
            apply_origin_overrides({}, bad)


def test_tunnel_id_validation() -> None:
    assert validate_tunnel_id("11111111-1111-4111-8111-111111111111")
    for bad in (
        "../zones",
        "11111111-1111-4111-8111-11111111111",
        "X1111111-1111-4111-8111-111111111111",
    ):
        with pytest.raises(ValidationError):
            validate_tunnel_id(bad)


def test_summarize_connectors() -> None:
    from tunnelgate.service import summarize_connectors

    assert summarize_connectors([]) == (0, [])
    conns = [
        *({"client_id": "a", "client_version": "2026.9.1"} for _ in range(4)),
        *({"client_id": "b", "client_version": "2026.10.0"} for _ in range(4)),
        {"client_id": "c", "client_version": "2026.9.1"},
    ]
    assert summarize_connectors(conns) == (3, ["2026.10.0", "2026.9.1"])
    assert summarize_connectors([{"client_id": "x"}]) == (1, [])
    assert summarize_connectors([{"client_id": "x", "client_version": "<b>bad</b>"}]) == (1, [])
