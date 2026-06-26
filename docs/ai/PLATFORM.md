# Platform — the DB-backed, UI-managed multi-form builder

> This supersedes the single-form framing in [ARCHITECTURE.md](./ARCHITECTURE.md).
> The app is now a **builder platform**: admins create/manage forms (and their KB,
> prompts, skills, and completion workflows) in a UI; patients pick a published form
> and complete it with EMR + voice assistance, then **review → approve → complete**.

## How it fits together

```
ADMIN (/admin, JWT)                          PATIENT (/)
  Form Builder                                 pick a published form (GET /api/forms)
   ├ schema/field editor   ─┐                   → search/match (masked) or manual
   ├ prompts & voice        │  forms table       → assistant: one Q at a time
   ├ knowledgebase (RAG)    │  (schema_json,      → review → "Approve & Complete"
   ├ skills (capabilities)  │   prompt_json,           │
   └ completion workflow   ─┘   voice_json,            ▼
                                workflow_json)     approval gate → workflow engine
                                                    → generate_pdf / web_submit / …
```

**Source of truth = the database.** The bundled filesystem **packs**
(`backend/app/forms/packs/<FORM_ID>/`) are the seed + import/export format. On boot,
`seed_from_packs()` imports any pack not already in the `forms` table; thereafter the
DB wins. The form **engine is unchanged** — it reads the schema from a process-local
cache (`app/forms/cache.py`, DB-backed with a pack fallback) so call sites keep their
no-`db` signatures.

## Entities (DB)

| Table | What | Edited via |
|---|---|---|
| `forms` | `schema_json` (fields), `prompt_json`, `voice_json`, `workflow_json`, status, output_targets | builder CRUD |
| `kb_documents` / `kb_chunks` | per-form RAG docs + embeddings (JSON vectors) | KB manager |
| `form_skills` | which built-in capabilities a form uses | Skills toggles |
| `form_approvals` | the human approval before completion | patient approve |
| `workflow_runs` / `workflow_task_runs` | each completion run + per-task status/evidence | (runtime) |
| `form_sessions` / `form_answers` / `generated_pdfs` / `audit_logs` | runtime (unchanged) | — |

## Subsystems

- **Registry + cache** — `app/forms/registry.py` (discover packs), `app/forms/cache.py`
  (DB schema cache + pack fallback), `app/forms/seed.py` (seed DB from packs).
- **Prompts + voice** — `app/forms/prompts.py`: per-form AI persona + per-field
  question/help overrides + voice config, injected into `question_rewriter` /
  `help_intent` and `get_tts_service(form_id)` / the STT vocabulary. Field-question
  overrides work even with **no LLM key**.
- **Knowledgebase (RAG)** — `app/ai/kb.py`: chunk + embed (OpenAI when keyed, else a
  **deterministic local hashing embedding** so it runs offline) + cosine retrieval.
  Injected into the "explain this question" path. 🔒 PHI-free; queries are field-level.
- **Skills** — `app/skills/registry.py`: built-in capabilities (`zip_lookup`,
  `kb_lookup`, `glossary`) with `run_skill()`; attached per form via `form_skills`.
- **Workflow engine** — `app/workflows/engine.py`: ordered tasks
  (`generate_pdf` | `web_submit` | `notify` | `store_evidence`) run after the approval
  gate, recording each task's status + output/evidence. Stops at first failure.
- **Web submission** — `app/workflows/web_submit.py`: a **dry-run mock driver by
  default** (no network), with a real Playwright-over-Browserless driver gated behind
  `WEB_SUBMIT_DRIVER=browserless` + `BROWSERLESS_URL`.

## API additions (all admin routes behind the JWT `_verify_token`)

- Forms: `GET/POST /api/admin/forms`, `GET/PUT/DELETE /api/admin/forms/{id}`,
  `PUT …/schema`, `PUT …/prompts`, `PUT …/workflow`, `POST …/publish` · `…/unpublish`,
  `GET …/export`, `POST /api/admin/forms/import`.
- KB: `GET/POST /api/admin/forms/{id}/kb`, `…/{doc}/reembed`, `DELETE …/{doc}`.
- Skills: `GET /api/admin/skills`, `POST /api/admin/skills/{key}/run`,
  `GET/PUT /api/admin/forms/{id}/skills`.
- Public/patient: `GET /api/forms` (published), `POST /api/session/{id}/approve`,
  `GET /api/session/{id}/workflow`.

## Add a form tomorrow

1. **In the UI:** `/admin` → Form Builder → New Form → edit the schema/fields, prompts
   & voice, KB, skills, and the completion workflow → Publish. It appears in the patient
   picker immediately and is runnable end-to-end.
2. **As a pack (git-friendly):** copy `backend/app/forms/packs/ODM_07216/` to a new
   `<FORM_ID>/`, edit `form.schema.json` (+ optional `prompts/`, `knowledgebase/`,
   `pdf.mapping.json`, `workflow.yaml`); it's seeded on boot. Or export an existing
   form (`GET …/export`) and `POST …/import` it elsewhere.

## 🔒 Web-submission compliance (Phase G)

Web submission is **PHI egress** to third-party portals and is gated by: per-form
opt-in (the `web_submit` task must be added to the workflow), the **human approval
gate**, audit events (`workflow_completed`/`failed`), and a **safe dry-run default**
(no real submission unless a Browserless driver is explicitly configured). Per-portal
data-processing/BAA review is required before enabling a real portal. KB/prompt content
must stay PHI-free; the vector index never stores patient answers.

## Phase log (all on `main`, each green)

A (DB authority + harness + Alembic + PHI search-masking) · B (builder CRUD + UI +
picker) · C (prompt packs + voice) · D (knowledgebase RAG) · E (skills) · F (workflows
+ approval gate, PDF) · G (web submission) · H (import/export, CORS/auth lock, eslint,
CI, docs).
