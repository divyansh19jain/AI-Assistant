# Platform - DB-Backed Multi-Form Builder

The app is a form-completion platform. `ODM_07216` is the bundled seed form, not a
hardcoded product limit.

## Flow

```text
Admin builder
  forms.schema_json
  forms.prompt_json
  forms.voice_json
  forms.workflow_json
  KB documents / chunks
  attached skills
        |
        v
Published form picker
        |
        v
Session create -> form_sessions.schema_json snapshot
        |
        v
Assistant asks applicable questions -> review -> approve
        |
        v
Workflow engine: generate_pdf, optional web_submit
```

## Source Of Truth

- Database is authoritative after seed/import.
- Bundled packs live at `backend/app/forms/packs/<FORM_ID>/`.
- Pack files:
  - `form.schema.json`
  - optional `pdf.mapping.json`
  - optional `prompts/system.md`
  - optional `prompts/field_overrides.json`
  - optional `knowledgebase/`
  - optional `workflow.yaml`
- `app/forms/cache.py` provides a process-local schema cache for published DB forms.
- `app/forms/registry.py` is the filesystem-pack fallback and import/seed format.

## Session Snapshot Contract

On session creation, the live form schema is copied into `form_sessions.schema_json`.
All session state, answer validation, missing-field logic, review data, approval
checks, and PDF summary generation must use that snapshot. This prevents in-flight
sessions from changing when an admin edits, republishes, or deletes a form later.

## Key Tables

| Table | Purpose |
|---|---|
| `forms` | form schema, prompt, voice, workflow, status, output targets |
| `form_sessions` | runtime session plus immutable schema snapshot |
| `form_answers` | patient answers and source metadata |
| `kb_documents` / `kb_chunks` | per-form PHI-free RAG content and embeddings |
| `form_skills` | built-in skills attached to a form |
| `form_approvals` | human approval records |
| `workflow_runs` / `workflow_task_runs` | completion execution and evidence |
| `generated_pdfs` | generated file records |
| `audit_logs` | sanitized audit events |

## Supported Workflow Tasks

- `generate_pdf`
- `web_submit`

Unknown task types fail closed. Do not add successful no-op tasks. The admin API and
builder UI validate task types before saving.

## PDF Behavior

If a form has `pdf.mapping.json` and the referenced `base_pdf` is present, the PDF
service fills AcroForm widgets. If not, it generates a generic data-summary PDF from
the session schema snapshot. Every mapping `field_key` should exist in that form's
schema; `backend/tests/test_form_logic.py` contains a drift regression for ODM.

## Knowledgebase And Prompts

Knowledgebase documents must be PHI-free form guidance. Help-intent retrieval uses
field-level query text only; raw patient utterances are not embedded into KB queries.
Prompt overrides are per form and can be edited in the builder or stored in a pack.

## Web Submission

`web_submit` is PHI egress. It is only allowed after human approval and only when the
form workflow opts in. The default driver is dry-run and does not make network calls.
Real portal submission requires `WEB_SUBMIT_DRIVER=browserless`, `BROWSERLESS_URL`,
a recipe with `portal_url`, selectors, and a separate compliance review.

## Add A New Form Tomorrow

1. Create it in `/admin/forms` or add a pack under `backend/app/forms/packs/<FORM_ID>/`.
2. Define `form.schema.json` with sections and fields.
3. Add optional `prefill` mappings for EMR values.
4. Add prompt/voice settings and PHI-free KB documents.
5. Add `pdf.mapping.json` only if field-filled PDF output is required.
6. Configure workflow tasks. Use `generate_pdf`; add `web_submit` only with a real recipe.
7. Publish the form and run a patient-flow smoke test.

## Verification

- Backend: `cd backend; .\.venv\Scripts\python.exe -m pytest -q`
- Frontend: `cd frontend; npm run build; npm run lint`
- Migration changes: `cd backend; .\.venv\Scripts\python.exe -m alembic upgrade head`
