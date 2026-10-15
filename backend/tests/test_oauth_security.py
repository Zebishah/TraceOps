import base64
import hashlib

from ops_pilot.core.oauth_security import (
    generate_oauth_secret,
    hash_oauth_secret,
    verify_oauth_secret,
    verify_pkce_s256,
)


def test_oauth_secret_hash_and_verification() -> None:
    secret = generate_oauth_secret()

    secret_hash = hash_oauth_secret(secret)

    assert secret != secret_hash

    assert verify_oauth_secret(
        secret,
        secret_hash,
    )

    assert not verify_oauth_secret(
        "wrong-secret",
        secret_hash,
    )


def test_verify_pkce_s256() -> None:
    verifier = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"

    digest = hashlib.sha256(verifier.encode("ascii")).digest()

    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    assert verify_pkce_s256(
        code_verifier=verifier,
        expected_challenge=challenge,
    )

    assert not verify_pkce_s256(
        code_verifier="wrong-verifier",
        expected_challenge=challenge,
    )
