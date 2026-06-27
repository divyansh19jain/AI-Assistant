---
name: pdf-field-mapping
description: Map a form field_key to a form pack PDF widget or fallback coordinate. Use when a field is not landing in a generated PDF, when adding a new field's PDF cell, or when handling checkbox/radio/date formatting.
---

# Map a `field_key` to a PDF widget

PDF mappings live beside the form pack:

`backend/app/forms/packs/<FORM_ID>/pdf.mapping.json`

The ODM 07216 pack is the reference implementation. Its mapping uses
`acroform_first`: PyMuPDF fills the named AcroForm widget first, and the `page` /
`x` / `y` values are fallback text-insertion coordinates used only if AcroForm
fill fails. DB-created forms without a mapping still get a generated summary PDF.

## 1. Discover the real widget name

For the bundled ODM base PDF:

```bash
cd backend
.\.venv\Scripts\python.exe -m app.pdf.inspect_fields
```

The script prints the actual AcroForm names from `ODM07216fillx.pdf`. Use widget
names verbatim. For another form, add an equivalent inspection script or adapt
`app/pdf/inspect_fields.py` to point at that pack's `base_pdf`.

## 2. Add the mapping entry

Text field:

```json
{"field_key": "applicant.last_name", "acroform_name": "Last name", "page": 5, "x": 400, "y": 660, "font_size": 10}
```

Checkbox:

```json
{"field_key": "applicant.is_homeless", "acroform_name": "Homeless", "page": 5, "x": 176, "y": 635, "font_size": 10, "field_type": "checkbox"}
```

Radio or multi-state checkbox, one entry per option:

```json
{"field_key": "applicant.voter_registration_choice", "acroform_name": "Yes I want to register", "page": 5, "x": 53, "y": 479, "field_type": "checkbox", "check_when_value": "yes"}
```

Boolean checkbox pairs use `"check_when": true` and `"check_when": false` on the
two entries.

## Entry fields

- `field_key` must match the form schema exactly.
- `acroform_name` is the exact PDF widget name.
- `field_type` is omitted for text and set to `"checkbox"` for check/radio widgets.
- `check_when` / `check_when_value` control when checkbox widgets are ticked.
- `page`, `x`, `y`, and `font_size` are fallback placement values in PDF points.

## Gate

- Add or update tests in `backend/tests/test_session_api.py` or
  `backend/tests/test_form_logic.py` for behavior changes.
- Run `cd backend; .\.venv\Scripts\python.exe -m pytest -q`.
- Generated PDFs contain PHI and must stay in `PDF_OUTPUT_DIR`, served only by the
  session-scoped download endpoint.
