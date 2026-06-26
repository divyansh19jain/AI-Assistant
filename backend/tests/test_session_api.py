"""Tests for session creation, answer saving, and review."""

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
    monkeypatch.setattr(pdf_service, "_get_base_pdf_path", lambda: None)

    create_resp = client.post("/api/session/create", json={
        "patient_id": "mock-001",
        "form_id": "ODM_07216",
        "manual_mode": False,
    })
    session_id = create_resp.json()["session_id"]

    pdf_resp = client.post(f"/api/session/{session_id}/generate-pdf")
    assert pdf_resp.status_code == 200
    data = pdf_resp.json()
    assert "download_url" in data
    assert "file_name" in data
    # With the base PDF forced absent, generation must use the summary fallback.
    assert data["is_fallback"] is True
