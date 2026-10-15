import base64
import hashlib
import hmac
import secrets


def generate_oauth_secret() -> str:
    return secrets.token_urlsafe(
        48,
    )


def hash_oauth_secret(
    value: str,
) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify_oauth_secret(
    value: str,
    expected_hash: str,
) -> bool:
    actual_hash = hash_oauth_secret(
        value,
    )

    return hmac.compare_digest(
        actual_hash,
        expected_hash,
    )


def verify_pkce_s256(
    *,
    code_verifier: str,
    expected_challenge: str,
) -> bool:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()

    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    return hmac.compare_digest(
        challenge,
        expected_challenge,
    )
