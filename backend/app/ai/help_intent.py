"""
Help / explain intent detection for the conversational assistant.

When the patient says something like "what does this mean?", "why do you need
my SSN?", or "I don't understand", that is NOT an answer to store — it's a
request for help. This module:

  1. classify_intent(): decides whether the raw input is an ANSWER or a HELP
     request (rule-based first, LLM-assisted when configured).
  2. explain_field(): produces a short, plain-language, first-person answer to
     the patient's question about the current field.

Both degrade gracefully without an API key.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Obvious help phrases handled without an LLM call (fast + free).
_HELP_PHRASES = (
    "what does this mean", "what do you mean", "i don't understand",
    "i dont understand", "what is this", "why do you need", "why do you ask",
    "what should i", "what do i", "can you explain", "explain", "help",
    "what is that", "i'm confused", "im confused", "not sure what",
    "what's this for", "whats this for", "what is this for",
)


class _IntentSchema(BaseModel):
    """Structured classification of a raw user utterance."""

    intent: Literal["answer", "help"] = Field(
        description=(
            "'help' if the user is asking a question, asking for an explanation, "
            "or expressing confusion instead of answering the form field. "
            "'answer' if they are attempting to provide the field value."
        )
    )
    reason: Optional[str] = Field(default=None, description="Brief reason for the classification.")


def classify_intent(field: dict, raw_answer: str) -> str:
    """
    Return "help" or "answer".

    Rule-based fast path catches obvious help phrases; the LLM (when available)
    handles subtler cases. Defaults to "answer" so normal input is never
    mistaken for a help request.
    """
    text = raw_answer.strip().lower()
    if not text:
        return "answer"

    # Fast path: obvious help phrasing or a bare question.
    if any(p in text for p in _HELP_PHRASES):
        return "help"
    if text.endswith("?") and len(text.split()) >= 3:
        # A short multi-word question is very likely a help request, but only
        # when the LLM isn't around to judge nuance.
        from app.ai.llm import ai_enabled
        if not ai_enabled():
            return "help"

    from app.ai.llm import structured_model
    model = structured_model(_IntentSchema)
    if model is None:
        return "answer"  # no LLM: trust the rule-based result (answer)

    label = field.get("label", field.get("field_key", "field"))
    question_text = field.get("question_text", "")
    try:
        result: _IntentSchema = model.invoke([
            ("system",
             "You decide whether a patient's message is an ANSWER to a form "
             "field or a HELP request (a question, a request to explain, or "
             "confusion). Be conservative: only choose 'help' when they are "
             "clearly not trying to provide the value."),
            ("human",
             f"Field: {label}\nQuestion asked: {question_text}\n"
             f"Patient message: {raw_answer!r}\nClassify the intent."),
        ])
        if result is not None:
            return result.intent
    except Exception:
        logger.warning("Intent classification failed; defaulting to 'answer'.", exc_info=True)

    return "answer"


def _kb_context(form_id: str | None, label: str, question_text: str, raw_question: str) -> str:
    """Retrieve PHI-free KB snippets for this field ("" if the form has no KB).

    Opens a short read-only session so the AI helpers don't need a db handle threaded
    through the whole answer flow. The query is field-level text — see app/ai/kb.py.
    """
    if not form_id:
        return ""
    try:
        from app.ai.kb import retrieve
        from app.db.base import SessionLocal

        db = SessionLocal()
        try:
            snippets = retrieve(db, form_id, f"{label} {question_text} {raw_question}", k=3)
        finally:
            db.close()
        return "\n\n".join(snippets)
    except Exception:
        logger.warning("KB retrieval for explain_field failed.", exc_info=True)
        return ""


def explain_field(field: dict, raw_question: str, form_id: str | None = None) -> str:
    """
    Produce a short, plain-language, first-person explanation answering the
    patient's question about the current field, then nudge them to answer.

    When the form has a knowledgebase, relevant snippets are retrieved (PHI-free,
    field-level query) and used to ground the answer. Falls back to a static helpful
    sentence when no LLM is configured (still surfacing a KB snippet if present).
    """
    label = field.get("label", field.get("field_key", "field"))
    question_text = field.get("question_text", "")
    required = field.get("required", True)

    kb_context = _kb_context(form_id, label, question_text, raw_question)

    from app.ai.llm import get_chat_model
    model = get_chat_model()

    if model is None:
        opt = "" if required else " If it doesn't apply to you, you can say 'skip'."
        base = f"This is asking for your {label.lower()}.{opt} {question_text}".strip()
        if kb_context:
            base = f"{base} {kb_context.splitlines()[0][:240]}".strip()
        return base

    try:
        kb_block = f"\nReference material (use if relevant):\n{kb_context}" if kb_context else ""
        response = model.invoke([
            ("system",
             "You are a warm medical-form assistant. The patient asked a "
             "question about a form field. Answer it in 1-2 short, plain-language "
             "sentences, speaking directly to them as 'you'. Do not give legal or "
             "eligibility advice. End by gently re-asking for the value. Return "
             "only the spoken text."),
            ("human",
             f"Field: {label}\nField is required: {required}\n"
             f"Original question: {question_text}\n"
             f"Patient asked: {raw_question!r}{kb_block}"),
        ])
        text = getattr(response, "content", None)
        if isinstance(text, list):
            text = " ".join(part.get("text", "") for part in text if isinstance(part, dict))
        if text and text.strip():
            return text.strip().strip('"')
    except Exception:
        logger.warning("Field explanation failed; using static fallback.", exc_info=True)

    return f"This is asking for your {label.lower()}. {question_text}".strip()
