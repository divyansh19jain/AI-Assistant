import json
from types import SimpleNamespace


def _row(key, value, source="user", confidence=1.0):
    return SimpleNamespace(field_key=key, value_json=json.dumps(value), source=source, confidence=confidence)


_CONSISTENCY_SCHEMA = {
    "form_id": "ODM_07216",
    "form_title": "Consistency",
    "version": "1.0",
    "sections": [
        {
            "section_key": "s",
            "section_title": "Person 1",
            "fields": [
                {"field_key": "person1.dob", "label": "Date of Birth", "section": "s", "type": "date", "required": True},
                {"field_key": "person1.sex", "label": "Sex", "section": "s", "type": "select", "required": True,
                 "validation_rule": {"allowed_values": ["Male", "Female", "Other"]}},
            ],
        }
    ],
}


def test_future_birthdate_is_a_warning_not_a_blocker():
    """A future DOB is surfaced for re-check but must NOT hard-block approval (a single
    odd-but-valid value should never strand a real application)."""
    from app.forms.readiness import build_session_readiness

    report = build_session_readiness("ODM_07216", _CONSISTENCY_SCHEMA, [_row("person1.dob", "2099-01-01")])
    assert any(w["kind"] == "future_date" for w in report["warnings"])
    assert not any(b["kind"] == "future_date" for b in report["blockers"])


def test_implausible_birthdate_is_a_warning_not_a_blocker():
    from app.forms.readiness import build_session_readiness

    report = build_session_readiness("ODM_07216", _CONSISTENCY_SCHEMA, [_row("person1.dob", "1850-01-01")])
    assert any(w["kind"] == "implausible_date" for w in report["warnings"])
    assert not any(b["kind"] == "implausible_date" for b in report["blockers"])


def test_normal_birthdate_has_no_date_warnings():
    from app.forms.readiness import build_session_readiness

    report = build_session_readiness("ODM_07216", _CONSISTENCY_SCHEMA, [_row("person1.dob", "1990-05-15")])
    assert not any(w["kind"] in {"future_date", "implausible_date"} for w in report["warnings"])


def test_income_screen_includes_effective_date_and_verify_note():
    from app.ai.odm_eligibility import screen_magi_income

    result = screen_magi_income("adult_19_64", household_size=2, monthly_income=2000)
    assert result["effective_date"] == "2026-03-01"
    assert "confirm current limits" in result["verify"].lower()
