"""Correction-aware inference: changing a gating answer revises the rest of the
interview (now-inapplicable answers are cleared, not left orphaned)."""

from app.sessions import service as svc
from app.db.models import FormSession


def _new_odm_session(db):
    state = svc.create_session(db, form_id="ODM_07216", patient_id=None, manual_mode=True)
    session = db.query(FormSession).filter(FormSession.id == state["session_id"]).first()
    return state["session_id"], session, svc._schema_for_session(session)


def test_changing_a_gate_clears_now_inapplicable_answer(db):
    sid, session, schema = _new_odm_session(db)

    # Not homeless -> home address applies; answer it.
    svc.set_field(db, session, schema, "applicant.is_homeless", "no")
    svc.set_field(db, session, schema, "applicant.home_address", "123 Main St")
    answers = svc._answers_map(db, sid)
    assert answers.get("applicant.home_address") == "123 Main St"

    # Correct to homeless -> home address no longer applies -> it is cleared,
    # so a stale value can't linger or silently reappear later.
    svc.set_field(db, session, schema, "applicant.is_homeless", "yes")
    answers = svc._answers_map(db, sid)
    assert answers.get("applicant.is_homeless") is True
    assert "applicant.home_address" not in answers


def test_unrelated_answers_are_not_cleared_on_correction(db):
    sid, session, schema = _new_odm_session(db)

    svc.set_field(db, session, schema, "applicant.first_name", "Tony")
    svc.set_field(db, session, schema, "applicant.is_homeless", "no")
    svc.set_field(db, session, schema, "applicant.home_address", "123 Main St")

    # Re-affirming the gate (still not homeless) must not wipe applicable answers.
    svc.set_field(db, session, schema, "applicant.is_homeless", "no")
    answers = svc._answers_map(db, sid)
    assert answers.get("applicant.first_name") == "Tony"
    assert answers.get("applicant.home_address") == "123 Main St"
