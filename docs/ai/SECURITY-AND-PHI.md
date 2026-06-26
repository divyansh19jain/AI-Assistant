# Security & PHI Rules (HIPAA-relevant) — NON-NEGOTIABLE

> This app handles **Protected Health Information** (patient names, DOB, SSN,
> address, contact info, Medicaid eligibility data). Every agent and every human
> edit MUST follow these rules. When a change would touch any rule below, stop
> and call it out explicitly in your summary.

## 0. The golden rules (read first)

1. **Never log PHI.** No patient names, DOB, SSN, address, phone, email, or raw
   answers in `logger.*`, `print`, stack traces you add, or error messages.
2. **Never hardcode secrets or credentials.** They live in `.env` only. No
   connection strings, API keys, JWT secrets, or passwords in committed code,
   tests, fixtures, comments, or docs.
3. **Never commit `.env` / `.env.local`.** They are gitignored — keep it that way.
4. **EMR is read-only.** Only `SELECT`. Never `INSERT/UPDATE/DELETE/DDL` against
   the EMR database. All EMR SQL is **parameterized** (`text()` + bound params) —
   never string-format / f-string user input into SQL.
5. **Mask at output boundaries.** Anything leaving the backend toward the
   client/logs/audit must be masked if it is sensitive. Values are stored
   unmasked in `form_answers` only because the PDF fill needs them.
6. **Audit the significant events.** Patient search, patient confirmed, session
   created, answer saved, field skipped/undone, PDF generated — each writes an
   `audit_logs` row with **sanitized** metadata.
7. **Keep the disclaimer.** "This assistant helps complete the form but does not
   determine eligibility or provide legal advice." must remain on every page and
   in every generated PDF.

## 1. What counts as sensitive / PHI here

`app/core/security.py` defines the sensitive set used for audit sanitization:

```python
sensitive_keys = {"ssn", "dob", "full_dob", "address", "email", "phone", "password"}
```

Treat as PHI more broadly: patient first/last name, middle initial, full DOB,
SSN, street address, phone, email, Medicaid/insurance IDs, pregnancy status,
income, employment, and the `raw_answer` text the user typed/spoke.

The form schema also flags fields with `"sensitive": true`; those are never
echoed back via TTS and never sent to the semantic LLM validator.

## 2. Masking (use the existing helpers — don't reinvent)

`app/core/security.py`:

- `mask_name(name)` -> `"J****"`
- `mask_dob(dob)` -> `"****-**-DD"`
- `mask_phone(phone)` -> `"***-***-1234"`
- `mask_ssn(ssn)` -> `"***-**-1234"`
- `sanitize_metadata(dict)` -> replaces sensitive keys with `"***"`

Rules:
- **Patient search** returns `MaskedPatient`, never `EMRPatient`, to the client.
- `EMRPatient` (full) is used **server-side only** for prefill; never serialize
  it to an HTTP response.
- When adding a new sensitive field to search/match output, mask it here first.

## 3. Logging safety

- `app/core/logging.py` installs a `SensitiveFilter` that redacts messages
  containing sensitive markers. **Do not rely on it alone** — never put PHI in a
  log message in the first place.
- Log identifiers, not values: `session_id`, `field_key`, `event_type`,
  `confidence`, `source`. Not the answer, not the patient.
- For exceptions, log `exc_info=True` but make sure the exception message you
  raise upstream does not embed PHI.

## 4. Audit logging

- Use `app/core/audit.py` (`log_event(...)`) for the significant events listed in
  the golden rules. Pass metadata **through `sanitize_metadata`** (the writer
  does this) — never store raw values.
- `audit_logs.patient_external_id_masked` stores a masked hint, not the real ID
  where it would be identifying.

## 5. EMR access (`app/emr/`)

- All real queries live in `talbot_adapter.py` and use SQLAlchemy `text()` with
  **named bind parameters** only. Example pattern:
  ```python
  query = text('SELECT ... FROM "Patient" WHERE LOWER("FirstName") LIKE LOWER(:fn)')
  conn.execute(query, {"fn": f"{first_name}%"})
  ```
- Never interpolate user input into the SQL string. Never build dynamic column
  names from user input.
- Keep the soft-delete filter (`"IsDeleted" = false`) and any tenant scoping.
- The adapter swallows EMR errors and degrades to empty/None so the app keeps
  working — preserve that graceful-degradation behavior, but log the failure
  (without PHI) so it is diagnosable.

## 6. Admin auth (`app/admin/`)

- JWT (HS256) signed with `ADMIN_JWT_SECRET`. Tokens carry a username + expiry.
- ⚠️ **Defaults are insecure for production**: `ADMIN_PASSWORD="admin1234"`,
  `ADMIN_JWT_SECRET="change-me-in-production"`. These MUST be overridden by env
  in any non-local environment. Do not "fix" by hardcoding a new value — require
  the env var (see backlog item).
- The dashboard endpoint must keep verifying the Bearer token. Dashboard
  responses must not leak unmasked PHI beyond what an authenticated admin needs.

## 7. CORS

- `app/main.py` allows `localhost:3000/3001` + a `localhost:\d+` regex with
  credentials. This is dev-appropriate. **Before any real deployment**, lock
  `allow_origins` to the real frontend origin(s) and remove the wildcard regex.

## 8. PDF output

- Generated PDFs contain full PHI. They are written to `PDF_OUTPUT_DIR`
  (gitignored) and downloaded over the session API. Do not expose the directory
  for listing; serve by session-scoped endpoint only.
- The disclaimer must appear in both AcroForm and fallback-summary output.

## 9. Pre-flight checklist for ANY change

Before you finish a task, confirm:

- [ ] No PHI in logs, errors, comments, or test fixtures (use fake data).
- [ ] No secrets/connection strings/keys committed; `.env*` untouched in git.
- [ ] EMR SQL still parameterized and read-only.
- [ ] New outputs that include patient data are masked or server-side-only.
- [ ] New significant actions write a sanitized audit entry.
- [ ] Disclaimer preserved where applicable.
- [ ] CORS / auth not loosened.

If a task *requires* relaxing any of these (e.g. a new third-party integration),
say so explicitly and get confirmation — do not relax silently.
