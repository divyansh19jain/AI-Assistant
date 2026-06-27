"""Tests for the approval gate + workflow engine (PDF target)."""


def _auth(client) -> dict:
    r = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_approve_runs_default_pdf_workflow(client, monkeypatch):
    # Force the summary-fallback PDF path so this test doesn't depend on the base PDF.
    import app.pdf.pdf_service as pdf_service

    monkeypatch.setattr(pdf_service, "_get_base_pdf_path", lambda *_args, **_kwargs: None)

    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "APDF", "title": "APDF"})
    client.post("/api/admin/forms/APDF/publish", headers=h)

    s = client.post("/api/session/create", json={"form_id": "APDF", "manual_mode": True}).json()
    sid = s["session_id"]

    # Nothing has run yet.
    assert client.get(f"/api/session/{sid}/workflow").json()["status"] == "not_started"

    # Approve -> the default workflow (generate_pdf) runs and completes.
    r = client.post(f"/api/session/{sid}/approve", json={"approved_by": "patient"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "completed"
    assert data["tasks"][0]["type"] == "generate_pdf"
    assert data["tasks"][0]["status"] == "completed"
    assert data["tasks"][0]["output"]["download_url"]

    # Status endpoint reflects the completed run.
    assert client.get(f"/api/session/{sid}/workflow").json()["status"] == "completed"


def test_custom_workflow_via_builder(client, monkeypatch):
    import app.pdf.pdf_service as pdf_service

    monkeypatch.setattr(pdf_service, "_get_base_pdf_path", lambda *_args, **_kwargs: None)

    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "WF", "title": "WF"})
    # A two-task workflow using supported task types only.
    client.put(
        "/api/admin/forms/WF/workflow",
        headers=h,
        json={
            "workflow": {
                "tasks": [
                    {"type": "generate_pdf"},
                    {"type": "web_submit", "config": {"recipe": {"portal_url": "https://example.test/apply"}}},
                ],
                "approval": {"required": True},
            }
        },
    )
    client.post("/api/admin/forms/WF/publish", headers=h)

    sid = client.post("/api/session/create", json={"form_id": "WF", "manual_mode": True}).json()["session_id"]
    data = client.post(f"/api/session/{sid}/approve", json={}).json()
    assert data["status"] == "completed"
    assert [t["type"] for t in data["tasks"]] == ["generate_pdf", "web_submit"]
    assert all(t["status"] == "completed" for t in data["tasks"])


def test_mock_web_driver_offline():
    from app.workflows.web_submit import MockWebDriver

    ev = MockWebDriver().submit({"portal_url": "https://example.test"}, {"a": 1, "b": 2})
    assert ev["dry_run"] is True
    assert ev["submitted_field_count"] == 2
    assert ev["confirmation"] == "MOCK-CONFIRM"
    assert MockWebDriver().submit({}, {"a": 1})["error"] == "recipe has no portal_url"


def test_web_submit_task_via_workflow(client):
    """🔒 web_submit runs through the approval gate, using the safe dry-run mock driver."""
    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "WEBF", "title": "WEBF"})
    client.put(
        "/api/admin/forms/WEBF/workflow",
        headers=h,
        json={
            "workflow": {
                "tasks": [{"type": "web_submit", "config": {"recipe": {"portal_url": "https://example.test/apply"}}}],
                "approval": {"required": True},
            }
        },
    )
    client.post("/api/admin/forms/WEBF/publish", headers=h)

    sid = client.post("/api/session/create", json={"form_id": "WEBF", "manual_mode": True}).json()["session_id"]
    data = client.post(f"/api/session/{sid}/approve", json={}).json()
    assert data["status"] == "completed"
    task = data["tasks"][0]
    assert task["type"] == "web_submit"
    assert task["status"] == "completed"
    assert task["output"]["driver"] == "mock"
    assert task["output"]["dry_run"] is True
    assert task["output"]["confirmation"] == "MOCK-CONFIRM"


def test_unknown_workflow_task_fails_closed(client, db):
    """Unsupported task types fail the run instead of being skipped."""
    import json
    from app.db.models import Form

    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "BADWF", "title": "BADWF"})
    form = db.query(Form).filter(Form.form_id == "BADWF").first()
    form.workflow_json = json.dumps({"tasks": [{"type": "notify"}], "approval": {"required": True}})
    db.commit()
    client.post("/api/admin/forms/BADWF/publish", headers=h)

    sid = client.post("/api/session/create", json={"form_id": "BADWF", "manual_mode": True}).json()["session_id"]
    data = client.post(f"/api/session/{sid}/approve", json={}).json()
    assert data["status"] == "failed"
    assert data["tasks"][0]["type"] == "notify"
    assert data["tasks"][0]["status"] == "failed"
    assert "unsupported workflow task type" in data["tasks"][0]["error"]


def test_web_submit_without_recipe_fails(client):
    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "NORECIPE", "title": "NORECIPE"})
    client.put(
        "/api/admin/forms/NORECIPE/workflow",
        headers=h,
        json={"workflow": {"tasks": [{"type": "web_submit"}], "approval": {"required": True}}},
    )
    client.post("/api/admin/forms/NORECIPE/publish", headers=h)

    sid = client.post("/api/session/create", json={"form_id": "NORECIPE", "manual_mode": True}).json()["session_id"]
    data = client.post(f"/api/session/{sid}/approve", json={}).json()
    assert data["status"] == "failed"
    assert data["tasks"][0]["status"] == "failed"
    assert "recipe has no portal_url" in data["tasks"][0]["error"]


def test_approval_rejects_incomplete_session(client):
    h = _auth(client)
    schema = {
        "form_id": "INCOMPLETE",
        "form_title": "Incomplete",
        "version": "1.0",
        "sections": [
            {
                "section_key": "s",
                "section_title": "S",
                "fields": [
                    {
                        "field_key": "s.required",
                        "label": "Required",
                        "section": "s",
                        "type": "text",
                        "required": True,
                        "question_text": "Required?",
                    }
                ],
            }
        ],
    }
    client.post("/api/admin/forms", headers=h, json={"form_id": "INCOMPLETE", "title": "Incomplete"})
    client.put("/api/admin/forms/INCOMPLETE/schema", headers=h, json={"schema": schema})
    client.post("/api/admin/forms/INCOMPLETE/publish", headers=h)

    sid = client.post("/api/session/create", json={"form_id": "INCOMPLETE", "manual_mode": True}).json()["session_id"]
    r = client.post(f"/api/session/{sid}/approve", json={})
    assert r.status_code == 400
    assert r.json()["detail"]["missing_fields"] == ["s.required"]
