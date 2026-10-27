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


@pytest.fixture
def password_env(base_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for k in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "ALLOWED_GROUPS"):
        base_env.delenv(k)
    base_env.setenv("BASIC_AUTH_USERNAME", "admin")
    base_env.setenv("BASIC_AUTH_PASSWORD", "pw")
    return base_env


def test_oidc_mode(base_env: pytest.MonkeyPatch) -> None:
    assert Settings().auth_mode == "oidc"


def test_password_mode(password_env: pytest.MonkeyPatch) -> None:
    s = Settings()
    assert s.auth_mode == "password"
    assert s.issuer == s.issuer_origin == s.issuer_host == ""
    assert s.critical_hostnames == {"a.example.com"}
    assert s.password_check == ("plain", "pw")


def test_both_modes_prefer_oidc(
    base_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    base_env.setenv("BASIC_AUTH_USERNAME", "admin")
    base_env.setenv("BASIC_AUTH_PASSWORD", "pw")
    assert Settings().auth_mode == "oidc"
    assert "using OIDC" in caplog.text


def test_hash_wins_over_plain(
    password_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from tunnelgate.passwords import hash_password

    encoded = hash_password("pw2")
    password_env.setenv("BASIC_AUTH_PASSWORD_HASH", encoded)
    assert Settings().password_check == ("hash", encoded)
    assert "using the hash" in caplog.text


def test_plain_password_logs_nothing(
    password_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    Settings()
    assert caplog.text == ""


@pytest.mark.parametrize(
    ("unset", "extra"),
    [
        (("BASIC_AUTH_USERNAME", "BASIC_AUTH_PASSWORD"), {}),
        (("BASIC_AUTH_PASSWORD",), {}),
        (("BASIC_AUTH_USERNAME",), {}),
        ((), {"BASIC_AUTH_PASSWORD_HASH": "scrypt$1$2"}),
        ((), {"BASIC_AUTH_PASSWORD_HASH": "scrypt:1048576:8:1:AAAA:AAAA"}),
        ((), {"BASIC_AUTH_USERNAME": "bad<user>"}),
        ((), {"BASIC_AUTH_PASSWORD": ""}),
        ((), {"OIDC_ISSUER": "https://auth.example.com"}),
    ],
)
def test_incomplete_auth_config_is_rejected(
    password_env: pytest.MonkeyPatch, unset: tuple[str, ...], extra: dict[str, str]
) -> None:
    for k in unset:
        password_env.delenv(k)
    for k, v in extra.items():
        password_env.setenv(k, v)
    with pytest.raises(ValidationError):
        Settings()
