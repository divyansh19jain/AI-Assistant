"""Document OCR — extract candidate field values from a photo (pay stub, ID, SSN
card, benefit letter) so the person doesn't have to read numbers aloud.

🔒 PHI EGRESS. The uploaded image can show SSN, DOB, name, and address, so it is sent
to the configured OpenAI-compatible vision model only when DOCUMENT_OCR_ENABLED is set
and a key is configured. Extractions are SUGGESTIONS ONLY — never auto-saved. The agent
or the person confirms each value before it becomes an answer (so a misread can't
silently corrupt the application). Each suggested value is validated against the field
schema before it is offered.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from app.core.config import get_settings
from app.forms.service import get_all_fields_from_schema
from app.forms.validation import ValidationError, validate_answer

logger = logging.getLogger(__name__)

_MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB cap on the upload
_OCR_FIELD_TYPES = {"text", "date", "phone", "ssn", "number", "select"}


def ocr_enabled() -> bool:
    """True only when document OCR is explicitly turned on AND a key is configured."""
    settings = get_settings()
    return bool(settings.OPENAI_API_KEY) and bool(getattr(settings, "DOCUMENT_OCR_ENABLED", False))


def _candidate_fields(schema: dict, answers: dict) -> list[dict]:
    """Active, not-yet-answered fields a document might contain — so we never suggest a
    value for an inactive branch (Person 2 not added, immigration N/A) or re-suggest a
    field the person already answered or skipped."""
    from app.forms.missing_fields import is_field_applicable

    out: list[dict] = []
    fields = get_all_fields_from_schema(schema)
    fields_by_key = {f["field_key"]: f for f in fields}
    for f in fields:
        if f.get("type", "text") not in _OCR_FIELD_TYPES:
            continue
        if not is_field_applicable(f, answers, fields_by_key):
            continue
        val = answers.get(f["field_key"])
        if val not in (None, "", "__skipped__"):
            try:
                validate_answer(f, val)
                continue
            except ValidationError:
                # A stale invalid row should not block OCR from suggesting a
                # replacement for that same field.
                pass
        if val == "__skipped__":
            continue
        out.append(f)
    return out


def extract_fields_from_image(image_bytes: bytes, mime: str, schema: dict, answers: dict | None = None) -> dict:
    """Return validated field suggestions read from a document image.

    Result: {"ok": True, "suggestions": [{field_key, label, value, confidence, sensitive}]}
    or {"ok": False, "error": "..."}. Never raises; failures degrade to an error dict.
    """
    if not ocr_enabled():
        return {"ok": False, "error": "document_ocr_disabled"}
    if not image_bytes or len(image_bytes) > _MAX_IMAGE_BYTES:
        return {"ok": False, "error": "invalid_image"}

    settings = get_settings()
    try:
        import httpx
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=httpx.Timeout(40.0, connect=5.0), max_retries=1)
    except Exception:
        logger.warning("Vision client unavailable; document OCR disabled.", exc_info=True)
        return {"ok": False, "error": "client_unavailable"}

    fields = _candidate_fields(schema, answers or {})
    if not fields:
        return {"ok": True, "suggestions": [], "source": "document_ocr"}
    by_key = {f["field_key"]: f for f in fields}
    field_lines = "\n".join(
        f"- {f['field_key']} ({f.get('type','text')}): {f.get('label','')}"
        + (f" choices={(f.get('validation_rule') or {}).get('allowed_values')}"
           if (f.get('validation_rule') or {}).get('allowed_values') else "")
        for f in fields
    )
    data_uri = f"data:{mime or 'image/jpeg'};base64,{base64.b64encode(image_bytes).decode()}"
    system = (
        "You read a single document image (pay stub, ID, Social Security card, benefit "
        "letter, etc.) and extract ONLY values you can read clearly that correspond to the "
        "listed form fields. Never guess or infer a value you cannot actually see. For "
        "dates use MM/DD/YYYY. Respond as JSON: "
        '{"extractions":[{"field_key":"...","value":"...","confidence":0.0-1.0}]}.'
    )
    user_content = [
        {"type": "text", "text": f"Form fields you may fill:\n{field_lines}\n\nExtract matching values from this image."},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]
    model = getattr(settings, "OPENAI_VISION_MODEL", "") or settings.OPENAI_MODEL

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_content}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        logger.warning("Document OCR extraction failed.", exc_info=True)
        return {"ok": False, "error": "extraction_failed"}

    suggestions: list[dict] = []
    for item in (data.get("extractions") or []):
        fk = str((item or {}).get("field_key", "")).strip()
        raw = (item or {}).get("value")
        field = by_key.get(fk)
        if field is None or raw in (None, ""):
            continue
        try:
            value = validate_answer(field, str(raw))
        except ValidationError:
            continue  # a misread that doesn't validate is dropped, never offered
        suggestions.append({
            "field_key": fk,
            "label": field.get("label", fk),
            "value": value,
            "confidence": _clamp_confidence((item or {}).get("confidence")),
            "sensitive": bool(field.get("sensitive", False)),
        })
    # 🔒 metadata only — never log the extracted values (PHI).
    logger.info("Document OCR produced %d suggestion(s).", len(suggestions))
    return {"ok": True, "suggestions": suggestions, "source": "document_ocr"}


def _clamp_confidence(value: Any) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, c))
