"""Tests for the builder forms CRUD API (app/admin/forms_router.py).

Covers the headline loop: create a form in the (admin) builder -> publish it ->
it appears in the public picker AND is runnable in the patient flow. Plus auth,
schema validation, conflict, and delete.

Uses the default admin credentials (admin/admin1234) via the login endpoint; never
real PHI.
"""


def _auth(client) -> dict:
    """Log in with the default admin creds and return an Authorization header."""
    r = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_forms_crud_requires_auth(client):
    # No bearer token -> rejected (HTTPBearer auto_error -> 403; expired/invalid -> 401).
    assert client.get("/api/admin/forms").status_code in (401, 403)
    assert client.post("/api/admin/forms", json={"form_id": "X", "title": "X"}).status_code in (401, 403)


def test_create_publish_run_loop(client):
    h = _auth(client)

    # 1. create -> draft, with a default one-section schema (JSON key is "schema")
    r = client.post("/api/admin/forms", headers=h, json={"form_id": "TEST_FORM", "title": "Test Builder Form"})
    assert r.status_code == 201, r.text
    detail = r.json()
    assert detail["status"] == "draft"
    assert isinstance(detail["schema"]["sections"], list)

    # 2. a draft is NOT offered in the public patient picker
    public_ids = [f["form_id"] for f in client.get("/api/forms").json()["forms"]]
    assert "TEST_FORM" not in public_ids
    # Drafts are also not runnable by direct API calls.
    assert client.post("/api/session/create", json={"form_id": "TEST_FORM", "manual_mode": True}).status_code == 404

    # 3. publish
    r = client.post("/api/admin/forms/TEST_FORM/publish", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"

    # 4. now it IS in the public picker
    public_ids = [f["form_id"] for f in client.get("/api/forms").json()["forms"]]
    assert "TEST_FORM" in public_ids

    # 5. and it is runnable end-to-end — the patient flow loads its schema from the cache
    r = client.post("/api/session/create", json={"form_id": "TEST_FORM", "manual_mode": True})
    assert r.status_code == 200, r.text
    assert r.json()["form_id"] == "TEST_FORM"

    # Unpublishing removes runtime access, not just picker visibility.
    client.post("/api/admin/forms/TEST_FORM/unpublish", headers=h)
    assert client.post("/api/session/create", json={"form_id": "TEST_FORM", "manual_mode": True}).status_code == 404


def test_update_schema_reflected(client):
    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "F2", "title": "F2"})
    new_schema = {
        "form_id": "F2",
        "form_title": "F2",
        "version": "1.0",
        "sections": [
            {
                "section_key": "s1",
                "section_title": "S1",
                "fields": [
                    {
                        "field_key": "a.b",
                        "label": "B",
                        "section": "s1",
                        "type": "text",
                        "required": True,
                        "question_text": "What is B?",
                    }
                ],
            }
        ],
    }
    r = client.put("/api/admin/forms/F2/schema", headers=h, json={"schema": new_schema})
    assert r.status_code == 200, r.text
    assert r.json()["schema"]["sections"][0]["fields"][0]["field_key"] == "a.b"


def test_draft_db_row_blocks_bundled_pack_fallback(client):
    h = _auth(client)
    r = client.post("/api/admin/forms", headers=h, json={"form_id": "ODM_07216", "title": "Draft Shadow"})
    assert r.status_code == 201, r.text

    # A DB row is authoritative. If it is draft, the filesystem seed pack with the
    # same id must not make the form runnable through a direct session-create call.
    r = client.post("/api/session/create", json={"form_id": "ODM_07216", "manual_mode": True})
    assert r.status_code == 404


def test_schema_metadata_stays_in_sync_with_form_row(client):
    h = _auth(client)
    schema = {
        "form_id": "WRONG",
        "form_title": "Wrong title",
        "version": "9.9",
        "sections": [
            {
                "section_key": "s",
                "section_title": "S",
                "fields": [],
            }
        ],
    }
    r = client.post(
        "/api/admin/forms",
        headers=h,
        json={"form_id": "META", "title": "Metadata Title", "version": "1.2", "schema": schema},
    )
    assert r.status_code == 201, r.text
    assert r.json()["schema"]["form_id"] == "META"
    assert r.json()["schema"]["form_title"] == "Metadata Title"
    assert r.json()["schema"]["version"] == "1.2"

    r = client.put("/api/admin/forms/META", headers=h, json={"title": "Renamed", "version": "2.0"})
    assert r.status_code == 200, r.text
    assert r.json()["schema"]["form_title"] == "Renamed"
    assert r.json()["schema"]["version"] == "2.0"

    client.post("/api/admin/forms/META/publish", headers=h)
    s = client.post("/api/session/create", json={"form_id": "META", "manual_mode": True})
    assert s.status_code == 200, s.text
    assert s.json()["form_title"] == "Renamed"


def test_invalid_schema_rejected(client):
    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "F3", "title": "F3"})
    # A schema with no 'sections' list is structurally invalid -> 422.
    r = client.put("/api/admin/forms/F3/schema", headers=h, json={"schema": {"nope": 1}})
    assert r.status_code == 422

    bad_field_schema = {
        "form_id": "F3",
        "form_title": "F3",
        "version": "1.0",
        "sections": [
            {
                "section_key": "s",
                "section_title": "S",
                "fields": [
                    {
                        "field_key": "s.a",
                        "label": "A",
                        "section": "wrong",
                        "type": "text",
                    }
                ],
            }
        ],
    }
    r = client.put("/api/admin/forms/F3/schema", headers=h, json={"schema": bad_field_schema})
    assert r.status_code == 422


def test_schema_validator_accepts_nested_and_count_dependencies(client):
    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "DEPS", "title": "Deps"})
    schema = {
        "form_id": "DEPS",
        "form_title": "Deps",
        "version": "1.0",
        "sections": [
            {
                "section_key": "s",
                "section_title": "S",
                "fields": [
                    {"field_key": "s.q1", "label": "Q1", "section": "s", "type": "boolean"},
                    {"field_key": "s.q2", "label": "Q2", "section": "s", "type": "boolean"},
                    {
                        "field_key": "s.followup",
                        "label": "Follow-up",
                        "section": "s",
                        "type": "boolean",
                        "depends_on": {"field_keys": ["s.q1", "s.q2"], "min_true": 2},
                    },
                    {
                        "field_key": "s.any_followup",
                        "label": "Any follow-up",
                        "section": "s",
                        "type": "text",
                        "depends_on": {"any": [{"field_key": "s.q1", "value": True}, {"field_key": "s.q2", "value": True}]},
                    },
                ],
            }
        ],
    }

    r = client.put("/api/admin/forms/DEPS/schema", headers=h, json={"schema": schema})

    assert r.status_code == 200, r.text


def test_invalid_workflow_rejected(client):
    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "WFBAD", "title": "WFBAD"})
    r = client.put(
        "/api/admin/forms/WFBAD/workflow",
        headers=h,
        json={"workflow": {"tasks": [{"type": "notify"}], "approval": {"required": True}}},
    )
    assert r.status_code == 422


def test_duplicate_create_conflict(client):
    h = _auth(client)
    assert client.post("/api/admin/forms", headers=h, json={"form_id": "F4", "title": "F4"}).status_code == 201
    assert client.post("/api/admin/forms", headers=h, json={"form_id": "F4", "title": "again"}).status_code == 409


def test_invalid_form_id_rejected(client):
    h = _auth(client)
    r = client.post("/api/admin/forms", headers=h, json={"form_id": "has spaces!", "title": "X"})
    assert r.status_code == 422


def test_delete_form(client):
    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "F5", "title": "F5"})
    assert client.delete("/api/admin/forms/F5", headers=h).status_code == 204
    assert client.get("/api/admin/forms/F5", headers=h).status_code == 404


def test_prompt_field_override_changes_question(client):
    """A builder per-field question override changes the asked question end-to-end.

    Works with no LLM key: the override becomes the rule-based base question text.
    """
    h = _auth(client)
    schema = {
        "form_id": "PF",
        "form_title": "PF",
        "version": "1.0",
        "sections": [
            {
                "section_key": "s1",
                "section_title": "S1",
                "fields": [
                    {
                        "field_key": "s1.name",
                        "label": "Name",
                        "section": "s1",
                        "type": "text",
                        "required": True,
                        "question_text": "What is your name?",
                    }
                ],
            }
        ],
    }
    client.post("/api/admin/forms", headers=h, json={"form_id": "PF", "title": "PF"})
    client.put("/api/admin/forms/PF/schema", headers=h, json={"schema": schema})
    client.post("/api/admin/forms/PF/publish", headers=h)

    # Baseline: the schema's question_text is used.
    s = client.post("/api/session/create", json={"form_id": "PF", "manual_mode": True}).json()
    assert s["next_question"]["question"] == "What is your name?"

    # Set a per-field override; a new session reflects it immediately (cache synced).
    client.put(
        "/api/admin/forms/PF/prompts",
        headers=h,
        json={"prompt": {"system": "You are terse.", "field_overrides": {"s1.name": {"question": "Your full legal name?"}}}},
    )
    s2 = client.post("/api/session/create", json={"form_id": "PF", "manual_mode": True}).json()
    assert s2["next_question"]["question"] == "Your full legal name?"


def test_export_import_roundtrip(client):
    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "EXP", "title": "Exp"})

    bundle = client.get("/api/admin/forms/EXP/export", headers=h).json()
    assert bundle["form_id"] == "EXP"
    assert "schema" in bundle and isinstance(bundle["schema"]["sections"], list)

    # Re-import under a new id.
    bundle["form_id"] = "EXP2"
    r = client.post("/api/admin/forms/import", headers=h, json=bundle)
    assert r.status_code == 201, r.text
    assert r.json()["form_id"] == "EXP2"

    # Importing the same id again conflicts.
    assert client.post("/api/admin/forms/import", headers=h, json=bundle).status_code == 409
