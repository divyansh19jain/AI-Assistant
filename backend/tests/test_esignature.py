"""e-signature + consent at approval: required only when the form opts in via
approval.require_signature, recorded either way, and stored for audit."""

import json


def _auth(client) -> dict:
    r = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _form_requiring_signature(client, db, form_id: str) -> str:
    from app.db.models import Form

    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": form_id, "title": form_id})
    form = db.query(Form).filter(Form.form_id == form_id).first()
    form.workflow_json = json.dumps({
        "tasks": [{"type": "generate_pdf"}],
        "approval": {"required": True, "require_signature": True},
    })
    db.commit()
    client.post(f"/api/admin/forms/{form_id}/publish", headers=h)
    return client.post("/api/session/create", json={"form_id": form_id, "manual_mode": True}).json()["session_id"]


def test_approve_requires_signature_when_form_opts_in(client, db):
    sid = _form_requiring_signature(client, db, "SIGREQ")
    r = client.post(f"/api/session/{sid}/approve", json={"approved_by": "patient"})
    assert r.status_code == 422

    from app.db.models import FormApproval
    assert db.query(FormApproval).filter(FormApproval.session_id == sid).count() == 0


def test_signature_and_consent_are_stored(client, db, monkeypatch):
    import app.pdf.pdf_service as pdf_service
    monkeypatch.setattr(pdf_service, "_get_base_pdf_path", lambda *a, **k: None)

    sid = _form_requiring_signature(client, db, "SIGOK")
    r = client.post(
        f"/api/session/{sid}/approve",
        json={"approved_by": "patient", "signature": "Tony Stark", "consent": True},
    )
    assert r.status_code == 200, r.text

    from app.db.models import FormApproval
    approval = db.query(FormApproval).filter(FormApproval.session_id == sid).first()
    assert approval is not None
    assert approval.signature == "Tony Stark"
    assert json.loads(approval.consent_json)["agreed"] is True


def test_signature_optional_when_not_required(client, db, monkeypatch):
    import app.pdf.pdf_service as pdf_service
    monkeypatch.setattr(pdf_service, "_get_base_pdf_path", lambda *a, **k: None)

    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "NOSIG", "title": "NOSIG"})
    client.post("/api/admin/forms/NOSIG/publish", headers=h)
    sid = client.post("/api/session/create", json={"form_id": "NOSIG", "manual_mode": True}).json()["session_id"]

    # Backward compatible: no signature needed when the form doesn't require one.
    r = client.post(f"/api/session/{sid}/approve", json={})
    assert r.status_code == 200, r.text
