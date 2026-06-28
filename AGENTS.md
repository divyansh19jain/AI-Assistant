# AGENTS.md - AI-Assistant Medicaid Form Platform

Master rules for Codex, Cursor, Claude Code, and any other coding agent working in
this repo. The deep references live in `docs/ai/`; this file is the short contract.
When docs and code disagree, inspect the code and update stale docs.

## What This Is

This is a healthcare form-completion platform:

- Admins create and maintain forms in `/admin`.
- Each published form can have its own schema, prompts, voice settings,
  knowledgebase, skills, PDF mapping, and completion workflow.
- Patients pick a published form, search/match an EMR patient or continue manually,
  answer questions by voice or typing, review answers, approve, then completion tasks
  run (`generate_pdf`, optional `web_submit`).

The bundled Ohio Medicaid `ODM_07216` pack is the seed example, not the platform
boundary. The backend is FastAPI, SQLAlchemy 2.0, Pydantic v2, Alembic, PyMuPDF, and
OpenAI-compatible AI helpers with rule-based fallbacks. The frontend is Next.js 14,
React 18, TypeScript, and Tailwind.

## PHI Rules

1. Never log PHI: names, DOB, SSN, address, phone, email, raw answers, or transcripts.
2. Never hardcode secrets. Use `.env` and keep local env files out of git.
3. EMR access is read-only and parameterized. No string-built SQL.
4. Mask patient output at API/UI boundaries.
5. Audit significant session, approval, PDF, and workflow events with sanitized metadata.
6. KB and prompt content must be form-level guidance only. Do not store patient answers
   in KB docs, embeddings, examples, comments, or fixtures.
7. Web submission is PHI egress. It must remain per-form opt-in, approval-gated,
   audited, and dry-run by default unless a real portal driver is explicitly configured.

## Data Model And Form Contracts

- `forms.schema_json` is the DB source of truth for published form definitions.
- `form_sessions.schema_json` stores an immutable schema snapshot for in-flight
  sessions. Do not route session/review/PDF logic back to the live form when a
  snapshot exists.
- Form pack path: `backend/app/forms/packs/<FORM_ID>/`.
- Pack files: `form.schema.json`, optional `pdf.mapping.json`, `prompts/`,
  `knowledgebase/`, and `workflow.yaml`.
- Runtime helpers:
  - Schema/cache: `backend/app/forms/service.py`, `cache.py`, `registry.py`.
  - Missing fields: `backend/app/forms/missing_fields.py`.
  - Completion readiness gate: `backend/app/forms/readiness.py`.
  - Conversational agent: `backend/app/ai/agent.py` (tool-calling; rule-based fallback).
  - Agent state/voice contracts: `docs/ai/AGENT-STATE-AND-VOICE.md`.
  - Questions/prompts: `backend/app/forms/questions.py`, `prompts.py`.
  - EMR prefill: `backend/app/forms/mapper.py`.
  - PDF: `backend/app/pdf/pdf_service.py`.
  - Approval/workflows: `backend/app/workflows/` (`engine.py` + Temporal: `temporal_*.py`).

## Workflow Tasks

Supported completion task types are:

- `generate_pdf`
- `web_submit`

Unknown task types must fail closed. Do not reintroduce successful no-op task types
such as `notify` or `store_evidence` unless you implement real delivery/evidence
storage and add tests.

### Completion readiness gate

Completion runs through one deterministic gate: `backend/app/forms/readiness.py`
(`GET /api/session/{id}/readiness`). It checks missing applicable/required fields,
stored-answer validation, low-confidence answers, and official-PDF mapping coverage.
The agent's "done", the review UI, the approval route, and PDF generation all consume
it — do not add separate completion rules anywhere else.

### Workflow engine (local | temporal)

`WORKFLOW_ENGINE=local` runs `workflows/engine.py` in-process. `WORKFLOW_ENGINE=temporal`
(Docker Compose default) runs `FormCompletionWorkflow` on a Temporal worker, which
executes that same engine inside an Activity (thread pool sized by
`TEMPORAL_ACTIVITY_WORKERS`). If Temporal is unreachable at approval time the API falls
back to the in-process engine. Both engines keep the same public API and write
`workflow_runs`/`workflow_task_runs`. A `failed` run leaves the session at
`ready_for_review`; only a completed run marks it `completed`. Details:
`docs/ai/WORKFLOWS.md`.

## Agent Workflow

- Read the relevant code path before editing. Trace UI -> API -> DB -> service -> tests.
- Prefer schema/config changes over imperative code when changing a form.
- Add/adjust tests for behavior changes.
- Keep comments short and useful, especially around contracts that are easy to break:
  schema snapshots, approval gates, PHI boundaries, web-submission egress, and PDF
  mapping assumptions.
- Do not revert unrelated user changes.

## Commands

```powershell
# Backend
cd backend
.\.venv\Scripts\python.exe -m pytest -q
uvicorn app.main:app --reload --port 8000

# If the venv is missing:
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Frontend
cd frontend
npm run build
npm run lint
npm run dev

# Database
docker compose up db -d
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head

# Workflow worker (only when WORKFLOW_ENGINE=temporal; Compose runs this for you)
.\.venv\Scripts\python.exe -m app.workflows.temporal_worker
```

## Definition Of Done

- Backend tests pass.
- Frontend build and lint pass for UI changes.
- Alembic migration is present for model/schema changes.
- New form behavior is validated against a non-ODM form when platform behavior changes.
- PDF mapping drift is checked when changing schema or mappings.
- Completion/approval changes go through the readiness gate (`readiness.py`), not
  ad-hoc checks; both workflow engines stay behavior-compatible.
- PHI/security review is done for EMR, logging, KB, voice, approval, auth, CORS, and
  web-submission changes.
