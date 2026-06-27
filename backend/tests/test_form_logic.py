"""Tests for form prefill, missing fields, dependencies, and validation."""

import pytest
from app.emr.schemas import EMRPatient, EMRAddress
from app.forms.mapper import prefill_from_emr
from app.forms.missing_fields import get_missing_applicable_fields, get_missing_required_fields, _dependency_satisfied
from app.forms.validation import validate_answer, ValidationError
from app.forms.service import get_all_fields


SAMPLE_PATIENT = EMRPatient(
    external_patient_id="test-001",
    first_name="Alice",
    middle_name="B",
    last_name="Smith",
    dob="1985-03-12",
    sex="Female",
    phone="6145559876",
    email="alice@example.com",
    address=EMRAddress(
        line1="100 Test Ave",
        line2="Apt 1",
        city="Columbus",
        state="OH",
        zip="43215",
        county="Franklin",
    ),
)


def test_prefill_from_emr_basic():
    prefilled = prefill_from_emr(SAMPLE_PATIENT)
    assert prefilled["applicant.first_name"]["value"] == "Alice"
    assert prefilled["applicant.last_name"]["value"] == "Smith"
    assert prefilled["applicant.city"]["value"] == "Columbus"
    # The mapper formats dates to MM/DD/YYYY for the form (see mapper._format_dob),
    # so the stored prefill value is display-formatted, not the EMR's ISO string.
    assert prefilled["person1.dob"]["value"] == "03/12/1985"
    assert prefilled["applicant.first_name"]["source"] == "emr"


def test_prefill_does_not_include_null_values():
    patient = EMRPatient(
        external_patient_id="test-002",
        first_name="Bob",
        last_name="Jones",
        middle_name=None,
        phone=None,
    )
    prefilled = prefill_from_emr(patient)
    assert "applicant.middle_name" not in prefilled
    assert "applicant.phone" not in prefilled


def test_missing_required_fields_empty_answers():
    missing = get_missing_required_fields("ODM_07216", {})
    required_keys = {f["field_key"] for f in missing}
    assert "applicant.first_name" in required_keys
    assert "applicant.last_name" in required_keys
    assert "person1.dob" in required_keys
    assert "applicant.middle_name" not in required_keys


def test_applicable_fields_include_optional_until_skipped():
    applicable = get_missing_applicable_fields("ODM_07216", {})
    keys = {f["field_key"] for f in applicable}
    assert "applicant.middle_name" in keys


def test_missing_required_fields_with_prefill():
    prefilled = prefill_from_emr(SAMPLE_PATIENT)
    answers = {k: v["value"] for k, v in prefilled.items()}
    missing = get_missing_required_fields("ODM_07216", answers)
    missing_keys = {f["field_key"] for f in missing}
    assert "applicant.first_name" not in missing_keys
    assert "applicant.last_name" not in missing_keys


def test_dependency_skip_pregnancy_fields():
    answers = {"person1.pregnant": False}
    all_fields = get_all_fields("ODM_07216")
    pregnancy_due = next(f for f in all_fields if f["field_key"] == "person1.pregnancy_due_date")
    assert not _dependency_satisfied(pregnancy_due, answers)


def test_skip_sentinel_does_not_satisfy_present_dependency():
    answers = {"applicant.mailing_address": "__skipped__"}
    all_fields = get_all_fields("ODM_07216")
    mailing_city = next(f for f in all_fields if f["field_key"] == "applicant.mailing_city")
    assert not _dependency_satisfied(mailing_city, answers)


def test_dependency_include_pregnancy_fields_when_pregnant():
    answers = {"person1.pregnant": True}
    all_fields = get_all_fields("ODM_07216")
    pregnancy_due = next(f for f in all_fields if f["field_key"] == "person1.pregnancy_due_date")
    assert _dependency_satisfied(pregnancy_due, answers)


def test_dependency_immigration_skipped_for_citizen():
    answers = {"person1.us_citizen_or_national": True}
    all_fields = get_all_fields("ODM_07216")
    imm_doc = next(f for f in all_fields if f["field_key"] == "person1.immigration_document_type")
    assert not _dependency_satisfied(imm_doc, answers)


def test_validate_boolean_yes():
    field = {"type": "boolean", "required": True, "validation_rule": {}}
    assert validate_answer(field, "yes") is True
    assert validate_answer(field, "yeah") is True
    assert validate_answer(field, "no") is False
    assert validate_answer(field, "nope") is False


def test_validate_boolean_invalid():
    field = {"type": "boolean", "required": True, "validation_rule": {}}
    with pytest.raises(ValidationError):
        validate_answer(field, "maybe")


def test_validate_date_formats():
    field = {"type": "date", "required": True, "validation_rule": {"format": "date"}}
    assert validate_answer(field, "01/15/1990") == "1990-01-15"
    assert validate_answer(field, "1990-01-15") == "1990-01-15"


def test_validate_phone():
    field = {"type": "phone", "required": True, "validation_rule": {"pattern": r"^\d{10}$"}}
    assert validate_answer(field, "6145551234") == "6145551234"
    assert validate_answer(field, "(614) 555-1234") == "6145551234"


def test_validate_state_name_and_spoken_date():
    state_field = {
        "field_key": "applicant.state",
        "label": "State",
        "type": "text",
        "required": True,
        "validation_rule": {"min_length": 2, "max_length": 2},
    }
    assert validate_answer(state_field, "Ohio") == "OH"
    assert validate_answer(state_field, "Ohio 61459 9800") == "OH"

    date_field = {"type": "date", "required": True, "validation_rule": {"format": "date"}}
    assert validate_answer(date_field, "January 5th 1980") == "1980-01-05"


def test_validate_zip_pattern():
    field = {"type": "text", "required": True, "validation_rule": {"pattern": r"^\d{5}(-\d{4})?$"}}
    assert validate_answer(field, "43215") == "43215"
    with pytest.raises(ValidationError):
        validate_answer(field, "ABCDE")


def test_declarative_prefill_from_schema():
    schema = {
        "sections": [
            {
                "section_key": "s",
                "section_title": "S",
                "fields": [
                    {"field_key": "s.name", "label": "Name", "section": "s", "type": "text"},
                    {"field_key": "s.phone", "label": "Phone", "section": "s", "type": "phone"},
                ],
            }
        ],
        "prefill": {
            "s.name": {"source": "first_name"},
            "s.phone": {"source": "phone", "transform": "phone10"},
        },
    }
    prefilled = prefill_from_emr(SAMPLE_PATIENT, "ANY", schema=schema)
    assert prefilled["s.name"]["value"] == "Alice"
    assert prefilled["s.phone"]["value"] == "6145559876"


def test_odm_pdf_mapping_has_no_stale_schema_keys():
    import json
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[1]
    schema = json.loads((backend_root / "app/forms/packs/ODM_07216/form.schema.json").read_text(encoding="utf-8"))
    mapping = json.loads((backend_root / "app/forms/packs/ODM_07216/pdf.mapping.json").read_text(encoding="utf-8"))
    fields = [f for sec in schema["sections"] for f in sec["fields"]]
    schema_keys = {f["field_key"] for f in fields}
    mapping_keys = {f["field_key"] for f in mapping["fields"]}
    assert mapping_keys <= schema_keys

    # Every non-excluded schema field should either fill a real ODM PDF widget or
    # be intentionally marked pdf_exclude because the official PDF has no matching
    # control at this schema granularity.
    uncovered = sorted(
        f["field_key"]
        for f in fields
        if not f.get("pdf_exclude") and f["field_key"] not in mapping_keys
    )
    assert uncovered == []


def test_odm_pdf_mapping_targets_real_committed_pdf_widgets():
    import json
    from pathlib import Path

    import fitz
    from app.pdf.pdf_service import _get_base_pdf_path

    backend_root = Path(__file__).resolve().parents[1]
    mapping = json.loads((backend_root / "app/forms/packs/ODM_07216/pdf.mapping.json").read_text(encoding="utf-8"))
    base_pdf = _get_base_pdf_path("ODM_07216")

    assert base_pdf is not None
    assert base_pdf.name == "ODM07216fillx.pdf"
    assert base_pdf.exists()

    doc = fitz.open(str(base_pdf))
    try:
        widgets = {
            widget.field_name
            for page in doc
            for widget in (page.widgets() or [])
            if widget.field_name
        }
    finally:
        doc.close()

    assert len(widgets) > 900
    missing = sorted(
        {
            entry["acroform_name"]
            for entry in mapping["fields"]
            if entry.get("acroform_name") and entry["acroform_name"] not in widgets
        }
    )
    assert missing == []
