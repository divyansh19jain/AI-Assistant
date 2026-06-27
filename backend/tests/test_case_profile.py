import json
from types import SimpleNamespace

from app.ai.case_profile import build_case_profile, render_case_notes


def _row(key, value, source="user", confidence=1.0):
    return SimpleNamespace(field_key=key, value_json=json.dumps(value), source=source, confidence=confidence)


_SCHEMA = {
    "form_id": "ODM_07216",
    "form_title": "T",
    "version": "1.0",
    "sections": [
        {
            "section_key": "s",
            "section_title": "S",
            "fields": [
                {"field_key": "applicant.first_name", "label": "First Name", "section": "s", "type": "text", "required": True},
                {"field_key": "applicant.last_name", "label": "Last Name", "section": "s", "type": "text", "required": True},
                {"field_key": "person1.first_name", "label": "P1 First", "section": "s", "type": "text", "required": True},
                {"field_key": "person1.dob", "label": "Date of Birth", "section": "s", "type": "date", "required": True},
            ],
        }
    ],
}


def test_case_profile_classifies_answers():
    rows = [
        _row("applicant.first_name", "Tony"),                                # answered (user)
        _row("person1.first_name", "Tony", source="carry_forward"),          # inferred
        _row("person1.dob", "1990-05-15", source="voice", confidence=0.4),   # low confidence
    ]
    profile = build_case_profile("ODM_07216", _SCHEMA, rows)

    assert "applicant.first_name" in profile["do_not_reask"]
    assert "person1.first_name" in profile["inferred"]
    assert "person1.dob" in profile["needs_confirmation"]
    assert "applicant.last_name" in profile["remaining"]


def test_case_notes_are_instructional_and_phi_safe():
    rows = [_row("person1.dob", "1990-05-15", source="voice", confidence=0.4)]
    notes = render_case_notes(build_case_profile("ODM_07216", _SCHEMA, rows))

    assert "do not ask again" in notes.lower()
    assert "read these back" in notes.lower()
    # The value itself must never leak into the agent context (PHI-safe).
    assert "1990-05-15" not in notes
