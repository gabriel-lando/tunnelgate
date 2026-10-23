from __future__ import annotations

import pytest

from tunnelgate.validation import (
    ValidationError,
    build_hostname,
    is_hostname,
    is_wildcard,
    normalize_hostname,
    validate_optional_hostname,
    validate_path,
    validate_service,
    zone_for,
)


@pytest.mark.parametrize("host", ["a.example.com", "x-1.y.example.co.uk", "A.Example.COM."])
def test_valid_hostnames(host: str) -> None:
    assert is_hostname(normalize_hostname(host))


@pytest.mark.parametrize(
    "host",
    [
        "",
        "localhost",
        "-a.example.com",
        "a-.example.com",
        "a..example.com",
        "a_b.example.com",
        'a.example.com" or "',
        "a.exa\nmple.com",
        "*.example.com",
        "a" * 64 + ".com",
        ("a." * 130) + "com",
    ],
)
def test_invalid_hostnames(host: str) -> None:
    with pytest.raises(ValidationError):
        normalize_hostname(host)


def test_wildcards() -> None:
    assert is_wildcard("*.apps.example.com")
    assert not is_wildcard("*.*.example.com")
    assert not is_wildcard("a.*.example.com")


def test_build_hostname() -> None:
    assert build_hostname("Vault-Test", "example.com") == "vault-test.example.com"
    assert build_hostname("a.b", "example.com") == "a.b.example.com"
    for bad in ("", "-x", "a_b", "a/b", "a b", "a..b"):
        with pytest.raises(ValidationError):
            build_hostname(bad, "example.com")


def test_zone_for_longest_suffix() -> None:
    zones = {"example.com": "1", "int.example.com": "2"}
    assert zone_for("a.int.example.com", zones) == "int.example.com"
    assert zone_for("a.example.com", zones) == "example.com"
    assert zone_for("*.apps.example.com", zones) == "example.com"
    assert zone_for("badexample.com", zones) is None


@pytest.mark.parametrize(
    "svc",
    ["http://gitea:3000", "https://10.0.0.1:8443/x?y=1", "tcp://db:5432", "ssh://h:22", "rdp://h"],
)
def test_valid_services(svc: str) -> None:
    assert validate_service(svc) == svc


@pytest.mark.parametrize(
    "svc",
    [
        "http_status:404",
        "hello_world",
        "unix:/run/x.sock",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://",
        "http://u:p@h",
        "http://h:99999",
        "http://h#frag",
        "ssh://h/path",
        "http://h x",
        "x" * 3000,
    ],
)
def test_invalid_services(svc: str) -> None:
    with pytest.raises(ValidationError):
        validate_service(svc)


def test_path_and_optional_hostname() -> None:
    assert validate_path(None) is None
    assert validate_path("") is None
    assert validate_path("^/api") == "^/api"
    with pytest.raises(ValidationError):
        validate_path("a b")
    with pytest.raises(ValidationError):
        validate_path("x" * 300)
    assert validate_optional_hostname("  ") is None
    assert validate_optional_hostname("A.example.com") == "a.example.com"


def test_route_hostname_normalization() -> None:
    from tunnelgate.validation import normalize_route_hostname

    assert normalize_route_hostname("*.Apps.Example.com.") == "*.apps.example.com"
    assert normalize_route_hostname("Git.example.com") == "git.example.com"
    with pytest.raises(ValidationError):
        normalize_route_hostname("*.*.example.com")


def test_service_policy() -> None:
    from tunnelgate.validation import ServicePolicy

    policy = ServicePolicy(forbidden_hosts=frozenset({"tg.example.com"}))
    assert policy.check("http://gitea:3000") == "http://gitea:3000"
    assert policy.check("https://10.0.0.5:8443") == "https://10.0.0.5:8443"
    for bad in (
        "http://localhost",
        "http://127.0.0.2:80",
        "http://[::1]",
        "http://169.254.169.254",
        "http://0.0.0.0:80",
        "https://TG.example.com",
        "http://[fe80::1]",
    ):
        with pytest.raises(ValidationError):
            policy.check(bad)
    allow = ServicePolicy(allowlist=("*.lan:*", "gitea:3000", "10.0.10.*"))
    assert allow.check("http://nas.lan:5000")
    assert allow.check("http://gitea:3000")
    assert allow.check("http://10.0.10.4:80")
    for bad in ("http://gitea:3001", "http://proxmox:8006", "http://10.0.20.4"):
        with pytest.raises(ValidationError):
            allow.check(bad)
