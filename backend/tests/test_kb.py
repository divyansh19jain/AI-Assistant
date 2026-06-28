"""Tests for the knowledgebase (RAG) — engine + admin CRUD.

Runs fully offline: with no OPENAI_API_KEY, app/ai/kb.py uses a deterministic local
hashing embedding, so ingest + retrieval are exercised without any API call.
"""


def _auth(client) -> dict:
    r = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_kb_chunk_and_embed_offline():
    from app.ai.kb import chunk_text, embed_texts, _cosine

    chunks = chunk_text(
        "Income is money you earn from a job.\n\nYour household includes people you live with."
    )
    assert len(chunks) >= 1
    vecs = embed_texts(chunks)
    assert len(vecs) == len(chunks)
    # A related query is more similar to some chunk than an unrelated one.
    q_income = embed_texts(["what counts as income from a job"])[0]
    assert max(_cosine(q_income, v) for v in vecs) > 0


def test_kb_engine_ingest_and_retrieve(db):
    from app.ai.kb import ingest_document, retrieve
    from app.db.models import KbDocument

    doc = KbDocument(
        form_id="F",
        doc_key="income",
        title="Income",
        text=(
            "Income is money you earn from a job, self-employment, or government benefits. "
            "Report your gross wages before taxes are taken out.\n\n"
            "Your household includes you, your spouse, and anyone you claim as a dependent."
        ),
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    assert ingest_document(db, doc) >= 1
    assert doc.status == "embedded"

    hits = retrieve(db, "F", "what counts as income from my job", k=2)
    assert hits, "expected at least one KB hit"
    assert any("income" in h.lower() for h in hits)

    # A form with no KB returns nothing (graceful disable).
    assert retrieve(db, "OTHER_FORM", "income", k=2) == []


def test_kb_crud_via_api(client):
    h = _auth(client)
    client.post("/api/admin/forms", headers=h, json={"form_id": "KBF", "title": "KBF"})

    r = client.post(
        "/api/admin/forms/KBF/kb",
        headers=h,
        json={"title": "Income guidance", "text": "Income is money you earn from a job, self-employment, or benefits."},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "embedded"
    assert r.json()["chunk_count"] >= 1

    docs = client.get("/api/admin/forms/KBF/kb", headers=h).json()
    assert len(docs) == 1
    doc_id = docs[0]["id"]

    assert client.delete(f"/api/admin/forms/KBF/kb/{doc_id}", headers=h).status_code == 204
    assert client.get("/api/admin/forms/KBF/kb", headers=h).json() == []


def test_kb_requires_existing_form(client):
    h = _auth(client)
    assert client.get("/api/admin/forms/NOPE/kb", headers=h).status_code == 404
    r = client.post(
        "/api/admin/forms/NOPE/kb",
        headers=h,
        json={"title": "Nope", "text": "General guidance."},
    )
    assert r.status_code == 404


def test_help_kb_query_excludes_raw_question(monkeypatch):
    from app.ai import help_intent

    captured = {}

    def fake_retrieve(db, form_id, query, k=3):
        captured["query"] = query
        return []

    class FakeDb:
        def close(self):
            pass

    monkeypatch.setattr("app.ai.kb.retrieve", fake_retrieve)
    monkeypatch.setattr("app.db.base.SessionLocal", lambda: FakeDb())

    help_intent._kb_context("F", "SSN", "Why do you need my SSN?", "my ssn is 123-45-6789")
    assert "123-45-6789" not in captured["query"]
    assert captured["query"] == "SSN Why do you need my SSN?"


def test_bundled_odm_kb_is_seeded_and_searchable(db):
    from app.ai.kb import retrieve
    from app.db.models import KbDocument
    from app.forms.seed import seed_from_packs, seed_kb_from_packs

    seed_from_packs(db)
    changed = seed_kb_from_packs(db)
    assert changed >= 4

    docs = db.query(KbDocument).filter(KbDocument.form_id == "ODM_07216").all()
    assert {d.doc_key for d in docs} >= {
        "application-interview-playbook",
        "eligibility-screening-2026",
        "household-and-income-guidance",
        "special-pathways-and-coverage",
    }
    assert all(d.status == "embedded" for d in docs)

    hits = retrieve(db, "ODM_07216", "income limit qualify household", k=4)
    assert hits
    assert any("final decision" in h.lower() or "income" in h.lower() for h in hits)

    # Idempotent startup behavior: once embedded and unchanged, a second seed is a no-op.
    assert seed_kb_from_packs(db) == 0


def test_odm_field_overrides_point_to_real_schema_fields():
    import json
    from pathlib import Path

    root = Path("app/forms/packs/ODM_07216")
    schema = json.loads((root / "form.schema.json").read_text(encoding="utf-8"))
    field_keys = {
        field["field_key"]
        for section in schema["sections"]
        for field in section["fields"]
    }
    overrides = json.loads((root / "prompts" / "field_overrides.json").read_text(encoding="utf-8"))["overrides"]
    unknown = sorted(set(overrides) - field_keys)
    assert unknown == []


def test_odm_pack_prompt_defaults_merge_under_db_prompt():
    from app.forms import prompts

    prompts.clear()
    prompts.set_prompt_pack("ODM_07216", {"system": "Custom system", "field_overrides": {}}, {})
    assert prompts.get_system_persona("ODM_07216") == "Custom system"
    assert "self-employed" in prompts.get_field_override("ODM_07216", "income.has_employment")["question"]
    assert "Women, Infants, and Children" in prompts.get_field_override("ODM_07216", "applicant.programs.wic")["help"]

    prompts.set_prompt_pack(
        "ODM_07216",
        {
            "system": "Custom system",
            "field_overrides": {
                "income.has_employment": {"question": "Custom employment question?"}
            },
        },
        {},
    )
    assert prompts.get_field_override("ODM_07216", "income.has_employment")["question"] == "Custom employment question?"
    assert "currently pregnant" in prompts.get_field_override("ODM_07216", "person1.pregnant")["question"]
