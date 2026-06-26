---
description: Bring the stack up locally (db + backend + frontend) in mock mode.
---

Bring up the AI-Assistant dev stack in the **default safe profile**
(`USE_MOCK_EMR=true`, no `OPENAI_API_KEY` → rule-based fallback). Primary shell is
Windows PowerShell.

Do this:

1. **App DB** (Postgres 15, host port **5499**):
   ```bash
   docker compose up db -d
   ```
2. **Backend** (FastAPI on :8000):
   ```bash
   cd backend
   python -m venv .venv ; .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000
   ```
   Verify: open http://localhost:8000/docs and `GET /health`.
3. **Frontend** (Next.js on :3000):
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
4. **Or the whole stack:** `docker compose up --build` (fe :3000, be :8000, db :5499).

Confirm the **yellow MOCK-mode banner** shows in the UI and the disclaimer is
present. Do **not** set a real EMR connection or `OPENAI_API_KEY` unless the user
explicitly asks. If a port is busy, report it — don't silently change ports.

Reference: [docs/ai/ARCHITECTURE.md](../../docs/ai/ARCHITECTURE.md) §7 (run profiles).
