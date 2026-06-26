"""
Question rewriting / rephrasing for the voice assistant.

Primary path: returns question_text from the field schema.
OpenAI path (via LangChain, see app.ai.llm): generates a warm, conversational,
first-person rephrasing that incorporates already-answered context. Activated
when OPENAI_API_KEY is set; otherwise falls back to rule-based text.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def rewrite_question(
    field: dict,
    previous_answers: dict | None = None,
    attempt: int = 1,
    form_id: str | None = None,
) -> str:
    """
    Return a user-friendly, first-person question string.

    Args:
        field: Field schema dict (its question_text may already be a builder override)
        previous_answers: Already answered fields for context
        attempt: 1 = first ask, 2+ = rephrasing after an unclear answer
        form_id: when set, the form's builder persona is used for the LLM rephrasing
    """
    base = field.get("question_text", f"Please provide your {field.get('label', field['field_key'])}.")

    if attempt >= 3:
        # Third+ attempt: very plain with explicit format hint.
        validation = field.get("validation_rule", "")
        hint = f" ({validation})" if validation else ""
        return f"One more time — {base}{hint} You can also say 'skip' if this field is optional."

    llm_result = _llm_rewrite(field, previous_answers or {}, attempt, form_id)
    if llm_result:
        return llm_result

    # Rule-based fallback.
    if attempt == 1:
        return base
    return (
        f"Let me ask that differently. {base} "
        "(You can also say 'skip' if this is optional.)"
    )


def acknowledge_answer(field: dict, value) -> str:
    """
    Return a warm, human-sounding acknowledgment of an accepted answer,
    spoken just before the next question.

    Sounds like a real person responding — references what was said when
    appropriate, never echoes sensitive values.
    """
    from app.ai.llm import get_chat_model

    model = get_chat_model()
    sensitive = field.get("sensitive", False)
    label = field.get("label", "that")

    if model is None:
        return "Thanks, noted!"

    value_hint = "" if sensitive or value in (None, "", "__skipped__") else f'"{value}"'
    skipped = value in (None, "__skipped__")

    try:
        response = model.invoke([
            ("system",
             "You are a warm, conversational medical-form assistant talking "
             "directly to a patient filling out their application. "
             "The patient just answered a form field. Write a natural, human "
             "response (1-2 sentences) that acknowledges their specific answer — "
             "the way a real person would respond, not a robot. "
             "Examples of the tone: "
             "'Perfect, Kevin — got your first name down!', "
             "'No worries if you don't have a middle name, I'll leave that blank.', "
             "'Great, 04/15/1985 noted for your date of birth.' "
             "Rules: "
             "- DO NOT echo sensitive data (SSN, passwords). "
             "- If they skipped/have none, acknowledge that naturally. "
             "- Keep it to 1-2 short sentences. "
             "- DO NOT ask the next question. "
             "- Return only the spoken response text, no quotes."),
            ("human",
             f"Field: {label}\n"
             f"{'Skipped / no value' if skipped else f'Answer given: {value_hint}'}"),
        ])
        text = getattr(response, "content", None)
        if isinstance(text, list):
            text = " ".join(p.get("text", "") for p in text if isinstance(p, dict))
        if text and text.strip():
            return text.strip().strip('"')
    except Exception:
        logger.warning("Acknowledgment generation failed; using fallback.", exc_info=True)

    return "Thanks, noted!"


def _llm_rewrite(field: dict, previous_answers: dict, attempt: int, form_id: str | None = None) -> str | None:
    """
    Use OpenAI (via LangChain) to produce a conversational, first-person,
    context-aware rephrasing of the question.

    Returns None if no LLM is configured or the call fails.
    """
    from app.ai.llm import get_chat_model

    model = get_chat_model()
    if model is None:
        return None

    label = field.get("label", field.get("field_key", "field"))
    base_question = field.get("question_text", f"Please provide your {label}.")
    field_type = field.get("type", "text")
    required = field.get("required", True)
    validation_rule = field.get("validation_rule", "")

    # Build a brief context string from a few recent non-sensitive answers.
    context_lines = []
    for key, val in list(previous_answers.items())[-5:]:
        if val and not field.get("sensitive"):
            context_lines.append(f"  {key}: {val}")
    context_block = "\n".join(context_lines) if context_lines else "  (none yet)"

    retry_instruction = (
        "" if attempt == 1 else
        f" The patient already tried to answer and it was unclear (attempt {attempt}). "
        "Ask in a noticeably different, simpler way."
    )

    date_rule = (
        "- IMPORTANT: If the field type is 'date', you MUST include a spoken format "
        "example at the end, e.g. '— for example, January fifteenth, nineteen eighty-five' "
        "OR the numeric form 'for example, 01/15/1985'. Always include this so the patient "
        "knows exactly how to say it.\n"
    ) if field_type == "date" else ""

    # Per-form persona (set in the builder) replaces the default role sentence; the
    # structural voice/perspective/format rules below are ALWAYS kept so a custom
    # persona can't break the first/second-person + date-format guarantees.
    from app.forms.prompts import get_system_persona

    role = get_system_persona(form_id) or (
        "You are a warm, friendly medical-form assistant talking DIRECTLY to the "
        "patient who is filling out their own application."
    )
    system_prompt = (
        f"{role}\n"
        "VOICE AND PERSPECTIVE RULES (must follow):\n"
        "- Speak in the first/second person: address the patient as 'you' and use 'your'.\n"
        "- NEVER refer to the patient in the third person (no 'the applicant', "
        "'Person 1', 'the patient', or 'they' when you mean the listener).\n"
        "- Exception: if the question is about a DIFFERENT household member "
        "(e.g. 'Person 2') or 'anyone in the household', keep asking the patient "
        "ABOUT that other person.\n"
        f"{date_rule}"
        "- Keep it to one short, natural sentence suitable for being spoken aloud.\n"
        "- Return ONLY the question text. No quotes, no preamble, no explanation."
    )
    user_prompt = (
        f"Rephrase this form question conversationally.{retry_instruction}\n\n"
        f"Field: {label}\n"
        f"Field type: {field_type}\n"
        f"Required: {required}\n"
        f"Validation rule: {validation_rule}\n"
        f"Original question: {base_question}\n\n"
        f"Previously answered fields:\n{context_block}"
    )

    try:
        response = model.invoke(
            [("system", system_prompt), ("human", user_prompt)]
        )
        text = getattr(response, "content", None)
        if isinstance(text, list):  # some providers return content parts
            text = " ".join(part.get("text", "") for part in text if isinstance(part, dict))
        if text and text.strip():
            return text.strip().strip('"')
    except Exception:
        logger.warning(
            "OpenAI question rewrite failed for field '%s'.",
            field.get("field_key", "?"), exc_info=True,
        )

    return None
