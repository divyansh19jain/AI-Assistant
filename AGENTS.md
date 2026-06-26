# AGENTS.md — AI-Assistant (ODM 07216 Medicaid form completion)

> Master rules for **any** AI coding agent on this repo — Codex / OpenAI CLI,
> Cursor, Claude Code, and others. This is the cross-tool standard entry point.
> The deep references live in [`docs/ai/`](./docs/ai/README.md); this file is the
> short, always-applicable contract. **When in doubt, the code wins over docs.**

## What this is

A healthcare app: **EMR-assisted + AI-voice-assisted PDF completion** of the
**Ohio Medicaid ODM 07216** form. PDF-flow only — no browser automation, no
portal submission. Stack: **FastAPI + SQLAlchemy 2.0 (sync) + Pydantic v2**
backend; **Next.js 14 + React 18 + TypeScript** frontend; **PostgreSQL**;
**LangChain/OpenAI** with a deterministic rule-based fallback; **PyMuPDF** PDFs.

Full map: [`docs/ai/ARCHITECTURE.md`](./docs/ai/ARCHITECTURE.md).

## 🔒 Non-negotiable rules (this is PHI)

1. **Never log PHI** — no names, DOB, SSN, address, phone, email, or raw answers
   in logs, errors, comments, or test fixtures. Log identifiers only
   (`session_id`, `field_key`, `event_type`).
2. **Never hardcode secrets** — connection strings, API keys, JWT secrets,
   passwords live in `.env` only. Never commit `.env` / `.env.local`.
3. **EMR is read-only** and all EMR SQL is **parameterized** (`text()` + bound
   params). No `INSERT/UPDATE/DELETE/DDL`, no string-built SQL, ever.
4. **Mask at output** — patient data leaving the backend is masked (use the
   helpers in `app/core/security.py`); `EMRPatient` (full) is server-side only.
5. **Audit significant actions** with **sanitized** metadata (`app/core/audit.py`).
6. **Keep the disclaimer** on every page and PDF; keep the MOCK-mode banner.

Details + a pre-flight checklist: [`docs/ai/SECURITY-AND-PHI.md`](./docs/ai/SECURITY-AND-PHI.md).
**If a task requires relaxing any rule above, stop and flag it — don't do it silently.**

## How the code is written (match it)

- **Backend** — feature = `router.py` (thin, `Depends(get_db)`) + `service.py`
  (logic + DB) + `schemas.py` (Pydantic v2). Config only via
  `app/core/config.py::get_settings()`. Sync SQLAlchemy 2.0 (`Mapped`/
  `mapped_column`). `async` only for STT/TTS I/O. Type hints with `str | None`.
  Full style: [`docs/ai/BACKEND-CONVENTIONS.md`](./docs/ai/BACKEND-CONVENTIONS.md).
- **Frontend** — App Router client components; backend access **only** via
  `frontend/lib/api.ts`; shared types in `lib/types.ts`; Tailwind utilities +
  shared classes (no UI library). Full style:
  [`docs/ai/FRONTEND-CONVENTIONS.md`](./docs/ai/FRONTEND-CONVENTIONS.md).
- **AI/LLM** — all model access goes through `app/ai/llm.py`
  (`get_chat_model` / `structured_model` / `ai_enabled`). **Every AI feature must
  have a rule-based fallback that runs when the model is `None`.** The provider is
  **OpenAI** (the README's "Claude" section is stale). Details:
  [`docs/ai/AI-LLM-INTEGRATION.md`](./docs/ai/AI-LLM-INTEGRATION.md).
- **The form is data-driven** by `backend/app/forms/schemas/odm_07216.json`.
  Field changes are usually JSON edits, not new imperative code.

## Common tasks → recipes

Add/change a form field, map a new EMR column, add an endpoint, add a component,
wire a real AI provider, enable voice, change the DB schema:
see [`docs/ai/WORKFLOWS.md`](./docs/ai/WORKFLOWS.md).

## Commands

```bash
# App DB (Postgres 15, host port 5499)
docker compose up db -d

# Backend
cd backend && python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000      # http://localhost:8000/docs
pytest tests/ -v                               # tests
python -m app.emr.introspect                   # EMR schema discovery (real EMR mode)

# Frontend
cd frontend && npm install
npm run dev                                    # http://localhost:3000
npm run build && npm run lint                  # typecheck + lint gate

# Full stack
docker compose up --build
```

Defaults: `USE_MOCK_EMR=true` (no real EMR needed), `OPENAI_API_KEY` empty
(rule-based fallback, zero AI cost). Develop against these unless told otherwise.

## Definition of done (the green bar)

- `cd backend && pytest tests/ -v` passes.
- `cd frontend && npm run build && npm run lint` passes.
- A test was added/updated for behavior changes (validation, fields, masking,
  endpoints, prefill).
- The **PHI pre-flight checklist** in `docs/ai/SECURITY-AND-PHI.md` is satisfied.
- A manual smoke through the affected flow (mock EMR, no AI key) when the
  form/session/PDF path changed.

## Now a builder platform

This is no longer a single hardcoded form. It is a **DB-backed, UI-managed multi-form
builder**: admins create forms + their knowledgebase, prompts, skills, and completion
workflows in `/admin`; patients pick a published form and complete it. Read
[`docs/ai/PLATFORM.md`](./docs/ai/PLATFORM.md) for the architecture, entities, and API.

## Scope guardrails

In scope now (added via the platform build): **multiple forms** (form packs + builder),
and **web/portal submission** as an opt-in completion task — but web submission is
**PHI egress** and is gated (per-form opt-in, human approval gate, audited, safe dry-run
default; real portals need a per-portal compliance review). Still out of scope without
an explicit ask: multi-person household (Person 1 only). Prefer the smallest change that
fits existing patterns; flag anything that touches security, auth, CORS, or the data
model.
