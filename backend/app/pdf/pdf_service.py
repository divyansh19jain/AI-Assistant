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
from app.forms.missing_fields import SKIPPED, get_applicable_answers
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
    if text in (SKIPPED, "", "null", "None") or text.lower() == "skipped":
        return None
    return text


def _is_skipped(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() in (SKIPPED.lower(), "skipped")


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in ("true", "yes", "on", "1")


def _checkbox_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in (SKIPPED, "", "null", "none", "false", "no", "skipped"):
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
    answers = get_applicable_answers(schema, _load_answers(db, session_id))
    base_pdf = _get_base_pdf_path(session.form_id)
    is_fallback = base_pdf is None

    if not is_fallback:
        try:
            file_path, file_name = _fill_acroform_pdf(session_id, answers, base_pdf, session.form_id, schema)
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


def _schema_field_types(schema: dict) -> dict[str, str]:
    """Return field_key -> field type from the frozen schema snapshot."""
    return {
        field["field_key"]: field.get("type", "text")
        for section in schema.get("sections", [])
        for field in section.get("fields", [])
        if field.get("field_key")
    }


def _entry_with_schema_defaults(entry: dict, field_type_by_key: dict[str, str]) -> dict:
    """Apply PDF-fill defaults that are implied by the form schema.

    The ODM pack stores dates normalized as YYYY-MM-DD, while the official PDF
    date fields ask for mm/dd/yyyy. Treat schema ``type: date`` as that default
    unless a mapping row opts into a different date_format.
    """
    if field_type_by_key.get(entry.get("field_key", "")) == "date" and "date_format" not in entry:
        return {**entry, "date_format": "mm/dd/yyyy"}
    return entry


def _mapped_widget_value(raw: Any, mapping_entry: dict, widget_type: str) -> str | None:
    if _is_skipped(raw):
        return None
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


def _fill_acroform_pdf(
    session_id: str,
    answers: dict,
    base_pdf: Path,
    form_id: str,
    schema: dict,
) -> tuple[Path, str]:
    mapping, _mapping_path = _load_mapping(form_id)
    entries = mapping.get("fields") or []
    if not entries:
        raise RuntimeError(f"form {form_id} has no PDF mapping")

    doc = fitz.open(str(base_pdf))
    field_type_by_key = _schema_field_types(schema)
    acroform_to_entries: dict[str, list[tuple[str, dict]]] = {}
    first_entry_by_key: dict[str, dict] = {}
    for entry in entries:
        field_key = entry.get("field_key")
        if not field_key:
            continue
        entry = _entry_with_schema_defaults(entry, field_type_by_key)
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
                if field_key not in answers:
                    continue
                raw = answers.get(field_key)
                if entry.get("field_type") == "radio" or widget.field_type_string == "RadioButton":
                    if _is_skipped(raw):
                        continue
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
                    # Force readable black text — several ODM form fields ship with a
                    # light default appearance that's hard to read once filled.
                    try:
                        widget.text_color = (0, 0, 0)
                        if not widget.text_fontsize or widget.text_fontsize < 9:
                            widget.text_fontsize = 10
                    except Exception:
                        pass
                    widget.update()
                    filled_keys.add(field_key)

    # Fallback coordinate fill for mapped fields that were not AcroForm widgets.
    for field_key, entry in first_entry_by_key.items():
        if field_key in filled_keys:
            continue
        if field_key not in answers:
            continue
        raw = answers.get(field_key)
        page_num = int(entry.get("page", 1)) - 1
        if page_num < 0 or page_num >= len(doc):
            continue
        page = doc[page_num]
        x, y = entry.get("x", 100), entry.get("y", 100)
        if entry.get("field_type") == "checkbox":
            if _mapped_widget_value(raw, entry, "CheckBox") is not None:
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

    # Append continuation pages for person3, person4, person5 (and beyond).
    # The base PDF only has slots for person1 and person2; additional household members
    # are stamped onto fresh copies of the person2 pages (matching the form's own
    # "make a copy of the pages and attach them" instruction).
    _append_extra_person_pages(doc, base_pdf, entries, answers, field_type_by_key)

    file_name = f"{_safe_file_prefix(form_id)}_{session_id[:8]}.pdf"
    out_path = _get_output_dir() / file_name
    doc.save(str(out_path))
    doc.close()
    return out_path, file_name


def _append_extra_person_pages(
    doc: "fitz.Document",
    base_pdf: Path,
    entries: list[dict],
    answers: dict,
    field_type_by_key: dict[str, str],
) -> None:
    """Copy the person2 pages from the base PDF and stamp person3+ data onto them.

    For each additional person whose gate field (personN.adding_personN) is True,
    we append blank copies of the person2 source pages and write the person's answers
    at the same x/y coordinates the person2 mapping uses.  AcroForm widgets on the
    copied pages are flattened (the copy comes from the blank base PDF) so we always
    use coordinate-based insertion — no widget conflicts with the already-filled pages.
    """
    # Build a lookup: field suffix -> person2 mapping entries (one per PDF entry row).
    # e.g. "first_name" -> [{"page": 8, "x": 130, "y": 695, ...}, ...]
    p2_suffix_to_entries: dict[str, list[dict]] = {}
    p2_pages: set[int] = set()
    for entry in entries:
        fk = entry.get("field_key", "")
        if not fk.startswith("person2."):
            continue
        suffix = fk[len("person2."):]
        entry = _entry_with_schema_defaults(entry, field_type_by_key)
        p2_suffix_to_entries.setdefault(suffix, []).append(entry)
        pg = int(entry.get("page", 1))
        if pg > 0:
            p2_pages.add(pg)

    if not p2_suffix_to_entries:
        return  # no person2 mapping — nothing to copy

    # Sorted page numbers (1-indexed) that make up the "person2 template".
    template_pages_1idx = sorted(p2_pages)

    # Insert position: right after person 2's last page so all household members
    # are grouped together before the income/coverage sections.
    # 0-indexed: last person2 page in the base PDF.
    insert_after_0idx = max(template_pages_1idx) - 1  # e.g. page 9 → index 8

    # Discover extra persons: any personN (N >= 3) whose gate answer is True.
    extra_ns = sorted(
        int(m.group(1))
        for k, v in answers.items()
        if (m := re.match(r"^person(\d+)\.adding_person\d+$", k))
        and int(m.group(1)) >= 3
        and _truthy(v)
    )
    if not extra_ns:
        return

    # Open a fresh (unfilled) copy of the base PDF to pull clean template pages from.
    try:
        base_doc = fitz.open(str(base_pdf))
    except Exception:
        logger.warning("Could not open base PDF for extra person pages: %s", base_pdf)
        return

    try:
        # Track how many pages we've inserted so far; each block shifts the insertion point.
        pages_inserted = 0

        for n in extra_ns:
            prefix = f"person{n}"
            # Map from each template page (1-indexed) to its new 0-indexed position in doc.
            new_page_by_template: dict[int, int] = {}
            for i, pg_1idx in enumerate(template_pages_1idx):
                src_pg_0idx = pg_1idx - 1
                if src_pg_0idx < 0 or src_pg_0idx >= len(base_doc):
                    continue
                # Insert right after person 2's block (shifted by how many we've added).
                dest = insert_after_0idx + 1 + pages_inserted + i
                doc.insert_pdf(base_doc, from_page=src_pg_0idx, to_page=src_pg_0idx,
                               start_at=dest)
                new_page_by_template[pg_1idx] = dest

            pages_inserted += len(new_page_by_template)
            if not new_page_by_template:
                continue

            if not new_page_by_template:
                continue

            # Add a "Person N (Continuation)" header on the first appended page.
            first_new_pg = doc[new_page_by_template[template_pages_1idx[0]]]
            first_new_pg.insert_text(
                fitz.Point(35, 35),
                f"Person {n} (Continuation Sheet)",
                fontsize=11,
                color=(0, 0, 0.6),
            )

            # Stamp personN answers onto the new pages using person2 coordinates.
            for suffix, p2_entries in p2_suffix_to_entries.items():
                field_key = f"{prefix}.{suffix}"
                raw = answers.get(field_key)
                if raw is None:
                    continue
                for entry in p2_entries:
                    src_pg_1idx = int(entry.get("page", 1))
                    new_pg_0idx = new_page_by_template.get(src_pg_1idx)
                    if new_pg_0idx is None:
                        continue
                    new_page = doc[new_pg_0idx]
                    x, y = entry.get("x", 100), entry.get("y", 100)
                    field_type_hint = entry.get("field_type", "")

                    if field_type_hint == "checkbox" or field_type_hint == "CheckBox":
                        if _mapped_widget_value(raw, entry, "CheckBox") is not None:
                            new_page.insert_text(fitz.Point(x, y), "X", fontsize=12, color=(0, 0, 0))
                        continue

                    if field_type_hint == "radio":
                        if _mapped_widget_value(raw, entry, "RadioButton") is not None:
                            new_page.insert_text(fitz.Point(x, y), "●", fontsize=10, color=(0, 0, 0))
                        continue

                    value = _mapped_widget_value(raw, entry, field_type_hint)
                    if value is not None:
                        new_page.insert_text(
                            fitz.Point(x, y),
                            value,
                            fontsize=entry.get("font_size", 10),
                            color=(0, 0, 0),
                        )
    finally:
        base_doc.close()


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
            shown = _display_value(value)
            display = "—" if shown is None else ("***" if sensitive else shown)
            line = f"  {label}: {display}"
            if len(line) > 96:
                line = line[:93] + "..."
            page.insert_text(fitz.Point(margin, y), line, fontsize=9.5, color=(0, 0, 0))
            y -= 13
        y -= 5

    try:
        from app.clinical.scoring import score_clinical_battery

        clinical_scores = score_clinical_battery(form_id, answers)
    except Exception:
        clinical_scores = []
    if clinical_scores:
        ensure_page()
        page.insert_text(fitz.Point(margin, y), "Clinical Screening Scores", fontsize=11, color=(0, 0, 0.5))
        y -= 14
        for score in clinical_scores:
            ensure_page()
            items = ""
            if score.get("answered_items") is not None and score.get("total_items") is not None:
                items = f"; items {score.get('answered_items')}/{score.get('total_items')}"
            line = (
                f"  {score['title']}: score {score.get('total_score')}/{score.get('max_score')}{items} - "
                f"{score.get('interpretation', '')}"
            )
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
