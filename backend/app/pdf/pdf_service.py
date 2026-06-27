"""
PDF generation service.

If a form pack provides ``pdf.mapping.json`` and the referenced base PDF is present,
the service fills that AcroForm. Otherwise it generates a generic summary PDF from
the session's frozen schema, which keeps DB-created forms usable without custom PDF
assets on day one.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from app.core.config import get_settings
from app.db.models import FormAnswer, FormSession, GeneratedPdf
from app.forms import registry
from app.forms.service import get_all_fields_from_schema, load_form_schema

logger = logging.getLogger(__name__)

PDF_ASSET_DIR = Path(__file__).parent


def _load_mapping(form_id: str) -> tuple[dict, Path | None]:
    """Return the form pack mapping and its path, or ({}, None) for DB-only forms."""
    try:
        mapping_path = registry.pdf_mapping_path(form_id)
    except Exception:
        return {}, None
    if not mapping_path.exists():
        return {}, mapping_path
    with open(mapping_path, encoding="utf-8") as f:
        return json.load(f), mapping_path


def _get_base_pdf_path(form_id: str = "ODM_07216") -> Path | None:
    """Resolve the base PDF declared by the form's mapping."""
    mapping, mapping_path = _load_mapping(form_id)
    base_pdf = mapping.get("base_pdf")
    if not base_pdf:
        return None

    candidates: list[Path] = []
    if mapping_path is not None:
        candidates.append(mapping_path.parent / base_pdf)
    candidates.append(PDF_ASSET_DIR / base_pdf)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _get_output_dir() -> Path:
    settings = get_settings()
    out = Path(settings.PDF_OUTPUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _schema_for_session(session: FormSession) -> dict:
    """Return the schema snapshot stored on the session, falling back for legacy rows."""
    if session.schema_json:
        try:
            return json.loads(session.schema_json)
        except Exception:
            logger.warning("Invalid schema_json on session %s; falling back to live schema.", session.id)
    return load_form_schema(session.form_id)


def _safe_file_prefix(form_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", form_id).strip("_") or "form"


def _display_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in ("__skipped__", "", "null", "None"):
        return None
    return text


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in ("true", "yes", "on", "1")


def _checkbox_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("__skipped__", "", "null", "none", "false", "no"):
        return None
    return "On" if _truthy(value) else None


def _load_answers(db, session_id: str) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for row in db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all():
        try:
            answers[row.field_key] = json.loads(row.value_json) if row.value_json else None
        except Exception:
            answers[row.field_key] = row.value_json
    return answers


def generate_session_pdf(db, session_id: str) -> dict | None:
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if not session:
        return None

    schema = _schema_for_session(session)
    answers = _load_answers(db, session_id)
    base_pdf = _get_base_pdf_path(session.form_id)
    is_fallback = base_pdf is None

    if not is_fallback:
        try:
            file_path, file_name = _fill_acroform_pdf(session_id, answers, base_pdf, session.form_id)
        except Exception as exc:
            logger.warning("AcroForm fill failed (%s), using fallback summary PDF", exc)
            is_fallback = True

    if is_fallback:
        file_path, file_name = _generate_summary_pdf(session_id, answers, session.form_id, schema)

    record = GeneratedPdf(session_id=session_id, file_path=str(file_path), file_name=file_name)
    db.add(record)
    db.commit()

    return {
        "session_id": session_id,
        "download_url": f"/api/session/{session_id}/download-pdf",
        "file_name": file_name,
        "is_fallback": is_fallback,
    }


def _mapped_widget_value(raw: Any, mapping_entry: dict, widget_type: str) -> str | None:
    field_type_hint = mapping_entry.get("field_type", "")
    if field_type_hint == "checkbox" or widget_type == "CheckBox":
        if "check_when_value" in mapping_entry:
            return "On" if str(raw).strip().lower() == str(mapping_entry["check_when_value"]).lower() else None
        if "check_when" in mapping_entry:
            return "On" if _truthy(raw) == bool(mapping_entry["check_when"]) else None
        if "write_nonempty" in mapping_entry:
            return "On" if _display_value(raw) is not None else None
        return _checkbox_value(raw)

    if "write_nonempty" in mapping_entry:
        return mapping_entry["write_nonempty"] if _display_value(raw) is not None else None
    if "write_empty" in mapping_entry:
        return mapping_entry["write_empty"] if _display_value(raw) is None else None
    if "write_value_when" in mapping_entry and "static_value" in mapping_entry:
        return mapping_entry["static_value"] if _truthy(raw) == bool(mapping_entry["write_value_when"]) else None

    value = _display_value(raw)
    if value and mapping_entry.get("date_format") == "mm/dd/yyyy" and len(value) == 10 and value[4] == "-":
        try:
            yyyy, mm, dd = value.split("-")
            return f"{mm}/{dd}/{yyyy}"
        except Exception:
            return value
    return value


def _fill_acroform_pdf(session_id: str, answers: dict, base_pdf: Path, form_id: str) -> tuple[Path, str]:
    mapping, _mapping_path = _load_mapping(form_id)
    entries = mapping.get("fields") or []
    if not entries:
        raise RuntimeError(f"form {form_id} has no PDF mapping")

    doc = fitz.open(str(base_pdf))
    acroform_to_entries: dict[str, list[tuple[str, dict]]] = {}
    first_entry_by_key: dict[str, dict] = {}
    for entry in entries:
        field_key = entry.get("field_key")
        if not field_key:
            continue
        first_entry_by_key.setdefault(field_key, entry)
        acroform_name = entry.get("acroform_name")
        if acroform_name:
            acroform_to_entries.setdefault(acroform_name, []).append((field_key, entry))

    filled_keys: set[str] = set()
    for page in doc:
        widgets = page.widgets() or []
        for widget in widgets:
            if not widget.field_name:
                continue
            for field_key, entry in acroform_to_entries.get(widget.field_name, []):
                raw = answers.get(field_key)
                if entry.get("field_type") == "radio" or widget.field_type_string == "RadioButton":
                    on_state = entry.get("radio_on_state")
                    if not on_state:
                        continue
                    try:
                        if widget.on_state() != on_state:
                            continue
                    except Exception:
                        continue
                    if entry.get("use_check_when_value"):
                        select = str(raw).strip().lower() == str(entry.get("check_when_value", "")).lower()
                    else:
                        select = _truthy(raw) == bool(entry.get("check_when", True))
                    if select:
                        widget.field_value = on_state
                        widget.update()
                        filled_keys.add(field_key)
                    continue

                value = _mapped_widget_value(raw, entry, widget.field_type_string)
                if value is not None:
                    widget.field_value = value
                    widget.update()
                    filled_keys.add(field_key)

    # Fallback coordinate fill for mapped fields that were not AcroForm widgets.
    for field_key, entry in first_entry_by_key.items():
        if field_key in filled_keys:
            continue
        raw = answers.get(field_key)
        page_num = int(entry.get("page", 1)) - 1
        if page_num < 0 or page_num >= len(doc):
            continue
        page = doc[page_num]
        x, y = entry.get("x", 100), entry.get("y", 100)
        if entry.get("field_type") == "checkbox":
            if _checkbox_value(raw) is not None:
                page.insert_text(fitz.Point(x, y), "X", fontsize=12, color=(0, 0, 0))
            continue
        value = _mapped_widget_value(raw, entry, entry.get("field_type", ""))
        if value is not None:
            page.insert_text(
                fitz.Point(x, y),
                value,
                fontsize=entry.get("font_size", 10),
                color=(0, 0, 0),
            )

    file_name = f"{_safe_file_prefix(form_id)}_{session_id[:8]}.pdf"
    out_path = _get_output_dir() / file_name
    doc.save(str(out_path))
    doc.close()
    return out_path, file_name


def _generate_summary_pdf(session_id: str, answers: dict, form_id: str, schema: dict) -> tuple[Path, str]:
    """Generate a readable data-summary PDF from the session schema snapshot."""
    doc = fitz.open()
    all_fields = get_all_fields_from_schema(schema)
    section_titles = {s["section_key"]: s["section_title"] for s in schema.get("sections", [])}
    form_title = schema.get("form_title") or schema.get("title") or form_id

    sections: dict[str, list[tuple[str, Any, bool]]] = {}
    for field in all_fields:
        key = field["field_key"]
        value = answers.get(key)
        if _display_value(value) is None:
            continue
        sections.setdefault(field["section"], []).append(
            (field.get("label", key), value, bool(field.get("sensitive", False)))
        )

    page = doc.new_page(width=612, height=792)
    y = 750
    margin = 50

    def ensure_page() -> None:
        nonlocal page, y
        if y < 60:
            page = doc.new_page(width=612, height=792)
            y = 750

    page.insert_text(fitz.Point(margin, y), str(form_title)[:90], fontsize=13, color=(0, 0, 0.6))
    y -= 18
    page.insert_text(fitz.Point(margin, y), "Application Data Summary", fontsize=11, color=(0, 0, 0.6))
    y -= 14
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page.insert_text(fitz.Point(margin, y), f"Session: {session_id} | Generated: {stamp}", fontsize=8, color=(0.4, 0.4, 0.4))
    y -= 18
    page.draw_line(fitz.Point(margin, y), fitz.Point(612 - margin, y), color=(0, 0, 0), width=0.5)
    y -= 16

    for section_key, items in sections.items():
        ensure_page()
        page.insert_text(
            fitz.Point(margin, y),
            section_titles.get(section_key, section_key),
            fontsize=11,
            color=(0, 0, 0.5),
        )
        y -= 14
        for label, value, sensitive in items:
            ensure_page()
            display = "***" if sensitive else str(value)
            line = f"  {label}: {display}"
            if len(line) > 96:
                line = line[:93] + "..."
            page.insert_text(fitz.Point(margin, y), line, fontsize=9.5, color=(0, 0, 0))
            y -= 13
        y -= 5

    ensure_page()
    page.draw_line(fitz.Point(margin, 55), fitz.Point(612 - margin, 55), color=(0.6, 0.6, 0.6), width=0.3)
    page.insert_text(
        fitz.Point(margin, 43),
        "Review all answers before submitting. This summary is not an eligibility determination.",
        fontsize=7,
        color=(0.5, 0.5, 0.5),
    )

    file_name = f"{_safe_file_prefix(form_id)}_Summary_{session_id[:8]}.pdf"
    out_path = _get_output_dir() / file_name
    doc.save(str(out_path))
    doc.close()
    return out_path, file_name
