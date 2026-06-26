---
description: Safely discover real EMR schema (read-only) and map a column into EMRPatient.
argument-hint: <optional: column/field you want to map, e.g. "patient mobile phone">
---

Discover real EMR schema and (optionally) map a column: **$ARGUMENTS**

🔒 The EMR is **read-only**. This command only reads schema — never patient
values, never writes. Follow recipe B in
[docs/ai/WORKFLOWS.md](../../docs/ai/WORKFLOWS.md).

1. **Introspect** (prints schema/columns, no patient values):
   ```bash
   cd backend && .\.venv\Scripts\Activate.ps1
   python -m app.emr.introspect
   ```
   This requires real-EMR mode + a connection string in `.env` (not mock). If the
   user is in mock mode and hasn't provided EMR access, stop and ask — don't
   fabricate column names.
2. **Map the column** into
   [app/emr/talbot_adapter.py](../../backend/app/emr/talbot_adapter.py): extend the
   parameterized `text()` SELECT and map the column into `EMRPatient`. Keep:
   - **named bind params only** (no string interpolation),
   - the soft-delete filter (`"IsDeleted" = false`) and any tenant scoping,
   - graceful degradation (log without PHI, return `None`/`[]` on error).
3. **Schema model** — add the field to `app/emr/schemas.py` (`EMRPatient`; add to
   `MaskedPatient` only if it should appear in masked search output, and mask it
   in `app/core/security.py` first).
4. **Mock parity** — add the field to `app/emr/mock_adapter.py` sample data so
   mock mode mirrors real mode.
5. **Tests** — extend `tests/test_patient_search.py` (masking + search) and the
   prefill test in `tests/test_form_logic.py`.
6. **Gate** — tests green; confirm EMR stays read-only and unmasked `EMRPatient`
   never reaches an HTTP response.

The `emr-field-mapping` skill has the parameterized-SELECT pattern and masking
checklist.
