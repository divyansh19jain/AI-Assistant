---
name: emr-field-mapping
description: Map a real EMR (Talbot) column into EMRPatient for prefill, the read-only + parameterized way. Use when wiring a new EMR-sourced value, extending the patient SELECT, or adding a field to masked search output. Covers the named-bind-param SELECT pattern, masking, mock parity, and the read-only guarantee.
---

# Map an EMR column into `EMRPatient` (read-only, parameterized)

🔒 The EMR is **read-only**. Only `SELECT`, only parameterized `text()` with
**named bind params**. Never `INSERT/UPDATE/DELETE/DDL`, never string-build SQL.
Full rules: `docs/ai/SECURITY-AND-PHI.md` §5. Recipe B in `docs/ai/WORKFLOWS.md`.

## 1. Discover the real schema (no patient values)

```bash
cd backend && .\.venv\Scripts\Activate.ps1
python -m app.emr.introspect
```
This needs real-EMR mode + a connection string in `.env`. If the user is in mock
mode and hasn't provided EMR access, **stop and ask** — never invent column names.

## 2. Extend the adapter SELECT (`app/emr/talbot_adapter.py`)

The required pattern — named bind params only, soft-delete filter, graceful
degradation:

```python
query = text(
    'SELECT "FirstName", "LastName", "NewColumn" '
    'FROM "Patient" '
    'WHERE LOWER("FirstName") LIKE LOWER(:fn) AND "IsDeleted" = false'
)
rows = conn.execute(query, {"fn": f"{first_name}%"})   # bind params, never f-string into SQL
```

Map the new column into `EMRPatient`. Keep the broad `try/except` that logs the
failure **class** (no PHI) and returns `None`/`[]` so an EMR outage never hard-fails
the app.

## 3. Add it to the schema model (`app/emr/schemas.py`)

- Add the field to **`EMRPatient`** (full, server-side only).
- Add it to **`MaskedPatient`** *only* if it should appear in masked search/match
  output — and mask it in `app/core/security.py` **first** (`mask_name`/`mask_dob`/
  `mask_phone`/`mask_ssn` or a new helper). 🔒 `EMRPatient` must never be
  serialized to an HTTP response.

## 4. Mock parity (`app/emr/mock_adapter.py`)

Add the field to the mock sample data so mock mode mirrors real mode (the default
dev/test profile is mock). Tests and the UI depend on this parity.

## 5. Prefill (`app/forms/mapper.py`)

If a form field should prefill from this column, set the field's `prefill` block
or legacy `emr_source_candidates` entry in the relevant form pack schema and
confirm `app/forms/mapper.py` reads the new `EMRPatient` attribute.

## Gate
- `cd backend && pytest tests/ -v` — extend `tests/test_patient_search.py`
  (masking + search) and the prefill test in `tests/test_form_logic.py`.
- 🔒 Confirm: SQL parameterized + read-only, soft-delete filter intact, unmasked
  `EMRPatient` never leaves the backend, new sensitive field masked before search
  output. Note any mock/real search-semantics difference (mock uses `startswith`,
  Talbot uses `LIKE`).
