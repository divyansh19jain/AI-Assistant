---
description: Add or change a field in a form pack or builder-exported form.
argument-hint: <FORM_ID field_key short description>
---

Add or change a form field: **$ARGUMENTS**

Use the current platform contract:

1. Locate the form definition:
   - bundled pack: `backend/app/forms/packs/<FORM_ID>/form.schema.json`
   - DB-created form: export it from `/api/admin/forms/{id}/export`, edit the
     exported schema shape, then import/update through the admin API/UI.
2. Add/update the field object with `field_key`, `label`, `section`, `type`,
   `required`, `sensitive`, `question_text`, `validation_rule`, and `depends_on`.
3. If EMR prefill is needed, prefer the schema `prefill` block:
   `{"field.key": {"source": "address.line1", "transform": "phone10"}}`.
4. If PDF output needs field filling, update that form pack's `pdf.mapping.json`.
   Use `python -m app.pdf.inspect_fields` for the base PDF's widget names.
5. If the assistant wording changes, update `prompts/field_overrides.json` or the
   builder prompt editor.
6. Add/adjust tests in `backend/tests/test_form_logic.py`, session/PDF tests, or
   admin builder tests as appropriate.
7. Run `.\.venv\Scripts\python.exe -m pytest -q` from `backend`, then frontend
   build/lint if UI was touched.

Do not add PHI to knowledgebase docs, prompts, fixtures, logs, or comments.
