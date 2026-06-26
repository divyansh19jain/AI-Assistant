---
name: add-form-field
description: Add or change a field on the data-driven Ohio Medicaid ODM 07216 form. Use when the user wants a new question/field, to make a field required/optional, change its validation, add skip-logic (depends_on), mark it sensitive, or wire its EMR prefill and PDF cell. The form is driven by odm_07216.json — most changes are JSON edits, not new code.
---

# Add / change an ODM 07216 form field

The form is **data-driven** by
`backend/app/forms/schemas/odm_07216.json`. Adding or changing a field is usually
a JSON edit plus a PDF-mapping entry and a test — not new imperative code.

## The field shape (copy an existing field exactly)

Each field in a section's `fields[]` array looks like this:

```json
{
  "field_key": "applicant.middle_name",
  "label": "Middle Name",
  "section": "step1_applicant",
  "type": "text",
  "required": false,
  "sensitive": false,
  "emr_source_candidates": ["middle_name"],
  "question_text": "What is your middle name? (optional, say 'skip' to skip)",
  "validation_rule": { "max_length": 64 },
  "depends_on": null,
  "pdf_mapping": { "field_name": "applicant_middle_name", "page": 1, "x": 0, "y": 0 }
}
```

Field anatomy:
- **`field_key`** — dot-notation, unique, stable (`applicant.first_name`). Code and
  the PDF mapping key off this. Don't rename casually.
- **`type`** — `text` | `date` | `boolean` | `phone` | `ssn` | `choice` (match an
  existing field of the same type for the exact validation shape).
- **`required`** — drives whether it's asked vs skippable.
- **`sensitive`** — `true` for PHI that must **never** be echoed via TTS or sent to
  the LLM (SSN, DOB, etc.). Set this correctly; it's a safety control.
- **`emr_source_candidates`** — `EMRPatient` field name(s) the mapper can prefill
  from. Empty/omit if it can't come from the EMR.
- **`question_text`** — the spoken/typed prompt; the optional LLM rewriter polishes
  it, so write it clearly.
- **`validation_rule`** — e.g. `{"min_length":1,"max_length":64}`, `{"pattern":...}`,
  date/phone/ssn rules. Reuse the shape from a same-type field.
- **`depends_on`** — skip-logic. `null` means always asked; otherwise
  `{ "field_key": "...", "value": ... }` so it's only asked on that branch.

## Steps (recipe A in docs/ai/WORKFLOWS.md)

1. **Schema** — add the field object to the right `section.fields[]` in
   `odm_07216.json`. Set `sensitive: true` if it's PHI.
2. **Prefill** — if it can come from the EMR, set `emr_source_candidates` and
   confirm `app/forms/mapper.py` maps that `EMRPatient` attribute. New EMR column?
   Use the `emr-field-mapping` skill first.
3. **Validation** — only touch `app/forms/validation.py` if a genuinely new value
   type/normalizer is needed; otherwise reuse an existing one.
4. **Dependencies** — `app/forms/missing_fields.py` honors `depends_on`
   automatically; verify the field appears on the right branch and skips on the other.
5. **PDF cell** — add the AcroForm entry in
   `app/pdf/mappings/odm_07216_mapping.json` (use the `pdf-field-mapping` skill —
   it covers `acroform_name`, checkboxes, dates).
6. **Tests** — extend `tests/test_form_logic.py` (prefill + validation + **both**
   dependency branches) and `tests/test_session_api.py` if the PDF changes.

## Gate
- `cd backend && pytest tests/ -v` green.
- 🔒 PHI: `sensitive` set correctly; the field's value never logged; masked at
  output if it appears in search/match. See `docs/ai/SECURITY-AND-PHI.md`.
- If the field is PHI and would be echoed/voiced/sent to the LLM, stop and confirm
  the `sensitive` guard covers it.
