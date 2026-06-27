# AI-Assistant Medicaid Form Platform

Healthcare form-completion platform with EMR prefill, AI-assisted question flow,
voice STT/TTS, review/approval, PDF generation, and optional web-submission
workflows.

The bundled Ohio Medicaid `ODM_07216` form is a seed form. Admins can add new forms
through `/admin/forms` or by adding a form pack under
`backend/app/forms/packs/<FORM_ID>/`.

## Core Flow

```text
Admin publishes a form
  -> patient picks a published form
  -> EMR search/match or manual mode
  -> session created with schema snapshot
  -> assistant gathers applicable fields
  -> user reviews and edits answers
  -> user approves
  -> workflow runs: generate_pdf, optional web_submit
```

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, React 18, TypeScript, Tailwind |
| Backend | FastAPI, SQLAlchemy 2.0, Pydantic v2, Alembic |
| AI / Voice | OpenAI-compatible LangChain helpers, rule fallbacks, STT/TTS routes |
| PDF | PyMuPDF AcroForm fill with generic summary fallback |
| DB | PostgreSQL for app data, read-only PostgreSQL EMR adapter |

## Form Platform

Read `docs/ai/PLATFORM.md` for the full contract. Key points:

- DB `forms.schema_json` is the source of truth after seed/import.
- `form_sessions.schema_json` freezes a schema snapshot for every session.
- Form packs live in `backend/app/forms/packs/<FORM_ID>/`.
- Per-form assets can include schema, prompts, voice config, KB docs, skills,
  PDF mapping, and workflow recipe.
- Supported workflow task types are `generate_pdf` and `web_submit`.
- Web submission is PHI egress and stays dry-run unless explicitly configured.

## Local Setup

```powershell
# Database
docker compose up db -d

# Backend
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

Default local profile:

- `USE_MOCK_EMR=true`
- no live AI key required
- web submission driver defaults to dry-run

## Verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm run build
npm run lint
```

## Important Docs

- `AGENTS.md` - global agent/developer rules.
- `docs/ai/PLATFORM.md` - multi-form architecture and contracts.
- `docs/ai/WORKFLOWS.md` - common implementation playbooks.
- `docs/ai/SECURITY-AND-PHI.md` - PHI/security checklist.
- `.claude/` and `.cursor/` - agent-specific rules and skills.
