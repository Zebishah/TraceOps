from ops_pilot.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hashing_and_verification() -> None:
    password = "StrongPassword123!"

    hashed_password = hash_password(password)

    assert hashed_password != password

    assert verify_password(
        password,
        hashed_password,
    )

    assert not verify_password(
        "WrongPassword123!",
        hashed_password,
    )


def test_access_token_contains_subject() -> None:
    token = create_access_token(
        subject="test-user-id",
    )

    payload = decode_access_token(token)

    assert payload["sub"] == "test-user-id"
    assert "exp" in payload
