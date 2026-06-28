"""Admin dashboard categorization + archive/delete/orphan actions."""


def _auth(client) -> dict:
    r = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_orphan_counted_and_bulk_archived(client):
    h = _auth(client)
    # A brand-new session with no answers is an "orphan" (abandoned).
    sid = client.post("/api/session/create", json={"form_id": "ODM_07216", "manual_mode": True}).json()["session_id"]

    data = client.get("/api/admin/dashboard", headers=h).json()
    assert data["stats"]["orphan"] >= 1
    assert any(s["id"] == sid and s["archived"] is False for s in data["sessions"])

    # Bulk-archive orphans -> the session leaves the default list, appears under archived.
    res = client.post("/api/admin/sessions/archive-orphans", headers=h).json()
    assert res["archived_count"] >= 1

    default = client.get("/api/admin/dashboard", headers=h).json()
    assert all(s["id"] != sid for s in default["sessions"])  # hidden by default
    assert default["stats"]["archived"] >= 1

    with_arch = client.get("/api/admin/dashboard?include_archived=true", headers=h).json()
    assert any(s["id"] == sid and s["archived"] is True for s in with_arch["sessions"])


def test_archive_unarchive_and_delete(client, db):
    from app.db.models import FormSession, FormAnswer

    h = _auth(client)
    sid = client.post("/api/session/create", json={"form_id": "ODM_07216", "manual_mode": True}).json()["session_id"]
    client.post(f"/api/session/{sid}/answer", json={"field_key": "applicant.first_name", "raw_answer": "Tony", "input_mode": "typed"})

    assert client.post(f"/api/admin/sessions/{sid}/archive", headers=h).json()["archived"] is True
    assert client.post(f"/api/admin/sessions/{sid}/unarchive", headers=h).json()["archived"] is False

    assert client.delete(f"/api/admin/sessions/{sid}", headers=h).json()["deleted"] is True
    assert db.query(FormSession).filter(FormSession.id == sid).first() is None
    assert db.query(FormAnswer).filter(FormAnswer.session_id == sid).count() == 0


def test_delete_unknown_session_404(client):
    h = _auth(client)
    assert client.delete("/api/admin/sessions/does-not-exist", headers=h).status_code == 404
