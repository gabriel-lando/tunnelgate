from __future__ import annotations

from tunnelgate.passwords import hash_password, is_valid_hash, verify_password, verify_plain


def test_hash_round_trip() -> None:
    encoded = hash_password("s3cret pass")
    assert encoded.startswith("scrypt:32768:8:1:") and "$" not in encoded
    assert is_valid_hash(encoded)
    assert verify_password("s3cret pass", encoded)
    assert not verify_password("s3cret pass ", encoded)
    assert hash_password("s3cret pass") != encoded


def test_invalid_hashes_never_verify() -> None:
    good = hash_password("x")
    for bad in (
        "",
        "plain",
        good.replace("scrypt:", "bcrypt:"),
        good.replace(":32768:", ":1000:"),
        good.replace(":32768:", ":4194304:"),
        good.replace(":8:1:", ":64:1:"),
        good + ":extra",
    ):
        assert not is_valid_hash(bad), bad
        assert not verify_password("x", bad)


def test_plain_compare() -> None:
    assert verify_plain("abc", "abc")
    assert not verify_plain("abc", "abcd")
    assert not verify_plain("", "abc")
