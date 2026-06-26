"""Generate user-friendly question prompts for missing fields."""

import re

from app.forms.missing_fields import get_next_question, get_missing_required_fields
from app.ai.question_rewriter import rewrite_question

# Instructional asides that belong in the UI, not in a spoken sentence, e.g.
# "(optional, say 'skip' to skip)" or "(MM/DD/YYYY)". Stripped from the base
# text before it's rephrased / spoken so it sounds like a person talking.
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")


def _spoken_base(field: dict) -> str:
    """The field's question with UI-only parentheticals removed."""
    raw = field.get("question_text") or f"Please provide your {field.get('label', field['field_key'])}."
    cleaned = _PARENTHETICAL.sub("", raw).strip()
    return cleaned or raw


def build_question_prompt(
    field: dict, answers: dict | None = None, form_id: str | None = None, attempt: int = 1
) -> str:
    """
    Return the question text to present/speak to the user for a given field.

    Routes through the AI rephraser (rewrite_question) so the spoken question
    sounds natural and first-person. Falls back to the cleaned base text when no
    LLM is configured. UI-only parentheticals are stripped before rephrasing.

    A per-form builder override (prompt pack ``field_overrides[field_key].question``)
    takes precedence over the schema's question_text, so an admin can reword a
    question without editing the schema — this applies even with no LLM (it becomes
    the rule-based base text).
    """
    from app.forms.prompts import get_field_override

    override = get_field_override(form_id, field.get("field_key", ""))
    base = override.get("question") or _spoken_base(field)
    # Feed the rephraser a clean, instruction-free version of the question.
    field_for_llm = {**field, "question_text": base}
    return rewrite_question(field_for_llm, answers or {}, attempt=attempt, form_id=form_id)


def get_current_question_context(
    form_id: str,
    answers: dict,
) -> dict | None:
    """
    Return a dict with:
      - field: the field schema
      - question: the natural, spoken-ready prompt string
      - missing_count: total remaining required fields
    or None if all required fields are answered.
    """
    missing = get_missing_required_fields(form_id, answers)
    if not missing:
        return None

    field = missing[0]
    return {
        "field": field,
        "question": build_question_prompt(field, answers, form_id),
        "missing_count": len(missing),
        "field_key": field["field_key"],
        "field_type": field["type"],
        "is_sensitive": field.get("sensitive", False),
        "is_optional": not field.get("required", True),
    }
