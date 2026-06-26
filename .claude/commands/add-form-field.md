---
description: Guided ODM 07216 field addition (schema → prefill → validation → PDF → tests).
argument-hint: <field key + short description, e.g. applicant.middle_initial "middle initial">
---

Add or change an ODM 07216 form field: **$ARGUMENTS**

The form is **data-driven** by
[backend/app/forms/schemas/odm_07216.json](../../backend/app/forms/schemas/odm_07216.json)
— prefer JSON edits over imperative code. Follow recipe A in
[docs/ai/WORKFLOWS.md](../../docs/ai/WORKFLOWS.md):

1. **Schema** — add the field to `odm_07216.json` with `key` (dot-notation),
   `label`, `type`, `section`, `question_text`, validation rule, `required`, any
   `depends_on` (skip-logic), and `"sensitive": true` if it's PHI that must never
   be echoed/logged.
2. **Prefill** (if it can come from the EMR) — map it in
   `app/forms/mapper.py` from the `EMRPatient` field. New EMR column? Use
   `/emr-introspect` and recipe B first.
3. **Validation** — extend `app/forms/validation.py` only if a new value
   type/normalizer is needed; reuse existing boolean/date/phone/SSN normalizers.
4. **Missing-field logic** — `app/forms/missing_fields.py` honors `depends_on`
   automatically; verify the field appears/skips on the right branch.
5. **Question phrasing** — set good `question_text`; the optional LLM rewriter
   improves it (`app/forms/questions.py`).
6. **PDF mapping** — add the `field_key → widget` entry in
   `app/pdf/mappings/odm_07216_mapping.json`. Discover widget names with
   `python -m app.pdf.inspect_fields`. Handle date format (ISO → MM/DD/YYYY) and
   radio/checkbox on-states like the existing entries.
7. **Tests** — extend `tests/test_form_logic.py` (prefill + validation +
   dependency branch) and `tests/test_session_api.py` if the PDF is affected.
8. **Gate** — `pytest tests/ -v` + PHI checklist (sensitive flag set if PHI? not
   logged? masked at output?).

State the exact field `key`, `type`, section, and whether it's `sensitive` before
editing. If anything is ambiguous, ask. The `add-form-field` skill has the full
JSON shape and examples.
