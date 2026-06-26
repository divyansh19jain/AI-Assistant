---
description: Run the backend pytest suite (and the frontend build/lint gate).
---

Run the test suite for AI-Assistant.

1. **Backend (the real test suite):**
   ```bash
   cd backend
   .\.venv\Scripts\Activate.ps1
   pytest tests/ -v
   ```
   Tests use an in-memory SQLite DB, mock EMR, and no LLM key — they should be
   fully deterministic and need no Postgres/EMR. A single test:
   `pytest tests/test_form_logic.py::test_name -v`.

2. **Frontend gate** (no test runner yet — build is the typecheck gate):
   ```bash
   cd frontend
   npm run build && npm run lint
   ```

Report pass/fail honestly with the relevant output. If a test fails, show the
failure and diagnose the root cause — do **not** loosen an assertion or skip a
test to get green. If behavior changed and no test covers it, note that a test is
owed (see [docs/ai/TESTING.md](../../docs/ai/TESTING.md)).
