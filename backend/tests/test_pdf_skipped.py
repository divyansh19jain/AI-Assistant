"""Skipped fields must render blank on the PDF, never the literal word 'skipped'."""

from app.sessions import service as svc
from app.db.models import FormSession


def test_saving_the_word_skipped_stores_a_skip_not_text(db):
    state = svc.create_session(db, form_id="ODM_07216", patient_id=None, manual_mode=True)
    session = db.query(FormSession).filter(FormSession.id == state["session_id"]).first()
    schema = svc._schema_for_session(session)

    result = svc.set_field(db, session, schema, "applicant.apartment", "skipped")
    assert result["ok"]
    # Stored as the skip sentinel, not as the literal text "skipped".
    assert svc._answers_map(db, state["session_id"])["applicant.apartment"] == "__skipped__"


def test_pdf_display_blanks_skipped_values():
    from app.pdf.pdf_service import _display_value, _is_skipped, _checkbox_value

    assert _display_value("skipped") is None
    assert _display_value("__skipped__") is None
    assert _display_value("123 Main St") == "123 Main St"
    assert _is_skipped("skipped") is True
    assert _is_skipped("__skipped__") is True
    assert _checkbox_value("skipped") is None
