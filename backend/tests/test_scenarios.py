"""Scenario harness — scripted "real people" driven through ODM_07216 end to end.

This validates the case-manager *machine* deterministically (no LLM key needed): for
each persona it answers required fields and skips optional ones, branch by branch, and
checks the session reaches a gathered-complete state with nothing missing, invalid, or
low-confidence. It also exercises the correction path (a person who changes a gating
answer mid-way). The conversational phrasing is the LLM's job and is tested separately;
here we prove the gathering, branching, carry-forward, and correction logic hold up
across realistic household shapes.

Extend PERSONAS with more shapes (parent with kids via person2, pregnant, elderly
Medicare, disabled, self-employed, mixed-immigration) as those branches are filled in.
"""

from app.forms.missing_fields import get_missing_applicable_fields
from app.sessions import service as svc
from app.db.models import FormSession


def _value_for(field: dict, persona: dict):
    """A type-valid default that satisfies the field's validation rule, with persona
    overrides for the branch-defining answers."""
    key = field["field_key"]
    if key in persona:
        return persona[key]
    ftype = field.get("type", "text")
    rule = field.get("validation_rule") or {}
    if ftype == "boolean":
        return False
    if ftype == "select":
        allowed = rule.get("allowed_values") or []
        return allowed[0] if allowed else "Test"
    if ftype == "date":
        return "1990-05-15"
    if ftype == "ssn":
        return "123456789"
    if ftype == "phone":
        return "5551234567"
    if ftype == "email":
        return "test@example.com"
    if ftype == "number":
        return str(rule.get("min", 1))
    # text
    pattern = rule.get("pattern", "")
    if r"\d{5}" in pattern:
        return "43215"
    if r"\d{10}" in pattern:
        return "5551234567"
    # Personal-name fields reject non-name placeholders ("Test"), so use a real name.
    label_l = str(field.get("label", "")).lower()
    if any(w in label_l for w in ("first name", "last name", "middle name", "full name", "maiden name")):
        return "Jordan"
    base = "Test"
    max_len = rule.get("max_length")
    if max_len and max_len < len(base):
        base = ("OH" if max_len >= 2 else "X")[:max_len]
    min_len = rule.get("min_length", 1)
    if len(base) < min_len:
        base += "x" * (min_len - len(base))
    return base


def _new_session(db):
    state = svc.create_session(db, form_id="ODM_07216", patient_id=None, manual_mode=True)
    session = db.query(FormSession).filter(FormSession.id == state["session_id"]).first()
    return state["session_id"], session, svc._schema_for_session(session)


def _drive_to_complete(db, sid, session, schema, persona, max_steps=400):
    """Answer required / skip optional, one missing field at a time, until gathered.

    The loop uses the cheap missing-field check; full readiness (which re-audits the
    PDF mapping) is computed once at the end for the assertions.
    """
    for _ in range(max_steps):
        answers = svc._answers_map(db, sid)
        missing = get_missing_applicable_fields("ODM_07216", answers, schema)
        if not missing:
            break
        field = missing[0]
        if field.get("required"):
            result = svc.set_field(db, session, schema, field["field_key"], _value_for(field, persona))
            assert result["ok"], f"could not fill {field['field_key']}: {result.get('error')}"
        else:
            svc.skip_field(db, sid, field["field_key"])
    else:
        raise AssertionError("persona did not reach completion within step budget")
    return svc.get_session_readiness(db, sid)


PERSONAS = {
    "single_adult_no_income": {"income.has_employment": "not_employed"},
    "employed_applicant": {"income.has_employment": "employed"},
    "homeless_applicant": {"applicant.is_homeless": True},
}


import pytest


@pytest.mark.parametrize("name", list(PERSONAS))
def test_persona_reaches_gathered_complete(db, name):
    sid, session, schema = _new_session(db)
    readiness = _drive_to_complete(db, sid, session, schema, PERSONAS[name])
    summary = readiness["summary"]
    assert summary["missing_required_fields"] == 0
    assert summary["missing_fields"] == 0
    assert summary["invalid_fields"] == 0
    assert summary["low_confidence_fields"] == 0


def test_homeless_persona_never_asked_home_address(db):
    sid, session, schema = _new_session(db)
    _drive_to_complete(db, sid, session, schema, PERSONAS["homeless_applicant"])
    answers = svc._answers_map(db, sid)
    # The home-address branch is gated off when homeless, so it is never collected.
    assert "applicant.home_address" not in answers


def test_corrector_persona_revises_the_model(db):
    """A person says they have a home, gives the address, then corrects to homeless."""
    sid, session, schema = _new_session(db)

    svc.set_field(db, session, schema, "applicant.is_homeless", "no")
    svc.set_field(db, session, schema, "applicant.home_address", "123 Main St")
    assert svc._answers_map(db, sid).get("applicant.home_address") == "123 Main St"

    # Correction: now homeless -> the home address is no longer applicable and is cleared.
    svc.set_field(db, session, schema, "applicant.is_homeless", "yes")
    assert "applicant.home_address" not in svc._answers_map(db, sid)

    # And the persona can still be completed afterwards.
    readiness = _drive_to_complete(db, sid, session, schema, {"applicant.is_homeless": True})
    assert readiness["summary"]["missing_fields"] == 0
