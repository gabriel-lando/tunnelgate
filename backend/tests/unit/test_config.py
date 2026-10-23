from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.conftest import ACCOUNT
from tunnelgate.config import Settings


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    env = {
        "CF_API_TOKEN": "t",
        "CF_ACCOUNT_ID": ACCOUNT,
        "OIDC_ISSUER": "https://auth.example.com/",
        "OIDC_CLIENT_ID": "tunnelgate",
        "OIDC_CLIENT_SECRET": "s",
        "APP_URL": "https://tg.int.example.com/",
        "ALLOWED_GROUPS": "HomeAdmins, Ops ",
        "CRITICAL_HOSTS": "A.example.com,",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return monkeypatch


def test_settings_parse(base_env: pytest.MonkeyPatch) -> None:
    s = Settings()
    assert s.allowed_groups == ["HomeAdmins", "Ops"]
    assert s.allowed_groups_folded == {"homeadmins", "ops"}
    assert s.issuer == "https://auth.example.com"
    assert s.issuer_origin == "https://auth.example.com"
    assert s.app_origin == "https://tg.int.example.com"
    assert s.redirect_uri == "https://tg.int.example.com/auth/callback"
    assert s.critical_hostnames == {"auth.example.com", "a.example.com"}
    assert s.secure_cookies and s.oidc_require_mfa


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("CF_ACCOUNT_ID", "not-hex"),
        ("APP_URL", "http://tg.int.example.com"),
        ("OIDC_ISSUER", "http://auth.example.com"),
        ("APP_URL", "https://tg.int.example.com/sub"),
        ("ALLOWED_GROUPS", " , "),
        ("ALLOWED_GROUPS", "bad<group>"),
        ("CRITICAL_HOSTS", "not a host"),
        ("CF_API_BASE", "http://api.cloudflare.com"),
        ("SESSION_MAX_AGE", "10"),
        ("SESSION_SECRET", "too-short"),
        ("SERVICE_ALLOWLIST", "bad pattern"),
    ],
)
def test_settings_reject_bad_values(base_env: pytest.MonkeyPatch, key: str, value: str) -> None:
    base_env.setenv(key, value)
    with pytest.raises(ValidationError):
        Settings()


def test_insecure_http_only_with_explicit_flag(base_env: pytest.MonkeyPatch) -> None:
    base_env.setenv("APP_URL", "http://localhost:5173")
    base_env.setenv("TUNNELGATE_ALLOW_INSECURE_HTTP", "true")
    assert not Settings().secure_cookies
