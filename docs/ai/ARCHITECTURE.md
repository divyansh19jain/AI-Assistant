# Architecture — AI-Assistant (ODM 07216 Medicaid form completion)

> Canonical system map. Keep this file accurate; agent rules and Cursor/Claude
> configs link here instead of duplicating it.

## 1. What this app is

An **EMR-assisted + AI-voice-assisted PDF form completion system** for the
**Ohio Department of Medicaid ODM 07216** ("Application for Health Coverage &
Help Paying Costs"). It is *PDF-flow only* — there is **no** browser automation,
online-portal filling, or government-portal submission, by design.

The user journey:

```
Landing (/)                consent + name + DOB
  -> Patient Match         confirm an EMR-matched (masked) patient, or go manual
  -> Assistant (/assistant/:sessionId)
                           one-question-at-a-time collection of missing fields
                           (typed today; voice STT/TTS wired and optional)
  -> Review (/review/:sessionId)
                           all fields grouped by section + source labels
                           -> generate + download filled PDF
```

## 2. Tech stack (authoritative)

| Layer       | Technology |
|-------------|-----------|
| Frontend    | Next.js 14 (App Router), React 18, TypeScript (strict), Tailwind CSS |
| Backend     | Python 3.11, FastAPI, **SQLAlchemy 2.0 (sync)**, Pydantic v2, pydantic-settings, Uvicorn |
| AI / NLP    | LangChain + **langchain-openai (`ChatOpenAI`)**; rule-based fallback when no key |
| Voice       | Browser Web Speech API + backend STT/TTS routes (ElevenLabs/OpenAI/Deepgram-ready) |
| PDF         | PyMuPDF (`fitz`) AcroForm fill, with a generated-summary fallback |
| App DB      | PostgreSQL 15 (Docker) |
| EMR DB      | PostgreSQL (Talbot), **read-only**, parameterized SQL via an adapter |

> ⚠️ **Provider note:** The code uses **OpenAI via LangChain** (`app/ai/llm.py`),
> not Claude. The README's "Anthropic / Claude" section is **stale** — see
> [AI-LLM-INTEGRATION.md](./AI-LLM-INTEGRATION.md) and the
> [IMPROVEMENT-BACKLOG.md](./IMPROVEMENT-BACKLOG.md). Treat `app/ai/llm.py` as the
> single source of truth for which model is called.

## 3. Repository layout

```
backend/                         FastAPI service
  app/
    main.py                      app factory, CORS, router includes, lifespan (create_tables)
    core/                        config (pydantic-settings), security (masking),
                                 audit (audit-log writer), logging (sensitive filter)
    db/                          base (engine/Base), models (ORM), session (get_db + create_tables)
    emr/                         adapter ABC, factory (mock vs real), mock_adapter,
                                 talbot_adapter (raw parameterized SQL), schemas, introspect (CLI)
    forms/                       schema loader (service), mapper (EMR->fields),
                                 missing_fields (dependency-aware), validation, questions
    ai/                          llm (LangChain factory), answer_extractor, question_rewriter,
                                 help_intent, speech_to_text, text_to_speech, stt_router,
                                 tts_router, langgraph_flow
    sessions/                    router + service + schemas  (form session lifecycle)
    patients/                    router + service + schemas  (EMR search)
    admin/                       router (JWT login + dashboard read API)
    pdf/                         pdf_service, mappings/odm_07216_mapping.json, inspect_fields, base PDF
    services/                    zipcode lookup
    forms/schemas/odm_07216.json the form definition that drives ALL form logic
  tests/                         pytest: conftest (SQLite + TestClient), 3 suites
frontend/                        Next.js app
  app/                           routes: / , /patient-match , /assistant/[sessionId] ,
                                 /review/[sessionId] , /admin , /admin/dashboard
  components/                    presentational components (typed via lib/types.ts)
  lib/                           api.ts (fetch client), types.ts, useVoice.ts (STT/TTS hook)
  types/                         speech.d.ts (Web Speech API shims)
docs/ai/                         THIS framework's canonical references
.cursor/rules/                   Cursor rule files (.mdc)
.claude/                         Claude Code settings, commands, agents, skills
docker-compose.yml               db + backend + frontend
```

## 4. Backend layering & request flow

Each feature is a **package of three files**: `router.py` (HTTP), `service.py`
(business logic, owns the DB session), `schemas.py` (Pydantic request/response).
Routers stay thin; they validate input, call a service, shape the response.

```
HTTP -> router (Depends(get_db)) -> service ──> db/ (SQLAlchemy ORM, sync)
                                      ├─> emr/  (factory -> mock|talbot adapter)
                                      ├─> forms/ (schema, mapper, missing_fields, validation, questions)
                                      ├─> ai/    (llm factory; rule-based fallback)
                                      └─> pdf/   (PyMuPDF fill or summary fallback)
core/ (config, security/masking, audit, logging) is cross-cutting.
```

### API surface (prefixes are authoritative)

| Method & path | Purpose |
|---|---|
| `POST /api/patient/search` | Search EMR (masked results) by name + DOB + consent |
| `POST /api/session/create` | Create a form session (with `patient_id` prefill or `manual_mode`) |
| `GET  /api/session/{id}` | Current session state + next question |
| `POST /api/session/{id}/answer` | Submit an answer (extract, validate, advance) |
| `POST /api/session/{id}/skip` | Skip an optional field |
| `POST /api/session/{id}/back` | Go back one field |
| `GET  /api/session/{id}/review` | All fields grouped by section, with source labels |
| `POST /api/session/{id}/generate-pdf` | Generate the filled PDF |
| `GET  /api/session/{id}/download-pdf` | Download the generated PDF |
| `POST /api/stt` | Speech-to-text (audio blob -> text) |
| `POST /api/tts` | Text-to-speech (text -> audio bytes) |
| `POST /api/admin/login` | Admin JWT login |
| `GET  /api/admin/dashboard` | Admin session list/stats (Bearer token) |
| `GET  /health` | Liveness |

## 5. Data model (`app/db/models.py`)

All timestamps are timezone-aware UTC via `utcnow()`. Tables are created at
startup by `create_tables()` (no Alembic migrations yet — see backlog).

- **`form_sessions`** — `id` (str PK), `form_id`, `patient_external_id?`,
  `status` (`active`/`completed`), `mock_mode`, timestamps, `completed_at?`.
- **`form_answers`** — `id`, `session_id` (FK), `field_key`, `value_json` (the
  normalized value), `raw_answer`, `source` (`user`/`voice`/`emr`), `confidence`.
- **`generated_pdfs`** — `id`, `session_id` (FK), `file_path`, `file_name`.
- **`audit_logs`** — `id`, `event_type`, `session_id?`,
  `patient_external_id_masked?`, `metadata_json` (sanitized).

> Relationships use `cascade="all, delete-orphan"`. Field values are stored
> **unmasked** in `form_answers` (needed for PDF fill / review). Masking happens
> at **output** boundaries only — see [SECURITY-AND-PHI.md](./SECURITY-AND-PHI.md).

## 6. The form schema is the engine

`app/forms/schemas/odm_07216.json` is the **single source of truth** for which
fields exist, their types, validation rules, dependencies (skip-logic),
section grouping, question text, and `sensitive` flags. Backend form logic
(`mapper`, `missing_fields`, `validation`, `questions`) and PDF mapping all key
off this file. **Adding/changing form behavior usually means editing this JSON,
not writing imperative code** — see [WORKFLOWS.md](./WORKFLOWS.md).

## 7. Run profiles

| Mode | How | Notes |
|---|---|---|
| App DB | `docker compose up db -d` | Postgres 15, host port **5499** (compose maps `5499:5432`). The README's `5433` is stale — prefer 5499. |
| Backend | `cd backend && uvicorn app.main:app --reload --port 8000` | docs at `/docs`, health at `/health` |
| Frontend | `cd frontend && npm run dev` | http://localhost:3000 |
| Full stack | `docker compose up --build` | fe :3000, be :8000, db :5499 |
| Mock EMR | `USE_MOCK_EMR=true` (default) | no real EMR needed; yellow MOCK banner in UI |
| No-AI | leave `OPENAI_API_KEY` empty | everything works via rule-based fallback, zero AI cost |

See also: [BACKEND-CONVENTIONS.md](./BACKEND-CONVENTIONS.md),
[FRONTEND-CONVENTIONS.md](./FRONTEND-CONVENTIONS.md),
[SECURITY-AND-PHI.md](./SECURITY-AND-PHI.md),
[TESTING.md](./TESTING.md), [WORKFLOWS.md](./WORKFLOWS.md).
