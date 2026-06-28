"""Readiness and coverage checks for form completion.

The conversational agent is allowed to be flexible and helpful, but completion is
not. This module is the deterministic gate used by review, approval, workflow, and
tests to prove a session is actually ready:

- every applicable field is answered or explicitly skipped;
- stored answers still validate against the session schema snapshot;
- low-confidence answers are surfaced before approval;
- official-PDF forms do not silently drop answered fields because of mapping drift.

The checks are schema-snapshot based so in-flight sessions remain stable if an
admin edits and republishes the live form definition later.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from app.forms.missing_fields import (
    SKIPPED,
    get_missing_applicable_fields,
    get_missing_required_fields,
    is_field_applicable,
)
from app.forms.service import get_all_fields_from_schema
from app.forms.validation import ValidationError, validate_answer

LOW_CONFIDENCE_THRESHOLD = 0.75


def build_session_readiness(
    form_id: str,
    schema: dict,
    answer_rows: Iterable[Any],
    *,
    confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
) -> dict:
    """Return a machine-readable completion report for one session.

    ``answer_rows`` may be SQLAlchemy ``FormAnswer`` rows or small test doubles
    with ``field_key``, ``value_json``, ``source``, and ``confidence`` attributes.
    """
    rows = list(answer_rows)
    answers = {_row_key(r): _deserialize(getattr(r, "value_json", None)) for r in rows}
    sources = {_row_key(r): getattr(r, "source", "missing") for r in rows}
    confidences = {_row_key(r): float(getattr(r, "confidence", 1.0) or 0.0) for r in rows}

    fields = get_all_fields_from_schema(schema)
    fields_by_key = {f["field_key"]: f for f in fields}
    applicable = [f for f in fields if is_field_applicable(f, answers, fields_by_key)]
    applicable_keys = {f["field_key"] for f in applicable}

    missing_applicable = get_missing_applicable_fields(form_id, answers, schema)
    missing_required = get_missing_required_fields(form_id, answers, schema)
    missing_required_keys = {f["field_key"] for f in missing_required}
    missing_optional = [f for f in missing_applicable if f["field_key"] not in missing_required_keys]

    invalid_fields = _invalid_answer_issues(applicable, answers)
    low_confidence_fields = _low_confidence_issues(applicable, answers, sources, confidences, confidence_threshold)
    skipped_fields = [_field_issue(f, "info", "skipped", "Skipped intentionally.", "review")
                      for f in applicable if answers.get(f["field_key"]) == SKIPPED]

    pdf_audit = audit_pdf_mapping(form_id, schema)
    unmapped_answered_fields = _unmapped_answered_field_issues(applicable, answers, pdf_audit)
    consistency_fields = _consistency_issues(applicable, answers)

    blockers = [
        *[_field_issue(f, "blocker", "missing_required", "Required field is missing.", "answer")
          for f in missing_required],
        *[_field_issue(f, "blocker", "missing_optional", "Answer or skip this optional field.", "answer_or_skip")
          for f in missing_optional],
        *invalid_fields,
        *low_confidence_fields,
        *unmapped_answered_fields,
    ]

    answered_keys = {
        k for k, v in answers.items()
        if k in applicable_keys and _has_value(v) and v != SKIPPED
    }
    skipped_keys = {k for k, v in answers.items() if k in applicable_keys and v == SKIPPED}
    status = "ready" if not blockers else "needs_attention"

    return {
        "ready": not blockers,
        "status": status,
        "confidence_threshold": confidence_threshold,
        "summary": {
            "total_schema_fields": len(fields),
            "total_applicable_fields": len(applicable),
            "answered_fields": len(answered_keys),
            "skipped_fields": len(skipped_keys),
            "missing_fields": len(missing_applicable),
            "missing_required_fields": len(missing_required),
            "invalid_fields": len(invalid_fields),
            "low_confidence_fields": len(low_confidence_fields),
            "unmapped_answered_pdf_fields": len(unmapped_answered_fields),
            "inconsistent_fields": len(consistency_fields),
        },
        "blockers": blockers,
        "warnings": skipped_fields + consistency_fields,
        "missing_required": [f["field_key"] for f in missing_required],
        "missing_optional": [f["field_key"] for f in missing_optional],
        "missing_applicable": [f["field_key"] for f in missing_applicable],
        "invalid_fields": invalid_fields,
        "low_confidence_fields": low_confidence_fields,
        "skipped_fields": skipped_fields,
        "pdf": pdf_audit,
        # Included for diagnostics; unknown answers usually indicate stale data from
        # an older schema version or a broken external write.
        "unknown_answer_keys": sorted(k for k in answers if k not in fields_by_key),
    }


def audit_pdf_mapping(form_id: str, schema: dict) -> dict:
    """Audit static schema-to-PDF coverage for a form pack.

    DB-only forms without a bundled mapping are valid: they fall back to summary
    PDF generation. For official-PDF forms, this report catches stale schema keys,
    missing mapping rows, and AcroForm widget names that no longer exist.
    """
    fields = get_all_fields_from_schema(schema)
    schema_keys = {f["field_key"] for f in fields}
    excluded_keys = {f["field_key"] for f in fields if f.get("pdf_exclude")}

    mapping, mapping_path = _load_pdf_mapping(form_id)
    entries = mapping.get("fields") if isinstance(mapping, dict) else None
    entries = entries if isinstance(entries, list) else []
    mapping_keys = {e.get("field_key") for e in entries if e.get("field_key")}
    stale_mapping_keys = sorted(k for k in mapping_keys if k not in schema_keys)
    unmapped_schema_keys = sorted(k for k in schema_keys - excluded_keys if k not in mapping_keys)

    base_pdf = _resolve_base_pdf(mapping, mapping_path)
    missing_widgets = _missing_pdf_widgets(entries, base_pdf)

    return {
        "form_id": form_id,
        "has_mapping": bool(entries),
        "mapping_path": str(mapping_path) if mapping_path else None,
        "base_pdf": str(base_pdf) if base_pdf else None,
        "base_pdf_exists": bool(base_pdf and base_pdf.exists()),
        "mapped_field_count": len(mapping_keys),
        "excluded_field_count": len(excluded_keys),
        "unmapped_schema_fields": unmapped_schema_keys,
        "stale_mapping_fields": stale_mapping_keys,
        "missing_pdf_widgets": missing_widgets,
        "official_pdf_ready": bool(entries) and bool(base_pdf and base_pdf.exists())
        and not stale_mapping_keys and not missing_widgets,
        # Used by session readiness to detect answered values that would be dropped.
        "mapped_field_keys": sorted(mapping_keys),
    }


def _invalid_answer_issues(fields: list[dict], answers: dict[str, Any]) -> list[dict]:
    issues: list[dict] = []
    for field in fields:
        key = field["field_key"]
        if key not in answers or answers[key] == SKIPPED or not _has_value(answers[key]):
            continue
        try:
            validate_answer(field, answers[key])
        except ValidationError as exc:
            issues.append(_field_issue(
                field,
                "blocker",
                "invalid",
                f"Stored answer no longer validates: {exc}",
                "correct",
            ))
    return issues


def _low_confidence_issues(
    fields: list[dict],
    answers: dict[str, Any],
    sources: dict[str, str],
    confidences: dict[str, float],
    threshold: float,
) -> list[dict]:
    issues: list[dict] = []
    for field in fields:
        key = field["field_key"]
        if key not in answers or answers[key] == SKIPPED or not _has_value(answers[key]):
            continue
        confidence = confidences.get(key, 1.0)
        if confidence < threshold:
            issue = _field_issue(
                field,
                "blocker",
                "low_confidence",
                "The assistant is not confident enough in this answer.",
                "review_or_correct",
            )
            issue["confidence"] = confidence
            issue["source"] = sources.get(key, "unknown")
            issues.append(issue)
    return issues


def _unmapped_answered_field_issues(
    fields: list[dict],
    answers: dict[str, Any],
    pdf_audit: dict,
) -> list[dict]:
    if not pdf_audit.get("official_pdf_ready"):
        return []
    mapped_keys = set(pdf_audit.get("mapped_field_keys") or [])
    issues: list[dict] = []
    for field in fields:
        key = field["field_key"]
        if field.get("pdf_exclude") or key in mapped_keys:
            continue
        if key in answers and answers[key] != SKIPPED and _has_value(answers[key]):
            issues.append(_field_issue(
                field,
                "blocker",
                "pdf_unmapped",
                "This answered field is not mapped to the official PDF.",
                "map_pdf",
            ))
    return issues


def _parse_date_or_none(value: Any) -> "date | None":
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _consistency_issues(fields: list[dict], answers: dict[str, Any]) -> list[dict]:
    """Sanity checks a careful caseworker would catch — surfaced as NON-blocking
    warnings (severity "info"), never hard blockers, so an unusual-but-valid value can
    still be approved. Currently flags a birth date that is in the future or implies an
    implausible age (clear data-entry mistakes worth re-checking).
    """
    issues: list[dict] = []
    today = date.today()
    for field in fields:
        key = field["field_key"]
        is_dob = key.endswith(".dob") or (
            field.get("type") == "date" and "birth" in str(field.get("label", "")).lower()
        )
        if not is_dob:
            continue
        val = answers.get(key)
        if val is None or val == SKIPPED or not _has_value(val):
            continue
        dob = _parse_date_or_none(val)
        if dob is None:
            continue  # unparseable dates are already caught by the invalid-answer check
        if dob > today:
            issues.append(_field_issue(field, "info", "future_date",
                                       "This birth date is in the future — please re-check it.", "correct"))
        elif dob.year < 1900 or (today.year - dob.year) > 120:
            issues.append(_field_issue(field, "info", "implausible_date",
                                       "This birth date doesn't look right — please re-check it.", "correct"))
    return issues


def _field_issue(field: dict, severity: str, kind: str, message: str, action: str) -> dict:
    return {
        "field_key": field["field_key"],
        "label": field.get("label", field["field_key"]),
        "section": field.get("section", ""),
        "severity": severity,
        "kind": kind,
        "message": message,
        "action": action,
    }


def _load_pdf_mapping(form_id: str) -> tuple[dict, Path | None]:
    try:
        from app.forms import registry

        mapping_path = registry.pdf_mapping_path(form_id)
    except Exception:
        return {}, None
    if not mapping_path.exists():
        return {}, mapping_path
    try:
        return json.loads(mapping_path.read_text(encoding="utf-8")), mapping_path
    except Exception:
        return {}, mapping_path


def _resolve_base_pdf(mapping: dict, mapping_path: Path | None) -> Path | None:
    base_pdf = mapping.get("base_pdf") if isinstance(mapping, dict) else None
    if not base_pdf:
        return None
    candidates: list[Path] = []
    if mapping_path is not None:
        candidates.append(mapping_path.parent / base_pdf)
    candidates.append(Path(__file__).resolve().parents[1] / "pdf" / base_pdf)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def _missing_pdf_widgets(entries: list[dict], base_pdf: Path | None) -> list[str]:
    if not base_pdf or not base_pdf.exists():
        return []
    try:
        import fitz

        doc = fitz.open(str(base_pdf))
        try:
            widget_names = {
                widget.field_name
                for page in doc
                for widget in (page.widgets() or [])
                if widget.field_name
            }
        finally:
            doc.close()
    except Exception:
        return []
    return sorted({
        entry["acroform_name"]
        for entry in entries
        if entry.get("acroform_name") and entry["acroform_name"] not in widget_names
    })


def _deserialize(value_json: str | None) -> Any:
    if value_json is None:
        return None
    try:
        return json.loads(value_json)
    except Exception:
        return value_json


def _row_key(row: Any) -> str:
    return str(getattr(row, "field_key"))


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and value.strip() in ("", "null", "None"):
        return False
    return True
