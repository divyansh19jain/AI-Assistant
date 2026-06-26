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
