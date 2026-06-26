# Testing guide

## Backend (pytest) — the only test suite today

- Location: `backend/tests/`.
- `conftest.py` provides:
  - an **in-memory SQLite** database created/dropped per test,
  - a `db` session fixture,
  - a `client` = FastAPI `TestClient` with `get_db` **overridden** to the test
    session.
- Suites:
  - `test_patient_search.py` — masking helpers + `MockEMRAdapter` + the search
    endpoint (consent validation, mock-mode flag).
  - `test_form_logic.py` — EMR->form prefill, dependency-aware missing fields,
    per-field validation/normalization (boolean/date/phone/SSN/pattern).
  - `test_session_api.py` — session create (manual + prefilled), answer
    save/validation, review, PDF generation (fallback path).

### Running

```bash
cd backend
.\.venv\Scripts\Activate.ps1     # Windows PowerShell
pytest tests/ -v
pytest tests/test_form_logic.py::test_name -v   # single test
```

### Conventions for new backend tests

- Use the `client` and `db` fixtures; don't hit a real Postgres or the real EMR.
- Use **fake** data only — never real PHI in fixtures (`Test Patient`,
  `Jane Doe`, `1990-01-15` are the established fakes).
- Default to **mock EMR** (`USE_MOCK_EMR=true`) and **no LLM key** so tests are
  deterministic and exercise the rule-based fallback. If you must test the LLM
  path, monkeypatch `app.ai.llm.get_chat_model` / `structured_model` to return a
  fake — never call a real provider in tests.
- Add a test whenever you: add/relax a validation rule, add a form field with
  dependencies, change masking, add an endpoint, or change the prefill mapping.
- Cover the **skip-logic** (dependency) branches — that's where form bugs hide
  (e.g. pregnancy fields skipped when not pregnant).

### Gaps worth filling (backlog)

- No tests for admin auth, audit-log writing, STT/TTS routers, or the LLM path.
- SQLite vs Postgres differences (timezone-aware datetimes, constraints) — a
  Postgres-backed test profile (testcontainers) would harden this.

## Frontend — none yet (backlog)

No test runner is configured. The build (`npm run build`) + `npm run lint` are
the current gates. When adding tests:

- **Playwright** for the landing -> match -> assistant -> review -> PDF flow.
- **React Testing Library** for components in `components/`.
- Keep them offline: mock the `api` client; never call the live backend with PHI.

## The "is it actually working" gate

For any change, the minimum green bar is:

```bash
# backend
cd backend && pytest tests/ -v
# frontend
cd frontend && npm run build && npm run lint
```

Plus a manual smoke through the affected flow with **mock EMR** and **no AI key**
when the change touches the form/session/PDF path.
