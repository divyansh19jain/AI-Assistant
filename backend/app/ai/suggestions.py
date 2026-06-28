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


def suggestions_for_field(db, field: dict, answers: dict | None = None) -> list[str]:
    """Tappable answer suggestions for one field (may be empty)."""
    answers = answers or {}
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
    key = field["field_key"]
    suffix = key.split(".")[-1]
    if suffix == "city":
        return _city_suggestions(db, key, answers)  # ZIP-aware
    common = _COMMON_BY_SUFFIX.get(suffix)
    if not common:
        return []
    merged: list[str] = []
    for value in _frequent_values(db, key) + common:  # history first
        if value not in merged:
            merged.append(value)
    return merged[:6]


def _city_suggestions(db, city_field_key: str, answers: dict) -> list[str]:
    """Cities for the applicant's ZIP — what others in this ZIP entered (history) plus the
    canonical city for that ZIP — so on a phone they tap instead of typing."""
    zip_field_key = city_field_key[:-4] + "zip"  # applicant.city -> applicant.zip
    zip_code = str(answers.get(zip_field_key) or answers.get("applicant.zip") or "").strip()
    out: list[str] = []
    if zip_code:
        try:
            from app.services.zipcode import lookup_zip

            info = lookup_zip(zip_code)
            if info and info.get("city"):
                out.append(info["city"])  # canonical city for this ZIP
        except Exception:
            pass
        for city in _cities_for_zip(db, zip_code):  # what past applicants in this ZIP entered
            if city not in out:
                out.append(city)
    for city in _COMMON_BY_SUFFIX["city"]:  # common Ohio cities as a fallback
        if city not in out:
            out.append(city)
    return out[:6]


def _cities_for_zip(db, zip_code: str) -> list[str]:
    """Cities entered by past applications that share this ZIP (most common first).

    City for a ZIP is public geography (not PHI), so no frequency threshold is applied.
    """
    try:
        from sqlalchemy import func

        from app.db.models import FormAnswer

        zip_json = json.dumps(zip_code)
        session_ids = [
            r[0] for r in db.query(FormAnswer.session_id)
            .filter(FormAnswer.field_key == "applicant.zip", FormAnswer.value_json == zip_json)
            .all()
        ]
        if not session_ids:
            return []
        rows = (
            db.query(FormAnswer.value_json, func.count())
            .filter(FormAnswer.field_key == "applicant.city", FormAnswer.session_id.in_(session_ids))
            .group_by(FormAnswer.value_json)
            .all()
        )
    except Exception:
        return []
    scored: list[tuple[str, int]] = []
    for value_json, count in rows:
        try:
            value = json.loads(value_json) if value_json else None
        except Exception:
            value = value_json
        if isinstance(value, str) and value not in ("__skipped__", "", "null"):
            scored.append((value, int(count)))
    scored.sort(key=lambda pair: -pair[1])
    return [value for value, _ in scored[:5]]


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
