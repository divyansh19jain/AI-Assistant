"""Tests for the approval gate + workflow engine (PDF target)."""


def _auth(client) -> dict:
    r = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_approve_runs_default_pdf_workflow(client, monkeypatch):
    # Force the summary-fallback PDF path so this test doesn't depend on the base PDF.
    import app.pdf.pdf_service as pdf_service

    monkeypatch.setattr(pdf_service, "_get_base_pdf_path", lambda: None)

    s = client.post("/api/session/create", json={"form_id": "ODM_07216", "manual_mode": True}).json()
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

    monkeypatch.setattr(pdf_service, "_get_base_pdf_path", lambda: None)

    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "WF", "title": "WF"})
    # A two-task workflow: notify, then generate the PDF.
    client.put(
        "/api/admin/forms/WF/workflow",
        headers=h,
        json={"workflow": {"tasks": [{"type": "notify"}, {"type": "generate_pdf"}], "approval": {"required": True}}},
    )
    client.post("/api/admin/forms/WF/publish", headers=h)

    sid = client.post("/api/session/create", json={"form_id": "WF", "manual_mode": True}).json()["session_id"]
    data = client.post(f"/api/session/{sid}/approve", json={}).json()
    assert data["status"] == "completed"
    assert [t["type"] for t in data["tasks"]] == ["notify", "generate_pdf"]
    assert all(t["status"] == "completed" for t in data["tasks"])


def test_mock_web_driver_offline():
    from app.workflows.web_submit import MockWebDriver

    ev = MockWebDriver().submit({"portal_url": "https://example.test"}, {"a": 1, "b": 2})
    assert ev["dry_run"] is True
    assert ev["submitted_field_count"] == 2
    assert ev["confirmation"] == "MOCK-CONFIRM"


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
