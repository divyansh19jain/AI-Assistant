"""Answer suggestions for the current field — tappable chips that fast-track entry on a
phone or tablet when voice is unclear or typing is slow.

For booleans it's Yes/No; for selects it's the allowed values; for a few safe,
low-cardinality text fields (city, county, state, relationship, language) it merges common
Ohio values with values seen frequently across past applications — since most applications
repeat the same handful of answers.

🔒 Privacy: NEVER suggests from a sensitive field (SSN / DOB / phone / address line). A
historical value is only surfaced when it is shared by several distinct applications
(k-anonymity), so no single person's answer is ever exposed.
"""

from __future__ import annotations

import json

_MIN_FREQUENCY = 3  # a historical value must appear in >= this many distinct sessions

# Common Ohio values so suggestions are useful immediately, before much history exists.
_COMMON_BY_SUFFIX: dict[str, list[str]] = {
    "city": ["Columbus", "Cleveland", "Cincinnati", "Toledo", "Akron", "Dayton", "Dublin"],
    "county": ["Franklin", "Cuyahoga", "Hamilton", "Summit", "Montgomery", "Lucas", "Delaware"],
    "state": ["OH"],
    "relationship_to_applicant": ["Self", "Spouse", "Child", "Parent"],
    "language": ["English", "Spanish", "Somali", "Arabic"],
    "preferred_language": ["English", "Spanish", "Somali", "Arabic"],
}


def suggestions_for_field(db, field: dict) -> list[str]:
    """Tappable answer suggestions for one field (may be empty)."""
    ftype = field.get("type", "text")
    rule = field.get("validation_rule") or {}
    if ftype == "boolean":
        return ["Yes", "No"]
    if ftype == "select":
        allowed = rule.get("allowed_values") or field.get("options") or []
        return [str(a) for a in allowed][:8]
    # Only a small allowlist of safe, repeating text fields get history-based hints.
    if field.get("sensitive") or ftype != "text":
        return []
    suffix = field["field_key"].split(".")[-1]
    common = _COMMON_BY_SUFFIX.get(suffix)
    if not common:
        return []
    merged: list[str] = []
    for value in _frequent_values(db, field["field_key"]) + common:  # history first
        if value not in merged:
            merged.append(value)
    return merged[:6]


def _frequent_values(db, field_key: str) -> list[str]:
    """Values shared by >= _MIN_FREQUENCY distinct past applications, most common first."""
    try:
        from sqlalchemy import func

        from app.db.models import FormAnswer

        rows = (
            db.query(FormAnswer.value_json, func.count(func.distinct(FormAnswer.session_id)))
            .filter(FormAnswer.field_key == field_key)
            .group_by(FormAnswer.value_json)
            .all()
        )
    except Exception:
        return []
    scored: list[tuple[str, int]] = []
    for value_json, count in rows:
        if int(count) < _MIN_FREQUENCY:
            continue  # k-anonymity: never surface a value only a few people gave
        try:
            value = json.loads(value_json) if value_json else None
        except Exception:
            value = value_json
        if not isinstance(value, str) or value in ("__skipped__", "", "null"):
            continue
        scored.append((value, int(count)))
    scored.sort(key=lambda pair: -pair[1])
    return [value for value, _ in scored[:6]]
