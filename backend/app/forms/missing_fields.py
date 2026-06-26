"""Determine which required fields are still missing given current answers."""

from app.forms.service import get_all_fields


def _dependency_satisfied(field: dict, answers: dict[str, any]) -> bool:
    """Check whether a field's dependency condition is met."""
    dep = field.get("depends_on")
    if dep is None:
        return True

    dep_key = dep.get("field_key")
    if not dep_key:
        return True

    dep_answer = answers.get(dep_key)
    if dep_answer is None:
        return False

    if "value" in dep:
        return dep_answer == dep["value"]

    if dep.get("condition") == "present":
        return bool(dep_answer)

    return True


def get_missing_required_fields(
    form_id: str,
    answers: dict[str, any],
) -> list[dict]:
    """
    Return ALL unanswered fields whose dependency conditions are met,
    in schema order (section by section, field by field).
    """
    all_fields = get_all_fields(form_id)
    missing = []

    for field in all_fields:
        if not _dependency_satisfied(field, answers):
            continue
        if field["field_key"] in answers:
            continue
        missing.append(field)

    return missing


def get_next_question(
    form_id: str,
    answers: dict[str, any],
) -> dict | None:
    """Return the next unanswered required field, or None if complete."""
    missing = get_missing_required_fields(form_id, answers)
    return missing[0] if missing else None


def get_optional_missing_fields(
    form_id: str,
    answers: dict[str, any],
) -> list[dict]:
    """Return optional fields that are not yet answered and whose deps are met."""
    all_fields = get_all_fields(form_id)
    missing = []
    for field in all_fields:
        if field.get("required", False):
            continue
        if not _dependency_satisfied(field, answers):
            continue
        if field["field_key"] not in answers:
            missing.append(field)
    return missing
