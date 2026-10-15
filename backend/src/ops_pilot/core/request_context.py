import re
import uuid
from contextvars import ContextVar, Token

_REQUEST_ID: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def get_request_id() -> str | None:
    return _REQUEST_ID.get()


def create_request_id() -> str:
    return str(uuid.uuid4())


def normalize_request_id(
    value: str | None,
) -> str:
    if value is not None and _REQUEST_ID_PATTERN.fullmatch(value):
        return value

    return create_request_id()


def set_request_id(
    request_id: str,
) -> Token[str | None]:
    return _REQUEST_ID.set(request_id)


def reset_request_id(
    token: Token[str | None],
) -> None:
    _REQUEST_ID.reset(token)
