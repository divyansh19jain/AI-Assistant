---
description: Run the PHI / secrets / SQL-safety review on the current diff.
---

Run a **PHI / security audit** on the current changes. This is a healthcare app
handling PHI — be adversarial. For anything non-trivial, delegate to the
`security-phi-reviewer` agent; otherwise review the diff directly against
[docs/ai/SECURITY-AND-PHI.md](../../docs/ai/SECURITY-AND-PHI.md).

Scope: `git diff` (and staged) on the current branch.

Check, with file/line evidence for every finding:

1. **PHI in logs/errors/comments/fixtures** — any patient name, DOB, SSN, address,
   phone, email, or `raw_answer` reaching `logger.*`, `print`, exception messages,
   comments, or test data. Only identifiers (`session_id`, `field_key`,
   `event_type`) are allowed.
2. **Secrets** — hardcoded connection strings, API keys, JWT secrets, passwords.
   Confirm `.env*` is untouched in git and still gitignored.
3. **EMR SQL** — every query parameterized (`text()` + named binds), read-only
   (no `INSERT/UPDATE/DELETE/DDL`), no user input string-built into SQL,
   soft-delete filter intact.
4. **Masking** — new patient data leaving the backend is masked
   (`app/core/security.py`) or server-side-only; `EMRPatient` never serialized to
   an HTTP response.
5. **Audit** — new significant actions write a sanitized `audit_logs` entry.
6. **`sensitive` fields** — not echoed via TTS, not sent to the LLM.
7. **Auth / CORS** — `ADMIN_PASSWORD`/`ADMIN_JWT_SECRET` not hardcoded; CORS not
   widened; disclaimer + MOCK banner preserved.

Output: a table of **issue · file:line · severity · fix**. End with a clear
verdict (PASS / CHANGES REQUIRED). If a finding is a real PHI/secret leak, treat
it as blocking.
