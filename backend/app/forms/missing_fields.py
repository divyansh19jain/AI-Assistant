"""Determine which form fields are still missing given current answers."""

from typing import Any

from app.forms.service import get_all_fields, get_all_fields_from_schema
from app.forms.validation import ValidationError, validate_answer


SKIPPED = "__skipped__"


def _has_meaningful_value(value: Any) -> bool:
    """Return False for values that should not satisfy dependency ``present`` checks."""
    if value is None:
        return False
    if isinstance(value, str) and value.strip() in ("", SKIPPED, "null", "None"):
        return False
    return True


def _field_answered(field: dict, answers: dict[str, Any]) -> bool:
    """A field is answered when it has a stored value that still validates.

    This is deliberately stricter than a raw "key exists" check. If a past bug or
    schema change left junk in the DB (for example the assistant's own question
    saved as a first name), the interview should re-ask that field instead of
    silently treating the invalid value as complete.
    """
    field_key = field["field_key"]
    if field_key not in answers:
        return False
    value = answers[field_key]
    if value == SKIPPED:
        return True
    if not _has_meaningful_value(value):
        return False
    try:
        validate_answer(field, value)
    except ValidationError:
        return False
    return True


_INVALID_DEPENDENCY_VALUE = object()


def _normalized_dependency_value(
    dep_key: str,
    dep_answer: Any,
    fields_by_key: dict[str, dict] | None = None,
) -> Any:
    """Return the dependency value after schema validation, or a sentinel if invalid.

    Dependencies are branch gates. If a stale/buggy value no longer validates, it
    must not activate child questions just because a row exists in the database.
    """
    if not fields_by_key:
        return dep_answer
    dep_field = fields_by_key.get(dep_key)
    if not dep_field:
        return dep_answer
    try:
        return validate_answer(dep_field, dep_answer)
    except ValidationError:
        return _INVALID_DEPENDENCY_VALUE


def _dependency_clause_satisfied(
    dep: dict[str, Any],
    answers: dict[str, Any],
    fields_by_key: dict[str, dict] | None = None,
) -> bool:
    """Evaluate one dependency clause.

    Future form packs can express human workflow branches declaratively:
    ``value`` for equality, ``not_value`` for "ask only if not X", ``values`` for
    membership, ``field_keys``/``min_true`` for count-style symptom gates, and
    nested ``any``/``all`` for multi-question clinical gates.
    """
    if "all" in dep:
        clauses = dep.get("all") or []
        return all(
            _dependency_clause_satisfied(clause, answers, fields_by_key)
            for clause in clauses
            if isinstance(clause, dict)
        )
    if "any" in dep:
        clauses = dep.get("any") or []
        return any(
            _dependency_clause_satisfied(clause, answers, fields_by_key)
            for clause in clauses
            if isinstance(clause, dict)
        )

    if "field_keys" in dep:
        keys = [str(key) for key in dep.get("field_keys") or [] if isinstance(key, str)]
        if not keys:
            return False
        try:
            min_true = int(dep.get("min_true", 1))
        except (TypeError, ValueError):
            return False
        if min_true < 1:
            return False
        true_count = 0
        for key in keys:
            dep_answer = answers.get(key)
            if not _has_meaningful_value(dep_answer):
                continue
            dep_answer = _normalized_dependency_value(key, dep_answer, fields_by_key)
            if dep_answer is _INVALID_DEPENDENCY_VALUE:
                continue
            if dep_answer is True:
                true_count += 1
        return true_count >= min_true

    dep_key = dep.get("field_key")
    if not dep_key:
        return True

    dep_answer = answers.get(dep_key)
    if not _has_meaningful_value(dep_answer):
        return False
    dep_answer = _normalized_dependency_value(dep_key, dep_answer, fields_by_key)
    if dep_answer is _INVALID_DEPENDENCY_VALUE:
        return False

    if "value" in dep:
        return dep_answer == dep["value"]

    if "not_value" in dep:
        return dep_answer != dep["not_value"]

    if "values" in dep:
        return dep_answer in set(dep.get("values") or [])

    if "not_values" in dep:
        return dep_answer not in set(dep.get("not_values") or [])

    if dep.get("condition") == "present":
        return _has_meaningful_value(dep_answer)

    return True


def _dependency_parent_keys(dep: dict[str, Any] | None) -> set[str]:
    """Return every field key referenced by a possibly-nested dependency."""
    if not isinstance(dep, dict):
        return set()
    keys: set[str] = set()
    dep_key = dep.get("field_key")
    if dep_key:
        keys.add(str(dep_key))
    for dep_key in dep.get("field_keys") or []:
        if isinstance(dep_key, str):
            keys.add(dep_key)
    for child in dep.get("all") or []:
        keys.update(_dependency_parent_keys(child if isinstance(child, dict) else None))
    for child in dep.get("any") or []:
        keys.update(_dependency_parent_keys(child if isinstance(child, dict) else None))
    return keys


def _dependency_satisfied(
    field: dict,
    answers: dict[str, Any],
    fields_by_key: dict[str, dict] | None = None,
) -> bool:
    """Check whether a field's dependency condition is met."""
    dep = field.get("depends_on")
    if dep is None:
        return True
    if not isinstance(dep, dict):
        return True
    return _dependency_clause_satisfied(dep, answers, fields_by_key)


def is_field_applicable(
    field: dict,
    answers: dict[str, Any],
    fields_by_key: dict[str, dict] | None = None,
    _seen: set[str] | None = None,
) -> bool:
    """Return whether a field belongs to the active branch for ``answers``.

    A direct dependency is not enough for chained form branches. For example,
    ``person2.spouse_name`` depends on ``person2.file_jointly_with_spouse``, which
    itself depends on ``person2.tax_file_next_year`` and ``person2.adding_person2``.
    If Person 2 is later corrected to "no", every descendant must be inactive even
    when stale child answers are still present in the database.
    """
    if not _dependency_satisfied(field, answers, fields_by_key):
        return False

    dep = field.get("depends_on")
    dep_keys = _dependency_parent_keys(dep if isinstance(dep, dict) else None)
    if not dep_keys or not fields_by_key:
        return True

    field_key = field.get("field_key", "")
    seen = set(_seen or set())
    if field_key:
        seen.add(field_key)
    for dep_key in dep_keys:
        if dep_key in seen:
            # Invalid cyclic schemas should not make both sides look applicable forever.
            return False
        parent = fields_by_key.get(dep_key)
        if parent and not is_field_applicable(parent, answers, fields_by_key, seen):
            return False
    return True


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
    fields = get_all_fields_from_schema(schema)
    fields_by_key = {f["field_key"]: f for f in fields}
    for field in fields:
        key = field["field_key"]
        if key not in answers or not is_field_applicable(field, answers, fields_by_key):
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
    fields = _fields_for(form_id, schema)
    fields_by_key = {f["field_key"]: f for f in fields}
    for field in fields:
        if not is_field_applicable(field, answers, fields_by_key):
            continue
        if _field_answered(field, answers):
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

    fields = _fields_for(form_id, schema)
    fields_by_key = {f["field_key"]: f for f in fields}
    for field in fields:
        if not field.get("required", False):
            continue
        if not is_field_applicable(field, answers, fields_by_key):
            continue
        if _field_answered(field, answers):
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
    fields = _fields_for(form_id, schema)
    fields_by_key = {f["field_key"]: f for f in fields}
    for field in fields:
        if field.get("required", False):
            continue
        if not is_field_applicable(field, answers, fields_by_key):
            continue
        if not _field_answered(field, answers):
            missing.append(field)
    return missing
