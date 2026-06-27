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


def test_temporal_engine_route_uses_temporal_bridge(client, monkeypatch):
    from app.core.config import get_settings
    import app.workflows.temporal_engine as temporal_engine

    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "TEMPORALWF", "title": "Temporal WF"})
    client.post("/api/admin/forms/TEMPORALWF/publish", headers=h)
    sid = client.post("/api/session/create", json={"form_id": "TEMPORALWF", "manual_mode": True}).json()["session_id"]

    called = {}

    def fake_execute(session_id: str) -> dict:
        called["session_id"] = session_id
        return {
            "run_id": 123,
            "status": "completed",
            "error": None,
            "tasks": [{"type": "generate_pdf", "status": "completed", "output": {"engine": "temporal"}, "error": None}],
        }

    monkeypatch.setenv("WORKFLOW_ENGINE", "temporal")
    get_settings.cache_clear()
    monkeypatch.setattr(temporal_engine, "execute_completion_workflow_sync", fake_execute)
    try:
        response = client.post(f"/api/session/{sid}/approve", json={"approved_by": "patient"})
    finally:
        monkeypatch.setenv("WORKFLOW_ENGINE", "local")
        get_settings.cache_clear()

    assert response.status_code == 200, response.text
    assert called["session_id"] == sid
    assert response.json()["tasks"][0]["output"]["engine"] == "temporal"


def test_temporal_unavailable_falls_back_to_local_engine(client, monkeypatch):
    from app.core.config import get_settings
    import app.pdf.pdf_service as pdf_service
    import app.workflows.temporal_engine as temporal_engine

    monkeypatch.setattr(pdf_service, "_get_base_pdf_path", lambda *_args, **_kwargs: None)
    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "TFALLBACK", "title": "Temporal Fallback"})
    client.post("/api/admin/forms/TFALLBACK/publish", headers=h)
    sid = client.post("/api/session/create", json={"form_id": "TFALLBACK", "manual_mode": True}).json()["session_id"]

    def raise_temporal(_session_id: str) -> dict:
        raise RuntimeError("temporal is down")

    monkeypatch.setenv("WORKFLOW_ENGINE", "temporal")
    get_settings.cache_clear()
    monkeypatch.setattr(temporal_engine, "execute_completion_workflow_sync", raise_temporal)
    try:
        response = client.post(f"/api/session/{sid}/approve", json={"approved_by": "patient"})
    finally:
        monkeypatch.setenv("WORKFLOW_ENGINE", "local")
        get_settings.cache_clear()

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "completed"
    assert data["tasks"][0]["type"] == "generate_pdf"
    assert client.get(f"/api/session/{sid}").json()["status"] == "completed"


def test_temporal_and_local_failure_returns_generic_503(client, monkeypatch):
    from app.core.config import get_settings
    import app.workflows.router as workflow_router
    import app.workflows.temporal_engine as temporal_engine

    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "TFAIL", "title": "Temporal Fail"})
    client.post("/api/admin/forms/TFAIL/publish", headers=h)
    sid = client.post("/api/session/create", json={"form_id": "TFAIL", "manual_mode": True}).json()["session_id"]

    monkeypatch.setenv("WORKFLOW_ENGINE", "temporal")
    get_settings.cache_clear()
    monkeypatch.setattr(temporal_engine, "execute_completion_workflow_sync", lambda _sid: (_ for _ in ()).throw(RuntimeError("temporal host detail")))
    monkeypatch.setattr(workflow_router, "run_workflow", lambda _db, _sid: (_ for _ in ()).throw(RuntimeError("local db detail")))
    try:
        response = client.post(f"/api/session/{sid}/approve", json={"approved_by": "patient"})
    finally:
        monkeypatch.setenv("WORKFLOW_ENGINE", "local")
        get_settings.cache_clear()

    assert response.status_code == 503
    assert response.json()["detail"] == "Completion service is temporarily unavailable. Please try again."
    assert "temporal host detail" not in response.text
    assert "local db detail" not in response.text
    assert client.get(f"/api/session/{sid}").json()["status"] == "ready_for_review"


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
                "tasks": [{
                    "type": "web_submit",
                    "config": {
                        "recipe": {
                            "portal_url": "https://example.test/apply",
                            "steps": [{"action": "fill", "selector": "#name", "field_key": "s.name"}],
                        }
                    },
                }],
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
    assert task["output"]["step_count"] == 1
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


def test_empty_workflow_fails_closed(client, db):
    import json
    from app.db.models import Form

    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "EMPTYWF", "title": "EMPTYWF"})
    form = db.query(Form).filter(Form.form_id == "EMPTYWF").first()
    form.workflow_json = json.dumps({"tasks": [], "approval": {"required": True}})
    db.commit()
    client.post("/api/admin/forms/EMPTYWF/publish", headers=h)

    sid = client.post("/api/session/create", json={"form_id": "EMPTYWF", "manual_mode": True}).json()["session_id"]
    data = client.post(f"/api/session/{sid}/approve", json={}).json()
    assert data["status"] == "failed"
    assert data["tasks"] == []


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
    assert client.get(f"/api/session/{sid}").json()["status"] == "ready_for_review"


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


def test_workflow_status_unknown_session_404(client):
    assert client.get("/api/session/not-a-session/workflow").status_code == 404


def test_ready_for_review_is_not_completed_until_approval(client, db):
    from app.db.models import FormApproval

    h = _auth(client)
    schema = {
        "form_id": "STATUS",
        "form_title": "Status",
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
    client.post("/api/admin/forms", headers=h, json={"form_id": "STATUS", "title": "Status"})
    client.put("/api/admin/forms/STATUS/schema", headers=h, json={"schema": schema})
    client.post("/api/admin/forms/STATUS/publish", headers=h)
    sid = client.post("/api/session/create", json={"form_id": "STATUS", "manual_mode": True}).json()["session_id"]

    answer = client.post(
        f"/api/session/{sid}/answer",
        json={"field_key": "s.required", "raw_answer": "Alice", "input_mode": "typed"},
    ).json()
    assert answer["is_complete"] is True
    assert client.get(f"/api/session/{sid}").json()["status"] == "ready_for_review"

    dashboard = client.get("/api/admin/dashboard", headers=h).json()["stats"]
    assert dashboard["completed"] == 0
    assert dashboard["ready_for_review"] == 1

    assert client.post(f"/api/session/{sid}/approve", json={}).status_code == 200
    assert client.get(f"/api/session/{sid}").json()["status"] == "completed"
    assert client.get("/api/admin/dashboard", headers=h).json()["stats"]["completed"] == 1

    # A rerun without answer edits reuses the current approval instead of inserting duplicates.
    assert client.post(f"/api/session/{sid}/approve", json={}).status_code == 200
    assert db.query(FormApproval).filter(FormApproval.session_id == sid).count() == 1


def test_web_submit_filters_inactive_conditional_answers(client):
    h = _auth(client)
    schema = {
        "form_id": "CONDWEB",
        "form_title": "Conditional Web",
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
    client.post("/api/admin/forms", headers=h, json={"form_id": "CONDWEB", "title": "Conditional Web"})
    client.put("/api/admin/forms/CONDWEB/schema", headers=h, json={"schema": schema})
    client.put(
        "/api/admin/forms/CONDWEB/workflow",
        headers=h,
        json={
            "workflow": {
                "tasks": [{"type": "web_submit", "config": {"recipe": {"portal_url": "https://example.test/apply"}}}],
                "approval": {"required": True},
            }
        },
    )
    client.post("/api/admin/forms/CONDWEB/publish", headers=h)
    sid = client.post("/api/session/create", json={"form_id": "CONDWEB", "manual_mode": True}).json()["session_id"]

    client.post(f"/api/session/{sid}/answer", json={"field_key": "s.has_other", "raw_answer": "yes", "input_mode": "typed"})
    client.post(f"/api/session/{sid}/answer", json={"field_key": "s.other_value", "raw_answer": "stale", "input_mode": "typed"})
    client.post(f"/api/session/{sid}/answer", json={"field_key": "s.has_other", "raw_answer": "no", "input_mode": "typed"})

    data = client.post(f"/api/session/{sid}/approve", json={}).json()
    assert data["status"] == "completed"
    assert data["tasks"][0]["output"]["submitted_field_count"] == 1
