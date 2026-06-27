"""Determine which form fields are still missing given current answers."""

from typing import Any

from app.forms.service import get_all_fields, get_all_fields_from_schema


SKIPPED = "__skipped__"


def _has_meaningful_value(value: Any) -> bool:
    """Return False for values that should not satisfy dependency ``present`` checks."""
    if value is None:
        return False
    if isinstance(value, str) and value.strip() in ("", SKIPPED, "null", "None"):
        return False
    return True


def _field_answered(field_key: str, answers: dict[str, Any]) -> bool:
    """A field is answered when it has a stored value or the explicit skip sentinel."""
    if field_key not in answers:
        return False
    value = answers[field_key]
    if value == SKIPPED:
        return True
    return _has_meaningful_value(value)


def _dependency_satisfied(field: dict, answers: dict[str, Any]) -> bool:
    """Check whether a field's dependency condition is met."""
    dep = field.get("depends_on")
    if dep is None:
        return True

    dep_key = dep.get("field_key")
    if not dep_key:
        return True

    dep_answer = answers.get(dep_key)
    if not _has_meaningful_value(dep_answer):
        return False

    if "value" in dep:
        return dep_answer == dep["value"]

    if dep.get("condition") == "present":
        return _has_meaningful_value(dep_answer)

    return True


def is_field_applicable(field: dict, answers: dict[str, Any]) -> bool:
    """Public helper for review/output views that must hide inactive branches."""
    return _dependency_satisfied(field, answers)


def get_applicable_answers(
    schema: dict,
    answers: dict[str, Any],
    *,
    include_skipped: bool = True,
) -> dict[str, Any]:
    """Return answers that still belong to currently active schema branches.

    This helper is intentionally schema-snapshot based. Review, PDF generation, and
    portal submission must not emit an old child-branch answer after the parent
    dependency was changed in a way that makes that child field inactive.
    """
    out: dict[str, Any] = {}
    for field in get_all_fields_from_schema(schema):
        key = field["field_key"]
        if key not in answers or not is_field_applicable(field, answers):
            continue
        if answers[key] == SKIPPED and not include_skipped:
            continue
        out[key] = answers[key]
    return out


def _fields_for(form_id: str, schema: dict | None) -> list[dict]:
    return get_all_fields_from_schema(schema) if schema is not None else get_all_fields(form_id)


def get_missing_applicable_fields(
    form_id: str,
    answers: dict[str, Any],
    schema: dict | None = None,
) -> list[dict]:
    """
    Return unanswered fields whose dependency conditions are met, in schema order.

    The conversational assistant uses this broader list so optional fields are either
    answered or explicitly skipped before review/approval.
    """
    missing = []
    for field in _fields_for(form_id, schema):
        if not _dependency_satisfied(field, answers):
            continue
        if _field_answered(field["field_key"], answers):
            continue
        missing.append(field)
    return missing


def get_missing_required_fields(
    form_id: str,
    answers: dict[str, Any],
    schema: dict | None = None,
) -> list[dict]:
    """
    Return unanswered required fields whose dependency conditions are met.

    Review/approval uses this stricter view to distinguish required gaps from
    optional questions the user may skip.
    """
    missing = []

    for field in _fields_for(form_id, schema):
        if not field.get("required", False):
            continue
        if not _dependency_satisfied(field, answers):
            continue
        if _field_answered(field["field_key"], answers):
            continue
        missing.append(field)

    return missing


def get_next_question(
    form_id: str,
    answers: dict[str, Any],
    schema: dict | None = None,
) -> dict | None:
    """Return the next unanswered applicable field, or None if complete."""
    missing = get_missing_applicable_fields(form_id, answers, schema)
    return missing[0] if missing else None


def get_optional_missing_fields(
    form_id: str,
    answers: dict[str, Any],
    schema: dict | None = None,
) -> list[dict]:
    """Return optional fields that are not yet answered and whose deps are met."""
    missing = []
    for field in _fields_for(form_id, schema):
        if field.get("required", False):
            continue
        if not _dependency_satisfied(field, answers):
            continue
        if not _field_answered(field["field_key"], answers):
            missing.append(field)
    return missing
