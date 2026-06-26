"""
Central LangChain LLM factory for the conversational assistant.

This is the single place that constructs the chat model used for answer
extraction, question rephrasing, and "help / explain" answers. Everything goes
through here so the provider and model live in config (see core.config) rather
than being hardcoded across the AI modules.

Provider: OpenAI via langchain-openai (ChatOpenAI).

If no API key is configured the factory returns None and every caller falls
back to its rule-based path, so the app keeps working with zero AI cost.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_chat_model() -> Any | None:
    """
    Return a configured LangChain chat model, or None if unavailable.

    Cached so we don't rebuild the client on every request. The result is None
    when:
      - the provider key is missing, or
      - langchain-openai isn't installed, or
      - client construction fails for any reason.
    Callers MUST handle None by falling back to rule-based logic.
    """
    from app.core.config import get_settings

    settings = get_settings()
    provider = (settings.LLM_PROVIDER or "openai").lower()

    if provider != "openai":
        logger.warning("Unsupported LLM_PROVIDER '%s'; AI features disabled.", provider)
        return None

    if not settings.OPENAI_API_KEY:
        # Expected in local/dev without a key — debug, not warning.
        logger.debug("OPENAI_API_KEY not set; assistant runs in rule-based fallback mode.")
        return None

    try:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=settings.OPENAI_TEMPERATURE,
            timeout=30,
            max_retries=2,
        )
    except Exception:
        logger.warning("Failed to build ChatOpenAI client; falling back to rule-based.", exc_info=True)
        return None


def structured_model(schema: type) -> Any | None:
    """
    Return a chat model bound to a Pydantic output schema, or None.

    Uses OpenAI's native structured-output mode (method="json_schema") so the
    response is constrained to the schema and returned as a validated instance
    of `schema`. Keep schemas conservative (avoid exotic unions / constraints)
    because strict json_schema mode rejects some constructs.
    """
    model = get_chat_model()
    if model is None:
        return None
    try:
        return model.with_structured_output(schema, method="json_schema")
    except Exception:
        logger.warning("with_structured_output failed for %s; disabling structured path.", schema, exc_info=True)
        return None


def ai_enabled() -> bool:
    """True when a real LLM is configured and constructable."""
    return get_chat_model() is not None
