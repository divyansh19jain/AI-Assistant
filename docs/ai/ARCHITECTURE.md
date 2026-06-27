# Architecture

This app is a DB-backed multi-form healthcare assistant. The bundled `ODM_07216`
pack seeds the first form; admins can add more forms without code changes.

## Main Surfaces

```text
frontend/app
  /                         patient form picker and EMR search entry
  /patient-match             masked EMR match selection
  /assistant/[sessionId]     one-question-at-a-time assistant
  /review/[sessionId]        review, edit, approve, workflow status/download
  /admin                     login
  /admin/forms               builder list
  /admin/forms/[formId]      schema, prompts, voice, KB, skills, workflow
  /admin/dashboard           session dashboard

backend/app
  admin/                     builder, KB, skills, dashboard, auth
  forms/                     registry, cache, schema helpers, validation, questions
  sessions/                  create/state/answer/review services
  workflows/                 approval-triggered completion engine
  pdf/                       AcroForm fill and summary fallback
  ai/                        LLM, extraction, rewriter, help intent, KB, STT/TTS
  emr/                       read-only mock/real adapters
  db/                        SQLAlchemy models/session
```

## Data Flow

1. Admin publishes a form.
2. Patient selects a published form.
3. Backend creates a `form_sessions` row and stores `schema_json` snapshot.
4. EMR values are prefilled from legacy or schema-declared mappings.
5. Assistant uses snapshot fields to ask applicable questions.
6. Review displays snapshot fields and stored answers.
7. Approval is rejected until all applicable fields are answered or skipped.
8. Workflow tasks run and record evidence/status.

## DB Tables

- `forms`
- `form_sessions`
- `form_answers`
- `generated_pdfs`
- `audit_logs`
- `kb_documents`
- `kb_chunks`
- `form_skills`
- `form_approvals`
- `workflow_runs`
- `workflow_task_runs`

## API Surface

Patient/public:

- `GET /api/forms`
- `POST /api/patient/search`
- `POST /api/session/create`
- `GET /api/session/{id}`
- `POST /api/session/{id}/answer`
- `POST /api/session/{id}/skip`
- `POST /api/session/{id}/back`
- `GET /api/session/{id}/review`
- `POST /api/session/{id}/approve`
- `GET /api/session/{id}/workflow`
- `POST /api/session/{id}/generate-pdf`
- `GET /api/session/{id}/download-pdf`
- `POST /api/stt`
- `POST /api/tts`

Admin:

- `POST /api/admin/login`
- `GET /api/admin/dashboard`
- `GET/POST /api/admin/forms`
- `GET/PUT/DELETE /api/admin/forms/{id}`
- `PUT /api/admin/forms/{id}/schema`
- `PUT /api/admin/forms/{id}/prompts`
- `PUT /api/admin/forms/{id}/workflow`
- `POST /api/admin/forms/{id}/publish`
- `POST /api/admin/forms/{id}/unpublish`
- `GET /api/admin/forms/{id}/export`
- `POST /api/admin/forms/import`
- `GET/POST /api/admin/forms/{id}/kb`
- `POST /api/admin/forms/{id}/kb/{doc}/reembed`
- `DELETE /api/admin/forms/{id}/kb/{doc}`
- `GET /api/admin/skills`
- `POST /api/admin/skills/{key}/run`
- `GET/PUT /api/admin/forms/{id}/skills`

## Provider Notes

AI helpers route through `backend/app/ai/llm.py` and must keep rule-based fallback
behavior. STT/TTS are exposed through routers and provider services, not through a
parallel legacy module.

## Verification

Use the gate in `AGENTS.md` and `docs/ai/WORKFLOWS.md`.
