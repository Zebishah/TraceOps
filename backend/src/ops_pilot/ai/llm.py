from functools import lru_cache

from langchain_groq import ChatGroq
from pydantic import SecretStr

from ops_pilot.core.config import get_settings


@lru_cache
def get_chat_model() -> ChatGroq:
    settings = get_settings()

    return ChatGroq(
        model=settings.generation_model,
        api_key=SecretStr(settings.groq_api_key),
        temperature=0,
        max_retries=2,
        timeout=30.0,
    )
