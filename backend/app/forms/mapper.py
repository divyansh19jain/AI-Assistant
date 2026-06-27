"""Maps normalized EMR patient data to form fields."""

import json
import re
from typing import Any, Callable
from app.emr.schemas import EMRPatient
from app.forms import registry
from app.forms.service import get_all_fields, get_all_fields_from_schema


def _format_dob(dob: str | None) -> str | None:
    """Convert YYYY-MM-DD to MM/DD/YYYY for form display."""
    if not dob:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", dob)
    if m:
        return f"{m.group(2)}/{m.group(3)}/{m.group(1)}"
    return dob


def _clean_phone(phone: str | None) -> str | None:
    """Strip non-digits; return 10-digit string or None."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    return digits if len(digits) == 10 else None


def _clean_ssn(ssn: str | None) -> str | None:
    """Strip dashes/spaces; return 9-digit string or None."""
    if not ssn:
        return None
    digits = re.sub(r"\D", "", ssn)
    return digits if len(digits) == 9 else None


def _map_sex(sex: str | None) -> str | None:
    if not sex:
        return None
    s = sex.strip().lower()
    if s in ("m", "male", "1"):
        return "Male"
    if s in ("f", "female", "2"):
        return "Female"
    return "Other"


def _map_marital(ms: str | None) -> bool | None:
    """Return True if currently married."""
    if not ms:
        return None
    return ms.strip().lower() in ("married", "m")


def _insurance_summary(patient: EMRPatient) -> str | None:
    if not patient.insurance:
        return None
    return "; ".join(str(i) for i in patient.insurance[:3])


def _employment_summary(patient: EMRPatient) -> str | None:
    if not patient.employment:
        return None
    return "; ".join(str(e) for e in patient.employment[:3])


def _income_summary(patient: EMRPatient) -> str | None:
    if not patient.income:
        return None
    return "; ".join(str(i) for i in patient.income[:3])


_TRANSFORMS: dict[str, Callable[[Any], Any]] = {
    "date_mmddyyyy": _format_dob,
    "phone10": _clean_phone,
    "ssn9": _clean_ssn,
    "sex": _map_sex,
    "married_bool": _map_marital,
}


# Legacy ODM prefill for the bundled form. New form packs should use a schema-level
# "prefill" block so EMR mappings travel with the form definition.
_PREFILL_MAP: dict[str, Callable[[EMRPatient], Any]] = {
    # ── Step 1: Applicant contact info ──────────────────────────────────
    "applicant.first_name":   lambda p: p.first_name or None,
    "applicant.middle_name":  lambda p: p.middle_name or None,
    "applicant.last_name":    lambda p: p.last_name or None,
    "applicant.suffix":       lambda p: p.suffix or None,
    "applicant.home_address": lambda p: p.address.line1 or None,
    "applicant.apartment":    lambda p: p.address.line2 or None,
    "applicant.city":         lambda p: p.address.city or None,
    "applicant.state":        lambda p: (p.address.state or "").strip() or None,
    "applicant.zip":          lambda p: p.address.zip or None,
    "applicant.county":       lambda p: p.address.county or None,
    "applicant.phone":        lambda p: _clean_phone(p.phone),
    "applicant.email":        lambda p: p.email or None,
    "applicant.preferred_language": lambda p: p.language or None,

    # ── Step 2 Person 1: same person as applicant ────────────────────────
    "person1.first_name":     lambda p: p.first_name or None,
    "person1.middle_name":    lambda p: p.middle_name or None,
    "person1.last_name":      lambda p: p.last_name or None,
    "person1.suffix":         lambda p: p.suffix or None,
    "person1.relationship_to_applicant": lambda p: "Self",
    "person1.dob":            lambda p: _format_dob(p.dob),
    "person1.sex":            lambda p: _map_sex(p.sex),
    "person1.ssn":            lambda p: _clean_ssn(p.ssn),
    "person1.married":        lambda p: _map_marital(p.marital_status),

    # ── Step 5: Health coverage from EMR ────────────────────────────────
    "health_coverage.current_coverage":    lambda p: _insurance_summary(p),

    # ── Step 3: Employment / income from EMR ────────────────────────────
    "income.emp1_person":     lambda p: f"{p.first_name} {p.last_name}".strip() if p.employment else None,
    "income.emp1_employer":   lambda p: str(p.employment[0]) if p.employment else None,
    "income.other_income":    lambda p: _income_summary(p),
}


def _read_path(obj: Any, path: str) -> Any:
    """Read a dotted path from a Pydantic model, object, or dict."""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
    return cur


def _extract_declarative_value(patient: EMRPatient, spec: Any) -> Any:
    """
    Evaluate a schema ``prefill`` spec.

    Supported shapes:
      "first_name"
      {"source": "address.line1", "transform": "phone10"}
      {"sources": ["preferred", "fallback"], "transform": "date_mmddyyyy"}
      {"const": "Self"}
    """
    if isinstance(spec, str):
        value = _read_path(patient, spec)
        transform = None
    elif isinstance(spec, dict):
        if "const" in spec:
            value = spec.get("const")
        else:
            sources = spec.get("sources") or [spec.get("source")]
            value = None
            for source in sources:
                if not source:
                    continue
                candidate = _read_path(patient, str(source))
                if candidate not in (None, ""):
                    value = candidate
                    break
        transform = spec.get("transform")
    else:
        return None

    if transform:
        fn = _TRANSFORMS.get(str(transform))
        if fn is None:
            return None
        value = fn(value)
    return value


def prefill_from_emr(
    patient: EMRPatient,
    form_id: str = "ODM_07216",
    schema: dict | None = None,
) -> dict[str, dict]:
    """
    Returns {field_key: {"value": ..., "value_json": ..., "source": "emr", "confidence": 1.0}}
    for each field that can be prefilled from the patient record.
    """
    prefilled: dict[str, dict] = {}
    all_fields = get_all_fields_from_schema(schema) if schema is not None else get_all_fields(form_id)
    field_keys = {f["field_key"] for f in all_fields}

    for field_key, extractor in _PREFILL_MAP.items():
        if field_key not in field_keys:
            continue
        try:
            value = extractor(patient)
        except Exception:
            value = None

        if value is not None and value != "":
            prefilled[field_key] = {
                "value": value,
                "value_json": json.dumps(value),
                "source": "emr",
                "confidence": 1.0,
            }

    try:
        declarative_map = (schema or {}).get("prefill") or registry.load_prefill_map(form_id)
    except Exception:
        declarative_map = (schema or {}).get("prefill") or {}

    for field_key, spec in declarative_map.items():
        if field_key not in field_keys:
            continue
        try:
            value = _extract_declarative_value(patient, spec)
        except Exception:
            value = None
        if value is not None and value != "":
            prefilled[field_key] = {
                "value": value,
                "value_json": json.dumps(value),
                "source": "emr",
                "confidence": 1.0,
            }

    return prefilled
