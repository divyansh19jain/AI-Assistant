"""Readiness gate tests for deterministic form completion."""

import json


def _admin_headers(client) -> dict:
    token = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _publish_simple_form(client, form_id: str = "READY_SIMPLE") -> None:
    headers = _admin_headers(client)
    schema = {
        "form_id": form_id,
        "form_title": "Readiness Simple",
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
                        "question_text": "What is your name?",
                        "validation_rule": {"min_length": 1},
                    },
                    {
                        "field_key": "main.nickname",
                        "label": "Nickname",
                        "section": "main",
                        "type": "text",
                        "required": False,
                        "question_text": "Do you have a nickname?",
                    },
                ],
            }
        ],
    }
    client.post("/api/admin/forms", headers=headers, json={"form_id": form_id, "title": "Readiness Simple"})
    client.put(f"/api/admin/forms/{form_id}/schema", headers=headers, json={"schema": schema})
    client.post(f"/api/admin/forms/{form_id}/publish", headers=headers)


def test_readiness_reports_missing_fields_and_blocks_approval(client):
    _publish_simple_form(client)
    sid = client.post("/api/session/create", json={"form_id": "READY_SIMPLE", "manual_mode": True}).json()["session_id"]

    readiness = client.get(f"/api/session/{sid}/readiness").json()
    assert readiness["ready"] is False
    assert readiness["missing_required"] == ["main.name"]
    assert readiness["missing_optional"] == ["main.nickname"]
    assert {b["kind"] for b in readiness["blockers"]} == {"missing_required", "missing_optional"}

    approval = client.post(f"/api/session/{sid}/approve", json={"approved_by": "patient"})
    assert approval.status_code == 400
    assert approval.json()["detail"]["readiness"]["ready"] is False


def test_readiness_ready_after_answer_and_optional_skip(client):
    _publish_simple_form(client, "READY_DONE")
    sid = client.post("/api/session/create", json={"form_id": "READY_DONE", "manual_mode": True}).json()["session_id"]

    client.post(
        f"/api/session/{sid}/answer",
        json={"field_key": "main.name", "raw_answer": "Jane Example", "input_mode": "typed"},
    )
    client.post(
        f"/api/session/{sid}/skip",
        json={"field_key": "main.nickname", "raw_answer": "skip", "input_mode": "typed"},
    )

    review = client.get(f"/api/session/{sid}/review").json()
    readiness = review["readiness"]
    assert readiness["ready"] is True
    assert readiness["summary"]["answered_fields"] == 1
    assert readiness["summary"]["skipped_fields"] == 1
    assert readiness["summary"]["missing_fields"] == 0
    assert review["is_complete"] is True


def test_low_confidence_answer_blocks_until_corrected(client, db):
    from app.db.models import FormAnswer

    _publish_simple_form(client, "READY_CONF")
    sid = client.post("/api/session/create", json={"form_id": "READY_CONF", "manual_mode": True}).json()["session_id"]
    db.add(FormAnswer(
        session_id=sid,
        field_key="main.name",
        value_json=json.dumps("Maybe Jane"),
        raw_answer="Maybe Jane",
        source="voice",
        confidence=0.4,
    ))
    db.add(FormAnswer(
        session_id=sid,
        field_key="main.nickname",
        value_json=json.dumps("__skipped__"),
        raw_answer="skipped",
        source="skipped",
        confidence=0.0,
    ))
    db.commit()

    readiness = client.get(f"/api/session/{sid}/readiness").json()
    assert readiness["ready"] is False
    assert readiness["low_confidence_fields"][0]["field_key"] == "main.name"
    assert client.post(f"/api/session/{sid}/approve", json={}).status_code == 400

    client.post(
        f"/api/session/{sid}/answer",
        json={"field_key": "main.name", "raw_answer": "Jane Example", "input_mode": "typed"},
    )
    readiness = client.get(f"/api/session/{sid}/readiness").json()
    assert readiness["ready"] is True
    assert readiness["low_confidence_fields"] == []


def test_admin_odm_audit_verifies_pdf_mapping(client):
    headers = _admin_headers(client)
    audit = client.get("/api/admin/forms/ODM_07216/audit", headers=headers)
    assert audit.status_code == 200, audit.text
    data = audit.json()
    assert data["ready"] is True
    assert data["pdf"]["official_pdf_ready"] is True
    assert data["pdf"]["missing_pdf_widgets"] == []
    assert data["pdf"]["stale_mapping_fields"] == []
