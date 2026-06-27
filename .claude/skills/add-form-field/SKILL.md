---
name: add-form-field
description: Add or change a field on any data-driven form in the Medicaid form platform. Use when adding questions, validation, skip logic, EMR prefill, prompt wording, or PDF mapping.
---

# Add Or Change A Form Field

Forms are data-driven. Prefer schema/config edits over imperative code.

## Where To Edit

- Bundled pack: `backend/app/forms/packs/<FORM_ID>/form.schema.json`
- PDF mapping: `backend/app/forms/packs/<FORM_ID>/pdf.mapping.json`
- Prompt overrides: `backend/app/forms/packs/<FORM_ID>/prompts/field_overrides.json`
- Builder/DB forms: use the admin UI or export/import API shape.

## Field Shape

```json
{
  "field_key": "applicant.middle_name",
  "label": "Middle Name",
  "section": "step1_applicant",
  "type": "text",
  "required": false,
  "sensitive": false,
  "emr_source_candidates": ["middle_name"],
  "question_text": "What is your middle name? Say skip if none.",
  "validation_rule": { "max_length": 64 },
  "depends_on": null,
  "pdf_mapping": { "field_name": "applicant_middle_name", "page": 1, "x": 0, "y": 0 }
}
```

Supported field types are `text`, `textarea`, `date`, `boolean`, `phone`, `ssn`,
`number`, `select`, and `email`.

## Prefill

Prefer the schema-level `prefill` block for new forms:

```json
{
  "prefill": {
    "applicant.phone": { "source": "phone", "transform": "phone10" },
    "applicant.address": { "source": "address.line1" },
    "person1.relationship_to_applicant": { "const": "Self" }
  }
}
```

Supported transforms are defined in `backend/app/forms/mapper.py`.

## PDF Mapping

Each `pdf.mapping.json` entry must use a `field_key` that exists in the schema.
Run or update the drift test in `backend/tests/test_form_logic.py` when changing
schema or mappings. For radio/checkbox mappings, copy the existing `field_type`,
`check_when`, `check_when_value`, or `radio_on_state` patterns.

## Gates

- Backend tests: `cd backend; .\.venv\Scripts\python.exe -m pytest -q`
- Frontend build/lint if UI changed.
- PHI review: set `sensitive: true` for SSN, DOB, immigration IDs, and any field
  that should not be spoken, logged, or sent to an LLM.
