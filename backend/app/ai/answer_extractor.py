"""
Answer extraction and normalization.

Rule-based extraction is the fast primary path for strongly-typed fields
(date, phone, ssn, boolean) that already validate cleanly.

OpenAI (via LangChain, see app.ai.llm) is used to:
  - Normalise messy natural-language answers ("March of 1990" -> "1990-03").
  - Detect answers that don't fit the field at all ("Lincoln Avenue" given for
    a first-name field) and ask for clarification instead of silently storing.
  - Refine free-text fields.

Set OPENAI_API_KEY (and OPENAI_MODEL) in .env to enable the LLM path; without a
key everything falls back to rule-based logic and the app still works.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.forms.validation import validate_answer, ValidationError

logger = logging.getLogger(__name__)

# Field types we always try the LLM on first (free text the rules can't refine).
_LLM_PREFERRED_TYPES = {"text", "textarea"}

# Skip / unknown phrase sets, kept module-level so they're cheap and testable.
_SKIP_PHRASES = {"skip", "n/a", "na", "none", "pass"}
_DONT_KNOW_PHRASES = {"i don't know", "idk", "not sure", "unknown", "i'm not sure", "dunno"}

# Patterns that mean "I don't have this / it doesn't apply to me" for optional fields.
# Matched case-insensitively as a substring so "i don't have a middle name" matches.
_NONE_PATTERNS = (
    "i don't have", "i do not have", "i dont have",
    "no middle", "no suffix", "no second", "no nickname", "no maiden",
    "doesn't apply", "does not apply", "not applicable", "not apply",
    "i have no ", "there is no ", "there isn't", "there is none",
    "i have none", "none of these", "doesn't exist", "does not exist",
)

# UI/voice command words that are NEVER a field value. These leak in when the
# speech recogniser picks up a button label or a stray utterance (e.g. "send").
# They are treated as no-op commands, not answers, so the form never advances on
# them. "skip" is intentionally excluded — it's handled as a real skip above.
_COMMAND_WORDS = {
    "send", "submit", "stop", "start", "replay", "repeat", "next", "back",
    "cancel", "go", "enter", "ok", "okay", "done", "voice", "mute", "unmute",
    "type instead", "go to review",
}

# Below this confidence we ask the user to confirm before saving (smart-confirm).
_CONFIRM_THRESHOLD = 0.75


@dataclass
class ExtractionResult:
    value: Any
    confidence: float
    needs_clarification: bool
    clarification_question: Optional[str]
    # True when the input was a UI/voice command (e.g. "send") that should be
    # ignored entirely — not saved, not treated as a wrong answer.
    is_command: bool = False
    # True when the value is plausible but low-confidence and should be
    # confirmed by the user before saving (smart-confirm).
    needs_confirmation: bool = False


class _ValidationSchema(BaseModel):
    """Structured output contract for the semantic validation call."""

    is_valid: bool = Field(
        description=(
            "True if the answer is a plausible, real-world value for this field "
            "on an Ohio Medicaid application. False if it looks wrong, nonsensical, "
            "or clearly not a real answer (e.g. 'YouTube' for a county name)."
        )
    )
    feedback: str = Field(
        description=(
            "A short, warm, first-person message addressed to the patient. "
            "If is_valid is True, confirm the answer in one brief sentence "
            "(e.g. 'Got it — Franklin County noted.'). "
            "If is_valid is False, explain gently what seems off and ask them "
            "to double-check or correct it "
            "(e.g. 'That doesn't look like a county name — could you double-check?')."
        )
    )


class _ExtractionSchema(BaseModel):
    """Structured output contract for the LLM extraction call."""

    value: Optional[str] = Field(
        default=None,
        description=(
            "The normalised field value as a string, or null if the answer does "
            "not provide a valid value for THIS field. For date fields use "
            "YYYY-MM-DD. For boolean fields use 'true' or 'false'. For phone use "
            "10 digits. For ssn use 9 digits. For names/text return the cleaned text."
        ),
    )
    fits_field: bool = Field(
        description=(
            "True only if the user's answer plausibly belongs to THIS field. "
            "False if the answer is clearly something else (e.g. a street address "
            "given when asked for a first name, or a number given for a city)."
        )
    )
    confidence: float = Field(description="Confidence between 0.0 and 1.0.")
    clarification_question: Optional[str] = Field(
        default=None,
        description=(
            "If fits_field is false or the answer is ambiguous, a short, warm, "
            "first-person re-ask (address the user as 'you'). Otherwise null."
        ),
    )


def extract_answer(field: dict, raw_answer: str) -> ExtractionResult:
    """
    Extract and validate an answer from raw user input.

    Order of operations:
      1. Handle skip / "I don't know" sentinels.
      2. Try the LLM (if configured) for messy-answer + wrong-type handling.
      3. Fall back to rule-based validation.
    """
    raw = raw_answer.strip()

    # UI/voice command words (e.g. "send") are not answers — ignore them so the
    # form never advances on a stray recognised word.
    if raw.lower() in _COMMAND_WORDS:
        return ExtractionResult(
            value=None, confidence=0.0, needs_clarification=False,
            clarification_question=None, is_command=True,
        )

    raw_lower = raw.lower()

    # Skip handling for optional fields.
    if raw_lower in _SKIP_PHRASES and not field.get("required", True):
        return ExtractionResult(None, 1.0, False, None)

    # "I don't have X" / "not applicable" — auto-skip optional, nudge required.
    if any(p in raw_lower for p in _NONE_PATTERNS):
        if not field.get("required", True):
            return ExtractionResult(None, 1.0, False, None)
        else:
            label = field.get("label", "this field")
            return ExtractionResult(
                None, 0.0, True,
                f"This field is required — I still need your {label.lower()}. "
                f"Could you provide it?",
            )

    # "I don't know" handling.
    if raw_lower in _DONT_KNOW_PHRASES:
        if field.get("required", True):
            return ExtractionResult(
                None, 0.0, True,
                f"This one is required. {field.get('question_text', 'Could you give it a try?')}",
            )
        return ExtractionResult(None, 0.8, False, None)

    field_type = field.get("type", "text")

    # LLM-first for everything when a model is available: it both normalises
    # messy answers AND catches wrong-type answers. Falls through to rules if
    # the LLM is unavailable or returns nothing usable.
    llm_result = _llm_extract(field, raw)
    if llm_result is not None:
        return llm_result

    # ---- Rule-based fallback (no LLM configured) ----
    if field_type in _LLM_PREFERRED_TYPES:
        # Free text: trust as-is.
        return ExtractionResult(raw, 0.9, False, None)

    try:
        normalized = validate_answer(field, raw)
        return ExtractionResult(normalized, 1.0, False, None)
    except ValidationError as exc:
        return ExtractionResult(
            None, 0.0, True,
            f"{exc} {field.get('question_text', '')}".strip(),
        )


def _llm_extract(field: dict, raw_answer: str) -> ExtractionResult | None:
    """
    Use OpenAI (via LangChain structured output) to extract, normalise, and
    sanity-check a single field value.

    Returns None if no LLM is configured or the call fails, so callers fall
    back to rule-based logic.
    """
    from app.ai.llm import structured_model

    model = structured_model(_ExtractionSchema)
    if model is None:
        return None

    label = field.get("label", field.get("field_key", "field"))
    field_type = field.get("type", "text")
    required = field.get("required", True)
    validation_rule = field.get("validation_rule", "")
    question_text = field.get("question_text", "")

    system_prompt = (
        "You extract and validate a SINGLE medical-form field value from a "
        "patient's natural-language answer. Be strict about whether the answer "
        "actually fits the field: if the user clearly answered something other "
        "than what was asked (for example a street address when asked for a "
        "first name), set fits_field to false and write a short, warm, "
        "first-person clarification that re-asks for the right thing. Speak to "
        "the patient as 'you'."
    )
    allowed = ""
    if isinstance(validation_rule, dict) and validation_rule.get("allowed_values"):
        allowed = f"Allowed values: {validation_rule['allowed_values']}\n"

    user_prompt = (
        f"Field label: {label}\n"
        f"Field type: {field_type}\n"
        f"Required: {required}\n"
        f"Validation rule: {validation_rule}\n"
        f"{allowed}"
        f"Question that was asked: {question_text}\n"
        f"Patient's answer: {raw_answer!r}\n\n"
        "Extract the value following the type rules. "
        + (f"Map the answer to the closest allowed value (e.g. 'Junior' -> 'Jr'). " if allowed else "")
        + "If the answer does not fit this field, set fits_field=false and provide clarification_question."
    )

    try:
        result: _ExtractionSchema = model.invoke(
            [("system", system_prompt), ("human", user_prompt)]
        )
    except Exception:
        logger.warning(
            "OpenAI extraction failed for field '%s'; using rule-based fallback.",
            field.get("field_key", "?"), exc_info=True,
        )
        return None

    if result is None:
        return None

    # Wrong-type / ambiguous answer -> clarify, don't store.
    # Optional fields: treat a non-fitting answer as a skip so we never loop.
    if not result.fits_field or result.value is None:
        if not required:
            return ExtractionResult(value=None, confidence=1.0, needs_clarification=False, clarification_question=None)
        return ExtractionResult(
            value=None,
            confidence=float(result.confidence or 0.0),
            needs_clarification=True,
            clarification_question=(
                result.clarification_question
                or f"That doesn't look quite right for this field. {question_text}".strip()
            ),
        )

    # The LLM says it fits — still run rule validation for typed fields so the
    # stored value is guaranteed well-formed (the LLM normalised it to a string).
    coerced: Any = result.value
    if field_type not in _LLM_PREFERRED_TYPES:
        try:
            coerced = validate_answer(field, str(result.value))
        except ValidationError as exc:
            return ExtractionResult(
                value=None,
                confidence=0.0,
                needs_clarification=True,
                clarification_question=f"{exc} {question_text}".strip(),
            )

    conf = float(result.confidence or 0.9)
    # Smart-confirm: plausible but uncertain -> ask the user to confirm before
    # saving, with a natural "I heard X — is that right?" question.
    needs_confirm = conf < _CONFIRM_THRESHOLD
    confirm_q = None
    if needs_confirm and not field.get("sensitive", False):
        confirm_q = f"I heard \"{coerced}\" — is that right?"
    elif needs_confirm:
        confirm_q = "I've got that — did I hear you correctly?"

    # Semantic sanity-check: verify the extracted value makes real-world sense
    # before saving. Skip for select fields (allowed_values already guarantees
    # correctness) and sensitive fields (never send SSN etc. to LLM).
    if not field.get("sensitive", False) and field_type not in ("select", "boolean"):
        sem = _semantic_validate(field, coerced)
        if sem is not None and not sem.is_valid:
            return ExtractionResult(
                value=None,
                confidence=0.0,
                needs_clarification=True,
                clarification_question=sem.feedback,
            )

    return ExtractionResult(
        value=coerced,
        confidence=conf,
        needs_clarification=False,
        clarification_question=confirm_q,
        needs_confirmation=needs_confirm,
    )


def _semantic_validate(field: dict, value: Any) -> "_ValidationSchema | None":
    """
    Ask the LLM whether the extracted value makes real-world sense for this
    field on an Ohio Medicaid form. Returns None when no LLM is available or
    the call fails (callers treat None as "valid — proceed").
    """
    from app.ai.llm import structured_model

    model = structured_model(_ValidationSchema)
    if model is None:
        return None

    label = field.get("label", field.get("field_key", "field"))
    field_type = field.get("type", "text")
    question_text = field.get("question_text", "")

    system_prompt = (
        "You are a helpful assistant reviewing answers on an Ohio Medicaid application form. "
        "Check whether the value makes real-world sense for the field. "
        "Be lenient for free-text fields — only flag obvious nonsense (brand names, "
        "random words, country names where a US county is expected, gibberish, etc.). "
        "If valid, set is_valid=true and write a brief warm confirmation. "
        "If invalid, set is_valid=false and ask the patient warmly to correct it."
    )
    user_prompt = (
        f"Field label: {label}\n"
        f"Field type: {field_type}\n"
        f"Question asked: {question_text}\n"
        f"Extracted value: {value!r}\n\n"
        "Is this a plausible, real-world value for this field?"
    )

    try:
        return model.invoke([("system", system_prompt), ("human", user_prompt)])
    except Exception:
        logger.debug("Semantic validation call failed for field '%s'.", field.get("field_key", "?"), exc_info=True)
        return None
