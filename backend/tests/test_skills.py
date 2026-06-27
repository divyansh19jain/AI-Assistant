"""Tests for skills (reusable AI capabilities) — registry + attach CRUD."""


def _auth(client) -> dict:
    r = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_run_builtin_skills_offline():
    from app.skills.registry import run_skill

    # glossary is fully offline + deterministic
    assert "money" in run_skill("glossary", {"term": "income"})["definition"].lower()
    # unknown term -> empty definition (not an error)
    assert run_skill("glossary", {"term": "zzz"})["definition"] == ""
    # unknown skill -> error dict, never raises
    assert "error" in run_skill("nope", {})
    # zip_lookup with no API key degrades gracefully
    assert "error" in run_skill("zip_lookup", {"zip": "43215"}) or "city" in run_skill("zip_lookup", {"zip": "43215"})


def test_skill_catalog_and_run_api(client):
    h = _auth(client)
    catalog = client.get("/api/admin/skills", headers=h).json()
    keys = [s["key"] for s in catalog]
    assert {"zip_lookup", "kb_lookup", "glossary"} <= set(keys)

    r = client.post("/api/admin/skills/glossary/run", headers=h, json={"params": {"term": "household"}})
    assert r.status_code == 200
    assert "live with" in r.json()["definition"].lower()

    assert client.post("/api/admin/skills/nope/run", headers=h, json={"params": {}}).status_code == 404


def test_attach_skills_to_form(client):
    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "SKF", "title": "SKF"})

    # initially none
    assert client.get("/api/admin/forms/SKF/skills", headers=h).json()["attached"] == []

    # bogus keys fail instead of being silently dropped
    r = client.put("/api/admin/forms/SKF/skills", headers=h, json={"skill_keys": ["glossary", "kb_lookup", "bogus"]})
    assert r.status_code == 422

    # attach two valid skills
    r = client.put("/api/admin/forms/SKF/skills", headers=h, json={"skill_keys": ["glossary", "kb_lookup"]})
    assert r.status_code == 200
    assert set(r.json()["attached"]) == {"glossary", "kb_lookup"}

    # readable back; and the registry helper agrees
    assert set(client.get("/api/admin/forms/SKF/skills", headers=h).json()["attached"]) == {"glossary", "kb_lookup"}


def test_skills_require_existing_form(client):
    h = _auth(client)
    assert client.get("/api/admin/forms/NOPE/skills", headers=h).status_code == 404
    assert client.put("/api/admin/forms/NOPE/skills", headers=h, json={"skill_keys": ["glossary"]}).status_code == 404
