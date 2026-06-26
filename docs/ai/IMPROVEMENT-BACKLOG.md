# Improvement backlog (found during the deep review)

Prioritized, agent-actionable. Each item: what, why, where, rough size.

> **Platform build status (Phases A–H).** Several items are now addressed:
> **I-3** admin defaults fail closed off-dev (`app/admin/router.py`); **I-4** CORS
> locked off-dev via `CORS_ALLOWED_ORIGINS` (`app/main.py`); **I-5** Alembic wired
> (`backend/alembic/`); **I-6** docs standardized on port 5499; **I-17** CI added
> (`.github/workflows/ci.yml`, pytest on 3.11 + build/lint + secret-scan); a frontend
> ESLint config now exists; and the patient-search **PHI masking** gap (found during
> the build) is fixed at the EMR-adapter boundary (`app/emr/masking.py`). Remaining
> items below still stand. Don't action a SECURITY item against a real environment
> without confirming it's wanted there.

## P0 — correctness / security (do before any real deployment)

- **I-1 · Validate / fix `OPENAI_MODEL`.** `config.py` defaults to
  `"gpt-5.4-mini"`. Confirm that's a real, available model for the account; if
  not, set a valid one. Add a startup log of the active model. *Where:*
  `app/core/config.py`, `app/ai/llm.py`. *Size:* XS.
- **I-2 · Reconcile the README vs code on the AI provider.** README documents
  Claude/`claude-opus-4-8`; code uses OpenAI only. Update the README's "Adding
  Real AI" section to match `app/ai/llm.py`. *Size:* XS.
- **I-3 · Remove insecure auth defaults.** `ADMIN_PASSWORD="admin1234"` and
  `ADMIN_JWT_SECRET="change-me-in-production"` must not be usable in prod.
  Require them via env (fail fast if unset when `APP_ENV != development`). *Where:*
  `app/core/config.py`, `app/admin/router.py`. *Size:* S.
- **I-4 · Lock CORS for non-dev.** Replace the `localhost:\d+` regex + wildcard
  with explicit origins driven by config when `APP_ENV != development`. *Where:*
  `app/main.py`. *Size:* S.

## P1 — robustness / maintainability

- **I-5 · Introduce Alembic migrations.** `alembic` is already a dependency but
  there are no migrations; schema is `create_all` at startup, which can't alter
  existing tables. Add `alembic/`, an initial migration, and a "make migrate"
  task. *Size:* M.
- **I-6 · Fix port drift in docs.** README says app DB `5433`; compose + `.env.example`
  use `5499`. Standardize on `5499` and update the README. *Size:* XS.
- **I-7 · Single-transaction ZIP auto-fill.** The ZIP -> city/state/county
  auto-fill can commit separately from the triggering answer; wrap them so a
  partial failure can't persist half the state. *Where:* `app/sessions/service.py`,
  `app/services/zipcode.py`. *Size:* S.
- **I-8 · Narrow EMR exception handling.** `talbot_adapter.py` catches broad
  `Exception` and returns empty; keep graceful degradation but log the failure
  class (no PHI) so EMR issues are diagnosable. *Size:* S.
- **I-9 · Align mock vs real search semantics.** Mock uses prefix/`startswith`;
  Talbot uses `LIKE`. Make them behave the same (or document the difference in
  the adapter). *Size:* S.

## P2 — quality / coverage

- **I-10 · Backend test gaps.** Add tests for admin auth, audit-log writing,
  STT/TTS routers, and a monkeypatched LLM path. Consider a Postgres test
  profile (testcontainers). *Size:* M.
- **I-11 · Frontend tests.** No runner today. Add Playwright for the full flow +
  RTL for components. *Size:* M.
- **I-12 · Accessibility pass.** `aria-label`s on icon buttons, non-color state
  cues, responsive breakpoints for the 3-column assistant layout. *Size:* M.
- **I-13 · Admin token storage.** Token in `localStorage` is XSS-exposed;
  evaluate HTTP-only cookie + CSRF protection. *Size:* M.
- **I-14 · Long-conversation performance.** Virtualize the assistant chat list
  and memoize the review/fields panel for very long sessions. *Size:* S–M.

## P3 — nice to have

- **I-15 · Structured logging** with correlation IDs (session-scoped) for easier
  multi-step debugging.
- **I-16 · Rate-limit** the STT/TTS endpoints to protect provider quotas.
- **I-17 · CI** (GitHub Actions): backend `pytest`, frontend `build` + `lint`,
  and a secret-scan, on PRs to `master`.

> When you pick one up, follow the matching recipe in [WORKFLOWS.md](./WORKFLOWS.md)
> and the rules in [SECURITY-AND-PHI.md](./SECURITY-AND-PHI.md).
