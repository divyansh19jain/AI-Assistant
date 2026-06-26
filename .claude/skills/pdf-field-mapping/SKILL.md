---
name: pdf-field-mapping
description: Map a form field_key to an AcroForm widget in the ODM 07216 PDF. Use when a field isn't landing in the generated PDF, when adding a new field's PDF cell, or when handling checkboxes/radios/date formatting. Covers discovering real widget names with inspect_fields.py and the mapping entry shape (acroform_name, field_type, check_when).
---

# Map a `field_key` to an ODM 07216 PDF widget

The mapping lives in `backend/app/pdf/mappings/odm_07216_mapping.json`. Strategy is
`acroform_first`: PyMuPDF fills the named AcroForm widget; the `x/y/page` coords are
a **fallback** text-insertion point used only if AcroForm fill fails. Recipe A
step 6 in `docs/ai/WORKFLOWS.md`.

## 1. Discover the real widget name (don't guess)

```bash
cd backend && .\.venv\Scripts\Activate.ps1
python -m app.pdf.inspect_fields
```
This prints the **actual AcroForm field names** from the base PDF
(`ODM07216fillx.pdf`). The names are messy and literal (e.g. `"1 First name"`,
`"2 Home address Check here if you are Homeless"`, `"undefined"`, `"undefined_2"`).
Use them **verbatim** as `acroform_name`.

## 2. Add the mapping entry

Text field:
```json
{"field_key": "applicant.last_name", "acroform_name": "Last name", "page": 5, "x": 400, "y": 660, "font_size": 10}
```

Checkbox (set `field_type`; control when it's checked):
```json
{"field_key": "applicant.is_homeless", "acroform_name": "undefined", "page": 5, "x": 176, "y": 635, "font_size": 10, "field_type": "checkbox"}
```

Radio / multi-state — one entry per option, keyed by the answer value:
```json
{"field_key": "applicant.voter_registration_choice", "acroform_name": "Yes I want to register",            "page": 5, "x": 53,  "y": 479, "field_type": "checkbox", "check_when_value": "yes"},
{"field_key": "applicant.voter_registration_choice", "acroform_name": "No I do not want to register to vote", "page": 5, "x": 172, "y": 479, "field_type": "checkbox", "check_when_value": "no"}
```

Boolean checkbox pair (check on `true` vs `false`): use `"check_when": true` /
`"check_when": false` on the two entries (see the `applicant.email_preference`
pair in the file).

## Entry fields
- **`field_key`** — must match the schema `field_key` exactly.
- **`acroform_name`** — exact widget name from `inspect_fields.py`.
- **`field_type`** — omit for text; `"checkbox"` for check/radio widgets.
- **`check_when` / `check_when_value`** — when a checkbox should be ticked
  (by boolean or by the field's answer value).
- **`page`, `x`, `y`, `font_size`** — fallback text placement (PDF points,
  bottom-left origin). Only used if AcroForm fill fails.

## Formatting rules
- **Dates**: stored ISO (`YYYY-MM-DD`); the PDF wants `MM/DD/YYYY` — follow how the
  existing date fields are handled in `app/pdf/pdf_service.py`.
- Keep the **disclaimer** in both AcroForm and the summary-fallback output.

## Gate
- Generate a PDF through the flow (mock EMR, no AI key) and confirm the value lands
  in the right cell / the right box is ticked.
- Extend `tests/test_session_api.py` (it exercises the PDF generation/fallback path).
- 🔒 Generated PDFs contain full PHI — they go to `PDF_OUTPUT_DIR` (gitignored) and
  are served only by the session-scoped download endpoint. Don't expose the dir.
