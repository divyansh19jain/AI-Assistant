# Form Pack Authoring

Use this checklist when adding a future Ohio Medicaid, Ohio SNAP, or other benefit
form. The platform should stay form-agnostic; new form behavior belongs in the
form pack, schema, prompts, KB, PDF mapping, and workflow definition.

## Required Files

Pack path:

```text
backend/app/forms/packs/<FORM_ID>/
```

Minimum viable pack:

- `form.schema.json`: sections, fields, validation, dependencies, and question text.
- `pdf.mapping.json`: required when the form must fill an official PDF.
- `prompts/system.md`: form-specific assistant behavior.
- `prompts/field_overrides.json`: field-specific wording and help.
- `knowledgebase/`: general form guidance the assistant can use for explanations.
- `workflow.yaml` or DB workflow JSON: completion tasks such as `generate_pdf`.

DB-created forms may omit `pdf.mapping.json`; they will generate a summary PDF.
Official agency PDF forms should include a mapping and base PDF.

## Field Contract

Every field should have:

- `field_key`: stable dotted key, never reused for a different meaning.
- `label`: short review/admin label.
- `section`: parent `section_key`.
- `type`: one of `text`, `textarea`, `date`, `boolean`, `phone`, `ssn`, `number`, `select`, `email`.
- `required`: whether the field may be skipped.
- `question_text`: plain spoken prompt.
- `validation_rule`: pattern, length, min/max, or allowed values.
- `depends_on`: conditional branch, when applicable.
- `sensitive`: true for values the assistant should not speak back.
- `pdf_exclude`: true only when the official PDF has no field for this schema value.

Do not rely on the LLM to decide whether a field is complete. The readiness gate
uses these schema fields to decide what is answerable, skippable, valid, and ready.

## Knowledgebase

KB content must be form-level guidance, not applicant answers. Good KB topics:

- who counts in a household;
- what counts as income;
- examples of expenses;
- citizenship/immigration terms;
- representative/signature instructions.

The agent retrieves KB snippets using only field metadata such as label and question
text. It does not query KB with the user's raw answer.

## PDF Mapping

For official PDF output:

1. Commit the fillable PDF beside the pack or under `backend/app/pdf/`.
2. Add `pdf.mapping.json` entries with `field_key` and `acroform_name`.
3. Use `field_type`, `check_when`, `check_when_value`, or `radio_on_state` for
   checkboxes/radio buttons.
4. Mark schema fields `pdf_exclude: true` only when intentionally not represented.
5. Run the admin audit and PDF tests.

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_form_logic.py tests/test_odm_pdf_e2e.py -q
```

The static audit is also available through:

```text
GET /api/admin/forms/<FORM_ID>/audit
```

## Readiness Gate

Before approval, the backend checks:

- all applicable fields are answered or explicitly skipped;
- required fields are present;
- stored values still validate against the session schema snapshot;
- low-confidence answers are corrected or reconfirmed;
- official-PDF answered fields are mapped.

Use:

```text
GET /api/session/<SESSION_ID>/readiness
```

Review, approval, direct PDF generation, and workflow completion all use this same
gate. Do not add another completion rule somewhere else.

## Add-A-Form Checklist

1. Create/import the form in `/admin/forms` or add a pack folder.
2. Define fields and dependency rules.
3. Add plain-language prompts and KB guidance.
4. Add PDF mapping for official PDF output.
5. Publish the form.
6. Create a manual session and complete it with typed answers.
7. Confirm review readiness is `ready: true`.
8. Approve and generate the PDF.
9. Open the PDF and verify visible values.
10. Add regression tests for dependencies, readiness, and representative PDF fields.
