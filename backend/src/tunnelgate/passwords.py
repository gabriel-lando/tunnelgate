"""scrypt password hashes for the single-user password login."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

# No "$" in the format: Docker Compose interpolates it in env files.
_FORMAT_RE = re.compile(r"^scrypt:(\d+):(\d+):(\d+):([A-Za-z0-9_-]+):([A-Za-z0-9_-]+)$")
_N, _R, _P = 2**15, 8, 1
_MAXMEM = 64 * 1024 * 1024
_DKLEN = 32


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, salt: bytes, *, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=_MAXMEM, dklen=dklen
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = _derive(password, salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt:{_N}:{_R}:{_P}:{_b64e(salt)}:{_b64e(key)}"


def is_valid_hash(encoded: str) -> bool:
    m = _FORMAT_RE.fullmatch(encoded)
    if not m:
        return False
    n, r, p = (int(x) for x in m.groups()[:3])
    try:
        salt, key = _b64d(m.group(4)), _b64d(m.group(5))
    except ValueError:  # includes binascii.Error
        return False
    # Bounds keep a hostile or typo'd hash from exhausting memory or CPU, or being guessable.
    return (
        2**14 <= n <= 2**17
        and n & (n - 1) == 0
        and 1 <= r <= 16
        and 1 <= p <= 4
        and 128 * n * r < _MAXMEM
        and len(salt) >= 16
        and 16 <= len(key) <= 64
    )


def verify_password(password: str, encoded: str) -> bool:
    if not is_valid_hash(encoded):
        return False
    _, n, r, p, salt, key = encoded.split(":")
    expected = _b64d(key)
    actual = _derive(password, _b64d(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
    return hmac.compare_digest(actual, expected)


def verify_plain(password: str, expected: str) -> bool:
    a = hashlib.sha256(password.encode("utf-8")).digest()
    b = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(a, b)
