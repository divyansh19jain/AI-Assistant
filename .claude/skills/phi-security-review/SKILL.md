---
name: phi-security-review
description: Run the non-negotiable PHI / secrets / SQL-safety / auth review before finishing any change that touches patient data, the EMR adapter, auth, logging, CORS, audit, masking, or PDF output. Use proactively at the end of such changes. Produces a checklist verdict with file:line evidence.
---

# PHI / security review (HIPAA-relevant — non-negotiable)

This app handles **PHI** (names, DOB, SSN, address, contact info, Medicaid data).
Authority: `docs/ai/SECURITY-AND-PHI.md`. Review the change (default scope:
`git diff` + staged) adversarially and cite `file:line` for every finding. For a
deep pass, hand off to the `security-phi-reviewer` agent.

## The seven checks

1. **No PHI in logs/errors/comments/fixtures.** Grep the diff for `logger.`,
   `print(`, `detail=`, f-strings, and test data. Patient name / DOB / SSN /
   address / phone / email / `raw_answer` must never appear. Only identifiers
   (`session_id`, `field_key`, `event_type`, `source`, `confidence`) are allowed.
   The `SensitiveFilter` is a backstop, not a license to log PHI.
2. **No secrets.** No hardcoded connection strings, API keys, JWT secrets,
   passwords. `.env*` untouched in git and still gitignored. No new insecure
   default (`ADMIN_PASSWORD`, `ADMIN_JWT_SECRET` must come from env).
3. **EMR read-only + parameterized.** Every query is `text()` with named bind
   params, `SELECT` only (no `INSERT/UPDATE/DELETE/DDL`), no user input
   string-built into SQL, soft-delete filter (`"IsDeleted" = false`) intact,
   graceful degradation preserved.
4. **Mask at output.** New patient data leaving the backend is masked
   (`app/core/security.py`) or strictly server-side. `EMRPatient` (full) is never
   serialized to an HTTP response; new sensitive fields are masked before reaching
   `MaskedPatient`/search output.
5. **Audit significant actions.** New significant events (search, confirm, session
   create, answer save, skip/back, PDF generate) write an `audit_logs` row with
   metadata through `sanitize_metadata`.
6. **Respect `sensitive` fields.** Schema fields flagged `"sensitive": true` are
   never echoed via TTS and never sent to the LLM. Confirm the guard still holds.
7. **Auth / CORS / disclaimer.** Bearer verification intact on admin endpoints;
   CORS not widened beyond dev; the disclaimer and MOCK-mode banner preserved.

## Useful greps (over the diff, not the whole tree)
- PHI in logs: search changed files for `logger\.(info|debug|warning|error).*f"` and
  inspect each for embedded values.
- Secrets: `password|secret|api_key|connection string|postgres://|sk-`.
- Raw SQL risk: `text(` with `%`/`+`/f-string interpolation, or `.format(` near SQL.

## Output
A table — **Finding · file:line · Severity (Blocking/High/Med/Low) · Fix** — then a
one-line verdict: **PASS** or **CHANGES REQUIRED**. Any real PHI or secret leak is
Blocking. Default to flagging when uncertain: a false positive costs a second look;
a false negative is a HIPAA incident. If the change *requires* relaxing a rule
(e.g. a new third-party integration), say so explicitly and get confirmation —
never relax silently.
