# Workflows

Common playbooks for changing the platform. Always finish with backend tests and,
for UI changes, frontend build/lint.

## Add Or Change A Form Field

1. Identify the form:
   - pack: `backend/app/forms/packs/<FORM_ID>/form.schema.json`
   - DB form: edit in `/admin/forms` or export/import the form bundle.
2. Add/update the field object: `field_key`, `label`, `section`, `type`,
   `required`, `sensitive`, `question_text`, `validation_rule`, `depends_on`.
3. For EMR prefill, prefer schema `prefill`:
   `{"field.key": {"source": "address.line1", "transform": "phone10"}}`.
4. For field-filled PDF output, update that form's `pdf.mapping.json`.
5. For wording, update prompt overrides or the builder prompt editor.
6. Add tests for validation, dependencies, prefill, and PDF mapping drift.

## Add A New Form

1. Create it in `/admin/forms` or copy `backend/app/forms/packs/ODM_07216/`.
2. Define sections and fields in `form.schema.json`.
3. Add optional prompts, voice settings, KB docs, skills, PDF mapping, workflow.
4. Publish it.
5. Smoke test patient selection, assistant flow, review, approval, and PDF output.

## Change Workflow Behavior

Supported tasks are `generate_pdf` and `web_submit`.

1. Validate builder/API behavior in `backend/app/admin/forms_router.py`.
2. Implement task behavior in `backend/app/workflows/engine.py`.
3. Web submission recipes must include `portal_url`; real portal submission requires
   Browserless configuration and compliance review.
4. Unknown tasks must fail closed.
5. Add tests in `backend/tests/test_workflow.py`.

## Database Schema Change

1. Update `backend/app/db/models.py`.
2. Add an Alembic migration under `backend/alembic/versions/`.
3. Keep migrations compatible with existing DBs when possible.
4. Run `.\.venv\Scripts\python.exe -m alembic upgrade head`.
5. Add or update tests.

## EMR Mapping

1. Run `python -m app.emr.introspect` only in approved real-EMR mode.
2. Keep SQL read-only and parameterized.
3. Extend `EMRPatient` and adapters as needed.
4. Preserve mock parity in `mock_adapter.py`.
5. Add tests for masking and prefill.

## Frontend Changes

1. Types in `frontend/lib/types.ts`.
2. API access only through `frontend/lib/api.ts`.
3. Preserve PHI masking, disclaimers, mock-mode indicators, and approval gates.
4. Run `npm run build` and `npm run lint`.

## Verification Gate

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm run build
npm run lint
```
