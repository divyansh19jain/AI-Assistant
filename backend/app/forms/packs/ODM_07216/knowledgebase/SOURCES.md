# Knowledgebase sources — ODM 07216

The AI uses this knowledgebase (Phase 3, via `app/ai/kb.py`) to help the user
understand a question — e.g. "what counts as income?", "who is in my household?".

## 🔒 NO-PHI attestation

Every document placed in this directory **must be general, form-level guidance with
NO Protected Health Information** — no patient names, DOB, SSN, addresses, or any
real applicant data. Patient answers are **never** embedded or stored in the vector
index. KB retrieval queries are built from **field-level text** (the field's
label/question), not from the user's free-text answer, and retrieval is skipped for
`sensitive` fields. See [`docs/ai/KNOWLEDGEBASE-RAG.md`](../../../../../../docs/ai/KNOWLEDGEBASE-RAG.md).

## Provenance

| Document | Source | Retrieved | Notes |
|----------|--------|-----------|-------|
| _(none yet)_ | — | — | Seed ODM eligibility/field-help guidance here in Phase 3. |

> `manifest.json` has `knowledgebase.enabled: false`. Set it to `true` after adding
> documents and running `python -m app.ai.kb_ingest ODM_07216`.
