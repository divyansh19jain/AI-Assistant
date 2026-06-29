"""Tests for session creation, answer saving, and review."""

import json

import pytest


def test_create_session_manual_mode(client):
    response = client.post("/api/session/create", json={
        "form_id": "ODM_07216",
        "manual_mode": True,
    })
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["prefilled_count"] == 0
    assert data["missing_count"] > 0


def test_create_session_with_mock_patient(client):
    response = client.post("/api/session/create", json={
        "patient_id": "mock-001",
        "form_id": "ODM_07216",
        "manual_mode": False,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["prefilled_count"] > 0
    assert data["mock_mode"] is True


def test_get_session(client):
    create_resp = client.post("/api/session/create", json={
        "form_id": "ODM_07216",
        "manual_mode": True,
    })
    session_id = create_resp.json()["session_id"]

    get_resp = client.get(f"/api/session/{session_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["session_id"] == session_id


def test_get_session_not_found(client):
    response = client.get("/api/session/nonexistent-id")
    assert response.status_code == 404


def test_save_answer(client):
    create_resp = client.post("/api/session/create", json={
        "form_id": "ODM_07216",
        "manual_mode": True,
    })
    session_id = create_resp.json()["session_id"]

    answer_resp = client.post(f"/api/session/{session_id}/answer", json={
        "field_key": "applicant.first_name",
        "raw_answer": "Alice",
        "input_mode": "typed",
    })
    assert answer_resp.status_code == 200
    data = answer_resp.json()
    assert data["success"] is True
    assert data["extracted_value"] == "Alice"


def test_answer_endpoint_rejects_repeated_question_as_text_value(client):
    create_resp = client.post("/api/session/create", json={
        "form_id": "BH_SELF_REPORT_BATTERY",
        "manual_mode": True,
    })
    session_id = create_resp.json()["session_id"]

    answer_resp = client.post(f"/api/session/{session_id}/answer", json={
        "field_key": "client.first_name",
        "raw_answer": "what is your first name",
        "input_mode": "typed",
    })

    assert answer_resp.status_code == 200
    data = answer_resp.json()
    assert data["success"] is False
    assert data["needs_clarification"] is True
    assert "not an answer" in data["error"].lower()

    state = client.get(f"/api/session/{session_id}").json()
    assert "client.first_name" not in state["answers"]
    assert state["next_question"]["field_key"] == "client.first_name"


def test_session_state_and_review_do_not_count_legacy_invalid_text(client, db):
    from app.db.models import FormAnswer

    create_resp = client.post("/api/session/create", json={
        "form_id": "BH_SELF_REPORT_BATTERY",
        "manual_mode": True,
    })
    session_id = create_resp.json()["session_id"]

    # Simulate a row written by an older buggy assistant version. The current
    # runtime must treat it as needing correction, not as completed client data.
    db.add(FormAnswer(
        session_id=session_id,
        field_key="client.first_name",
        value_json=json.dumps("what is your first name"),
        raw_answer="what is your first name",
        source="voice",
        confidence=1.0,
    ))
    db.commit()

    state = client.get(f"/api/session/{session_id}").json()
    assert state["answered_count"] == 0
    assert state["next_question"]["field_key"] == "client.first_name"

    review = client.get(f"/api/session/{session_id}/review").json()
    first_name = next(f for f in review["sections"]["client"] if f["field_key"] == "client.first_name")
    assert first_name["is_valid"] is False
    assert "not an answer" in first_name["validation_error"].lower()
    assert review["readiness"]["summary"]["answered_fields"] == 0
    assert review["readiness"]["summary"]["invalid_fields"] == 1
    assert "client.first_name" in review["missing_applicable"]


def test_odm_does_not_reask_person1_name_after_applicant_name(client):
    create_resp = client.post("/api/session/create", json={
        "form_id": "ODM_07216",
        "manual_mode": True,
    })
    session_id = create_resp.json()["session_id"]

    client.post(f"/api/session/{session_id}/answer", json={
        "field_key": "applicant.first_name",
        "raw_answer": "Amy",
        "input_mode": "typed",
    })
    client.post(f"/api/session/{session_id}/answer", json={
        "field_key": "applicant.last_name",
        "raw_answer": "Stark",
        "input_mode": "typed",
    })
    dob_resp = client.post(f"/api/session/{session_id}/answer", json={
        "field_key": "person1.dob",
        "raw_answer": "January 5th 1980",
        "input_mode": "typed",
    })

    assert dob_resp.status_code == 200
    assert dob_resp.json()["success"] is True
    assert dob_resp.json()["extracted_value"] == "1980-01-05"

    state = client.get(f"/api/session/{session_id}").json()
    assert state["answers"]["person1.first_name"] == "Amy"
    assert state["answers"]["person1.last_name"] == "Stark"
    assert state["answers"]["person1.relationship_to_applicant"] == "Self"
    assert state["next_question"]["field_key"] not in {"person1.first_name", "person1.last_name"}


def test_state_name_normalizes_and_short_phone_reasks(client):
    create_resp = client.post("/api/session/create", json={
        "form_id": "ODM_07216",
        "manual_mode": True,
    })
    session_id = create_resp.json()["session_id"]

    state_resp = client.post(f"/api/session/{session_id}/answer", json={
        "field_key": "applicant.state",
        "raw_answer": "Ohio 61459 9800",
        "input_mode": "typed",
    })
    assert state_resp.status_code == 200
    assert state_resp.json()["success"] is True
    assert state_resp.json()["extracted_value"] == "OH"

    phone_resp = client.post(f"/api/session/{session_id}/answer", json={
        "field_key": "applicant.phone",
        "raw_answer": "61459 9800",
        "input_mode": "typed",
    })
    assert phone_resp.status_code == 200
    assert phone_resp.json()["success"] is False
    assert phone_resp.json()["needs_clarification"] is True
    assert "10-digit phone number" in phone_resp.json()["error"]


def test_save_invalid_boolean(client):
    create_resp = client.post("/api/session/create", json={
        "form_id": "ODM_07216",
        "manual_mode": True,
    })
    session_id = create_resp.json()["session_id"]

    answer_resp = client.post(f"/api/session/{session_id}/answer", json={
        "field_key": "person1.tax_file_next_year",
        "raw_answer": "maybe",
        "input_mode": "typed",
    })
    assert answer_resp.status_code == 200
    data = answer_resp.json()
    assert data["success"] is False
    assert data["needs_clarification"] is True


def test_review_endpoint(client):
    create_resp = client.post("/api/session/create", json={
        "patient_id": "mock-001",
        "form_id": "ODM_07216",
        "manual_mode": False,
    })
    session_id = create_resp.json()["session_id"]

    review_resp = client.get(f"/api/session/{session_id}/review")
    assert review_resp.status_code == 200
    data = review_resp.json()
    assert "sections" in data
    assert "missing_required" in data
    assert "is_complete" in data


def test_pdf_generation_fallback(client, monkeypatch):
    # The fillable base PDF IS committed to the repo (app/pdf/ODM07216fillx.pdf), so
    # we force the no-base-PDF condition to deterministically exercise the summary
    # fallback branch this test is named for — instead of depending on the env.
    import app.pdf.pdf_service as pdf_service
    monkeypatch.setattr(pdf_service, "_get_base_pdf_path", lambda *_args, **_kwargs: None)

    h = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"}).json()
    headers = {"Authorization": f"Bearer {h['token']}"}
    client.post("/api/admin/forms", headers=headers, json={"form_id": "PDF_FALLBACK", "title": "PDF Fallback"})
    client.post("/api/admin/forms/PDF_FALLBACK/publish", headers=headers)

    create_resp = client.post("/api/session/create", json={"form_id": "PDF_FALLBACK", "manual_mode": True})
    session_id = create_resp.json()["session_id"]

    pdf_resp = client.post(f"/api/session/{session_id}/approve", json={})
    assert pdf_resp.status_code == 200, pdf_resp.text
    data = pdf_resp.json()["tasks"][0]["output"]
    assert "download_url" in data
    assert "file_name" in data
    # With the base PDF forced absent, generation must use the summary fallback.
    assert data["is_fallback"] is True


def test_direct_pdf_generation_requires_approval(client, monkeypatch):
    import app.pdf.pdf_service as pdf_service
    monkeypatch.setattr(pdf_service, "_get_base_pdf_path", lambda *_args, **_kwargs: None)

    h = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"}).json()
    headers = {"Authorization": f"Bearer {h['token']}"}
    client.post("/api/admin/forms", headers=headers, json={"form_id": "DIRECT_PDF", "title": "Direct PDF"})
    client.post("/api/admin/forms/DIRECT_PDF/publish", headers=headers)
    sid = client.post("/api/session/create", json={"form_id": "DIRECT_PDF", "manual_mode": True}).json()["session_id"]

    assert client.post(f"/api/session/{sid}/generate-pdf").status_code == 403
    assert client.post(f"/api/session/{sid}/approve", json={}).status_code == 200
    assert client.post(f"/api/session/{sid}/generate-pdf").status_code == 200


def test_builder_form_pdf_summary_uses_form_id(client):
    h = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"}).json()
    headers = {"Authorization": f"Bearer {h['token']}"}
    schema = {
        "form_id": "GENERIC_PDF",
        "form_title": "Generic Benefit Form",
        "version": "1.0",
        "sections": [
            {
                "section_key": "main",
                "section_title": "Main",
                "fields": [
                    {
                        "field_key": "main.name",
                        "label": "Name",
                        "section": "main",
                        "type": "text",
                        "required": True,
                        "question_text": "Name?",
                    }
                ],
            }
        ],
    }
    client.post("/api/admin/forms", headers=headers, json={"form_id": "GENERIC_PDF", "title": "Generic Benefit Form"})
    client.put("/api/admin/forms/GENERIC_PDF/schema", headers=headers, json={"schema": schema})
    client.post("/api/admin/forms/GENERIC_PDF/publish", headers=headers)
    sid = client.post("/api/session/create", json={"form_id": "GENERIC_PDF", "manual_mode": True}).json()["session_id"]
    client.post(
        f"/api/session/{sid}/answer",
        json={"field_key": "main.name", "raw_answer": "Jane Example", "input_mode": "typed"},
    )

    wf = client.post(f"/api/session/{sid}/approve", json={}).json()
    data = wf["tasks"][0]["output"]
    assert data["is_fallback"] is True
    assert data["file_name"].startswith("GENERIC_PDF_Summary_")


def test_session_uses_schema_snapshot_after_form_edit(client):
    h = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"}).json()
    headers = {"Authorization": f"Bearer {h['token']}"}
    schema_v1 = {
        "form_id": "SNAP",
        "form_title": "Snapshot",
        "version": "1.0",
        "sections": [
            {
                "section_key": "s",
                "section_title": "S",
                "fields": [
                    {
                        "field_key": "s.first",
                        "label": "First",
                        "section": "s",
                        "type": "text",
                        "required": True,
                        "question_text": "First?",
                    }
                ],
            }
        ],
    }
    schema_v2 = {
        **schema_v1,
        "sections": [
            {
                "section_key": "s",
                "section_title": "S",
                "fields": [
                    {
                        "field_key": "s.second",
                        "label": "Second",
                        "section": "s",
                        "type": "text",
                        "required": True,
                        "question_text": "Second?",
                    }
                ],
            }
        ],
    }
    client.post("/api/admin/forms", headers=headers, json={"form_id": "SNAP", "title": "Snapshot"})
    client.put("/api/admin/forms/SNAP/schema", headers=headers, json={"schema": schema_v1})
    client.post("/api/admin/forms/SNAP/publish", headers=headers)
    sid = client.post("/api/session/create", json={"form_id": "SNAP", "manual_mode": True}).json()["session_id"]

    client.put("/api/admin/forms/SNAP/schema", headers=headers, json={"schema": schema_v2})
    state = client.get(f"/api/session/{sid}").json()
    assert state["next_question"]["field_key"] == "s.first"


def test_review_omits_inactive_conditional_fields(client):
    h = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"}).json()
    headers = {"Authorization": f"Bearer {h['token']}"}
    schema = {
        "form_id": "COND",
        "form_title": "Conditional",
        "version": "1.0",
        "sections": [
            {
                "section_key": "s",
                "section_title": "S",
                "fields": [
                    {
                        "field_key": "s.has_other",
                        "label": "Has other",
                        "section": "s",
                        "type": "boolean",
                        "required": True,
                        "question_text": "Do you have another value?",
                    },
                    {
                        "field_key": "s.other_value",
                        "label": "Other value",
                        "section": "s",
                        "type": "text",
                        "required": True,
                        "question_text": "What is it?",
                        "depends_on": {"field_key": "s.has_other", "value": True},
                    },
                ],
            }
        ],
    }
    client.post("/api/admin/forms", headers=headers, json={"form_id": "COND", "title": "Conditional"})
    client.put("/api/admin/forms/COND/schema", headers=headers, json={"schema": schema})
    client.post("/api/admin/forms/COND/publish", headers=headers)
    sid = client.post("/api/session/create", json={"form_id": "COND", "manual_mode": True}).json()["session_id"]

    client.post(
        f"/api/session/{sid}/answer",
        json={"field_key": "s.has_other", "raw_answer": "no", "input_mode": "typed"},
    )

    review = client.get(f"/api/session/{sid}/review").json()
    field_keys = [f["field_key"] for f in review["sections"]["s"]]
    assert field_keys == ["s.has_other"]
    assert review["missing_applicable"] == []
    assert review["is_complete"] is True


def test_gate_correction_clears_multi_level_stale_answers(client, db):
    from app.db.models import FormAnswer

    h = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"}).json()
    headers = {"Authorization": f"Bearer {h['token']}"}
    schema = {
        "form_id": "DEEP_COND",
        "form_title": "Deep Conditional",
        "version": "1.0",
        "sections": [
            {
                "section_key": "s",
                "section_title": "S",
                "fields": [
                    {"field_key": "s.top_gate", "label": "Top", "section": "s", "type": "boolean", "required": True},
                    {
                        "field_key": "s.child_gate",
                        "label": "Child",
                        "section": "s",
                        "type": "boolean",
                        "required": True,
                        "depends_on": {"field_key": "s.top_gate", "value": True},
                    },
                    {
                        "field_key": "s.grandchild_value",
                        "label": "Grandchild",
                        "section": "s",
                        "type": "text",
                        "required": True,
                        "depends_on": {"field_key": "s.child_gate", "value": True},
                    },
                ],
            }
        ],
    }
    client.post("/api/admin/forms", headers=headers, json={"form_id": "DEEP_COND", "title": "Deep Conditional"})
    client.put("/api/admin/forms/DEEP_COND/schema", headers=headers, json={"schema": schema})
    client.post("/api/admin/forms/DEEP_COND/publish", headers=headers)
    sid = client.post("/api/session/create", json={"form_id": "DEEP_COND", "manual_mode": True}).json()["session_id"]

    for field_key, raw in [
        ("s.top_gate", "yes"),
        ("s.child_gate", "yes"),
        ("s.grandchild_value", "stale detail"),
        ("s.top_gate", "no"),
    ]:
        r = client.post(
            f"/api/session/{sid}/answer",
            json={"field_key": field_key, "raw_answer": raw, "input_mode": "typed"},
        )
        assert r.status_code == 200, r.text

    review = client.get(f"/api/session/{sid}/review").json()
    field_keys = [f["field_key"] for f in review["sections"]["s"]]
    assert field_keys == ["s.top_gate"]
    stored_keys = {row[0] for row in db.query(FormAnswer.field_key).filter(FormAnswer.session_id == sid).all()}
    assert stored_keys == {"s.top_gate"}


def test_review_fields_include_schema_edit_metadata(client):
    h = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"}).json()
    headers = {"Authorization": f"Bearer {h['token']}"}
    schema = {
        "form_id": "REVIEW_META",
        "form_title": "Review Meta",
        "version": "1.0",
        "sections": [
            {
                "section_key": "s",
                "section_title": "S",
                "fields": [
                    {
                        "field_key": "s.choice",
                        "label": "Choice",
                        "section": "s",
                        "type": "select",
                        "required": True,
                        "question_text": "Pick one.",
                        "validation_rule": {"allowed_values": ["A", "B"]},
                    }
                ],
            }
        ],
    }
    client.post("/api/admin/forms", headers=headers, json={"form_id": "REVIEW_META", "title": "Review Meta"})
    client.put("/api/admin/forms/REVIEW_META/schema", headers=headers, json={"schema": schema})
    client.post("/api/admin/forms/REVIEW_META/publish", headers=headers)
    sid = client.post("/api/session/create", json={"form_id": "REVIEW_META", "manual_mode": True}).json()["session_id"]
    client.post(
        f"/api/session/{sid}/answer",
        json={"field_key": "s.choice", "raw_answer": "A", "input_mode": "typed"},
    )

    field = client.get(f"/api/session/{sid}/review").json()["sections"]["s"][0]
    assert field["field_type"] == "select"
    assert field["options"] == ["A", "B"]


def test_skip_unknown_field_rejected(client):
    create_resp = client.post("/api/session/create", json={
        "form_id": "ODM_07216",
        "manual_mode": True,
    })
    session_id = create_resp.json()["session_id"]

    skip_resp = client.post(f"/api/session/{session_id}/skip", json={
        "field_key": "not.in.schema",
        "raw_answer": "skip",
        "input_mode": "typed",
    })
    assert skip_resp.status_code == 200
    assert skip_resp.json()["success"] is False
    assert "Unknown field" in skip_resp.json()["error"]
