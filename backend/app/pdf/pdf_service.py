"""
PDF generation service for ODM 07216.

Strategy:
1. Try to fill AcroForm fields using PyMuPDF if the base PDF is present.
2. Fall back to a clean text-based summary PDF if the base PDF is missing or
   field mapping fails.

Place the base PDF at: backend/app/pdf/ODM07216fillx.pdf
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone

import fitz  # PyMuPDF

from app.core.config import get_settings
from app.db.models import FormAnswer, FormSession, GeneratedPdf
from app.forms import registry

logger = logging.getLogger(__name__)

BASE_PDF_NAME = "ODM07216fillx.pdf"


def _load_mapping(form_id: str) -> dict:
    """Load the AcroForm widget mapping for ``form_id`` from its form pack.

    The mapping location is resolved via :mod:`app.forms.registry` so each form
    carries its own ``pdf.mapping.json`` — this is what makes PDF generation
    multi-form rather than tied to the single ODM mapping.
    """
    with open(registry.pdf_mapping_path(form_id), encoding="utf-8") as f:
        return json.load(f)


def _get_base_pdf_path() -> Path | None:
    candidate = Path(__file__).parent / BASE_PDF_NAME
    if candidate.exists():
        return candidate
    return None


def _get_output_dir() -> Path:
    settings = get_settings()
    out = Path(settings.PDF_OUTPUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    return out


def generate_session_pdf(db, session_id: str) -> dict | None:
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if not session:
        return None

    answers_rows = db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
    answers: dict = {}
    for row in answers_rows:
        try:
            answers[row.field_key] = json.loads(row.value_json) if row.value_json else None
        except Exception:
            answers[row.field_key] = row.value_json

    base_pdf = _get_base_pdf_path()
    is_fallback = base_pdf is None

    if not is_fallback:
        try:
            file_path, file_name = _fill_acroform_pdf(session_id, answers, base_pdf, session.form_id)
        except Exception as exc:
            logger.warning("AcroForm fill failed (%s), using fallback summary PDF", exc)
            is_fallback = True

    if is_fallback:
        file_path, file_name = _generate_summary_pdf(session_id, answers, session.form_id)

    record = GeneratedPdf(
        session_id=session_id,
        file_path=str(file_path),
        file_name=file_name,
    )
    db.add(record)
    db.commit()

    download_url = f"/api/session/{session_id}/download-pdf"
    return {
        "session_id": session_id,
        "download_url": download_url,
        "file_name": file_name,
        "is_fallback": is_fallback,
    }


def _fill_acroform_pdf(session_id: str, answers: dict, base_pdf: Path, form_id: str) -> tuple[Path, str]:
    mapping = _load_mapping(form_id)
    # Build both a dict for single-entry lookup and a list for multi-entry fields
    # (e.g. a Yes checkbox and a No checkbox both keyed to the same field_key).
    all_entries = mapping.get("fields", [])
    field_map = {}
    for f in all_entries:
        fk = f["field_key"]
        if fk not in field_map:
            field_map[fk] = f  # first entry wins for coord fallback


    # Filter out skipped/null answers — nothing to write for these
    def _display_value(v) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        if s in ("__skipped__", "", "null", "None"):
            return None
        return s

    def _checkbox_value(v) -> str | None:
        """Return 'On' if the answer is truthy, None to leave unchecked."""
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in ("__skipped__", "", "null", "none", "false", "no"):
            return None
        if s in ("true", "yes", "on", "1"):
            return "On"
        return None

    doc = fitz.open(str(base_pdf))

    # Build a reverse map: acroform_name -> list of mapping entries.
    # Lists are needed because RadioButtons share the same acroform_name but have different
    # radio_on_state values (one per option), and checkbox Yes/No pairs also share names.
    acroform_to_entries: dict[str, list[tuple[str, dict]]] = {}
    for m in all_entries:
        aname = m.get("acroform_name")
        if aname:
            acroform_to_entries.setdefault(aname, []).append((m["field_key"], m))

    # Track which field_keys were successfully filled via AcroForm
    acroform_filled_keys: set[str] = set()

    for page in doc:
        for widget in page.widgets():
            if not widget.field_name:
                continue
            entries = acroform_to_entries.get(widget.field_name)
            if not entries:
                continue
            widget_type = widget.field_type_string

            for field_key, mapping_entry in entries:
                raw = answers.get(field_key)
                field_type_hint = mapping_entry.get("field_type", "")

                if field_type_hint == "radio" or widget_type == "RadioButton":
                    # RadioButton: each physical button has a unique on_state() export value.
                    # Only process the mapping entry whose radio_on_state matches THIS widget's
                    # on_state() — so we never apply the wrong option to the wrong button.
                    radio_on_state = mapping_entry.get("radio_on_state")
                    if radio_on_state is None:
                        continue
                    try:
                        this_widget_on_state = widget.on_state()
                    except Exception:
                        continue
                    if this_widget_on_state != radio_on_state:
                        continue  # this entry is for a different radio button in the group
                    # use_check_when_value: select this button when answer matches check_when_value string
                    if mapping_entry.get("use_check_when_value"):
                        cwv = mapping_entry.get("check_when_value", "")
                        should_select = str(raw).strip().lower() == cwv
                    else:
                        raw_bool = str(raw).strip().lower() in ("true", "yes", "on", "1")
                        should_select = raw_bool == mapping_entry.get("check_when", True)
                    if should_select:
                        widget.field_value = radio_on_state
                        widget.update()
                        acroform_filled_keys.add(field_key)
                elif field_type_hint == "checkbox" or widget_type == "CheckBox":
                    if "check_when_value" in mapping_entry:
                        value = "On" if str(raw).strip().lower() == mapping_entry["check_when_value"] else None
                    elif "check_when" in mapping_entry:
                        raw_bool = str(raw).strip().lower() in ("true", "yes", "on", "1")
                        value = "On" if raw_bool == mapping_entry["check_when"] else None
                    elif "write_nonempty" in mapping_entry:
                        has_value = raw is not None and str(raw).strip().lower() not in ("", "null", "none", "__skipped__", "no", "false")
                        value = "On" if has_value else None
                    else:
                        value = _checkbox_value(raw)
                    if value is not None:
                        widget.field_value = value
                        widget.update()
                        acroform_filled_keys.add(field_key)
                else:
                    # write_nonempty: write static_value (e.g. "Y") when answer is non-empty/truthy
                    if "write_nonempty" in mapping_entry:
                        has_value = raw is not None and str(raw).strip().lower() not in ("", "null", "none", "__skipped__", "no", "false")
                        value = mapping_entry["write_nonempty"] if has_value else None
                    # write_empty: write static_value (e.g. "N") when answer is empty/falsy/skipped
                    elif "write_empty" in mapping_entry:
                        has_value = raw is not None and str(raw).strip().lower() not in ("", "null", "none", "__skipped__", "no", "false")
                        value = mapping_entry["write_empty"] if not has_value else None
                    # write_value_when + static_value: write static_value when bool answer matches write_value_when
                    elif "write_value_when" in mapping_entry and "static_value" in mapping_entry:
                        raw_bool = str(raw).strip().lower() in ("true", "yes", "on", "1") if raw is not None else False
                        value = mapping_entry["static_value"] if raw_bool == mapping_entry["write_value_when"] else None
                    else:
                        value = _display_value(raw)
                        if value is not None:
                            # Convert ISO date (YYYY-MM-DD) to MM/DD/YYYY if the field expects that format
                            if mapping_entry.get("date_format") == "mm/dd/yyyy" and len(value) == 10 and value[4] == "-":
                                try:
                                    parts = value.split("-")
                                    value = "%s/%s/%s" % (parts[1], parts[2], parts[0])
                                except Exception:
                                    pass
                    if value is not None:
                        widget.field_value = value
                        widget.update()
                        acroform_filled_keys.add(field_key)

    # Coordinate-based fill for any field NOT matched via AcroForm widgets
    for field_key, m in field_map.items():
        if field_key in acroform_filled_keys:
            continue
        raw = answers.get(field_key)
        is_checkbox = m.get("field_type") == "checkbox"
        if is_checkbox:
            value = _checkbox_value(raw)
            if value is None:
                continue
            # Draw a visible checkmark at the coordinate
            page_num = m.get("page", 1) - 1
            if page_num < len(doc):
                page = doc[page_num]
                x, y = m.get("x", 100), m.get("y", 100)
                page.insert_text(fitz.Point(x, y), "✓", fontsize=12, color=(0, 0, 0))
        else:
            value = _display_value(raw)
            if value is None:
                continue
            page_num = m.get("page", 1) - 1
            if page_num < len(doc):
                page = doc[page_num]
                x, y = m.get("x", 100), m.get("y", 100)
                font_size = m.get("font_size", 10)
                page.insert_text(
                    fitz.Point(x, y),
                    value,
                    fontsize=font_size,
                    color=(0, 0, 0),
                )

    file_name = f"ODM07216_{session_id[:8]}.pdf"
    out_path = _get_output_dir() / file_name
    doc.save(str(out_path))
    doc.close()
    return out_path, file_name


def _generate_summary_pdf(session_id: str, answers: dict, form_id: str) -> tuple[Path, str]:
    """Generate a clean filled-data summary PDF as fallback."""
    from app.forms.service import get_all_fields, load_form_schema

    doc = fitz.open()
    schema = load_form_schema(form_id)
    all_fields = get_all_fields(form_id)
    field_labels = {f["field_key"]: f["label"] for f in all_fields}
    section_titles = {s["section_key"]: s["section_title"] for s in schema["sections"]}

    # Group answers by section
    sections: dict[str, list] = {}
    for field in all_fields:
        key = field["field_key"]
        sec = field["section"]
        if sec not in sections:
            sections[sec] = []
        value = answers.get(key)
        if value is not None and str(value).strip() not in ("__skipped__", "", "null", "None"):
            sections[sec].append((field["label"], value, field.get("sensitive", False)))

    page = doc.new_page(width=612, height=792)
    y = 750
    margin = 50
    font_size = 10
    title_font_size = 14
    section_font_size = 11

    # Title
    page.insert_text(fitz.Point(margin, y), "Ohio Department of Medicaid", fontsize=title_font_size, color=(0, 0, 0.6))
    y -= 20
    page.insert_text(fitz.Point(margin, y), "Application for Health Coverage & Help Paying Costs", fontsize=title_font_size - 1, color=(0, 0, 0.6))
    y -= 15
    page.insert_text(fitz.Point(margin, y), "DRAFT - Application Data Summary (Fallback PDF)", fontsize=font_size, color=(0.8, 0.1, 0.1))
    y -= 10
    page.insert_text(fitz.Point(margin, y), f"Session: {session_id}  |  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", fontsize=8, color=(0.4, 0.4, 0.4))
    y -= 20
    page.draw_line(fitz.Point(margin, y), fitz.Point(612 - margin, y), color=(0, 0, 0), width=0.5)
    y -= 15

    def ensure_page():
        nonlocal page, y
        if y < 60:
            page = doc.new_page(width=612, height=792)
            y = 750

    for sec_key, items in sections.items():
        if not items:
            continue
        ensure_page()
        title = section_titles.get(sec_key, sec_key)
        page.insert_text(fitz.Point(margin, y), title, fontsize=section_font_size, color=(0, 0, 0.5))
        y -= 14
        page.draw_line(fitz.Point(margin, y + 2), fitz.Point(612 - margin, y + 2), color=(0.6, 0.6, 0.8), width=0.3)
        y -= 6

        for label, value, sensitive in items:
            ensure_page()
            display_val = "***" if sensitive else str(value)
            text = f"  {label}: {display_val}"
            if len(text) > 90:
                text = text[:87] + "..."
            page.insert_text(fitz.Point(margin, y), text, fontsize=font_size, color=(0, 0, 0))
            y -= 13

        y -= 6

    # Disclaimer footer on last page
    ensure_page()
    page.draw_line(fitz.Point(margin, 55), fitz.Point(612 - margin, 55), color=(0.6, 0.6, 0.6), width=0.3)
    page.insert_text(fitz.Point(margin, 45), "DISCLAIMER: This summary assists form completion but does not determine eligibility or provide legal advice.", fontsize=7, color=(0.5, 0.5, 0.5))
    page.insert_text(fitz.Point(margin, 35), "Please review all answers before submitting or using this PDF. This is a DRAFT — place the base PDF to enable field-filled output.", fontsize=7, color=(0.5, 0.5, 0.5))

    file_name = f"ODM07216_Summary_{session_id[:8]}.pdf"
    out_path = _get_output_dir() / file_name
    doc.save(str(out_path))
    doc.close()
    return out_path, file_name
