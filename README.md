# AI-Assistant

EMR-assisted + AI voice-assisted PDF form completion system.

> **NOTE:** This project implements the **PDF-based flow only**.
> No Playwright, browser automation, online portal filling, or final government portal submission is included by design.

---

## Project Overview

Users complete the **ODM 07216 – Ohio Department of Medicaid Application for Health Coverage & Help Paying Costs** form with the help of:

1. **EMR pre-fill** — patient data from the EMR database is mapped to form fields automatically.
2. **AI voice assistant** — missing fields are collected one question at a time (voice UI is architecturally ready; initial implementation uses typed input).
3. **PDF generation** — a filled PDF is generated for review and download.

---

## Flow

```
Landing page
  ↓ User enters First Name, Last Name, DOB + consent
  ↓ Backend searches EMR (or mock)
Patient Match page
  ↓ User confirms matched patient (or continues manually)
  ↓ Session created with EMR-prefilled fields
Assistant page
  ↓ Missing required fields collected one at a time
  ↓ User types (or eventually speaks) answers
  ↓ Answers validated and saved
Review page
  ↓ All fields shown grouped by section with source labels (EMR / User / AI Voice)
  ↓ PDF generated
  ↓ User downloads PDF
```

---

## Tech Stack

| Layer       | Technology                                        |
|-------------|---------------------------------------------------|
| Frontend    | Next.js 14, React, TypeScript, Tailwind CSS       |
| Backend     | Python 3.11, FastAPI, SQLAlchemy, Pydantic, Uvicorn |
| AI / Voice  | LangChain, LangGraph (stubs ready for OpenAI/Deepgram/ElevenLabs) |
| PDF         | PyMuPDF (fitz), pypdf                             |
| App DB      | PostgreSQL 15 (Docker)                            |
| EMR DB      | PostgreSQL (Talbot — read-only)                   |

---

## Setup — Windows PowerShell

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker Desktop (for the app database)
- Git

---

### 1. Clone / open the project

```powershell
cd C:\Development\AI-Assistant
```

---

### 2. Backend setup

```powershell
cd backend

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Copy env file and edit values
Copy-Item .env.example .env
notepad .env
```

Edit `.env`:
- Set `USE_MOCK_EMR=true` for local development without the real EMR.
- Set `APP_DATABASE_URL` to point to your local PostgreSQL (Docker recommended — see below).
- Leave AI keys empty to use mock implementations.

---

### 3. Start the app database (Docker)

From the project root:

```powershell
docker compose up db -d
```

This starts a PostgreSQL 15 instance on port **5433** with:
- User: `ai_assistant`
- Password: `ai_assistant`
- Database: `ai_assistant`

Tables are created automatically when the backend starts.

---

### 4. Run the backend

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs  
Health check: http://localhost:8000/health

---

### 5. Frontend setup

```powershell
cd frontend

# Copy env file
Copy-Item .env.local.example .env.local

# Install dependencies
npm install

# Run dev server
npm run dev
```

Frontend: http://localhost:3000

---

### 6. Run everything with Docker Compose

```powershell
# From project root
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- App DB: localhost:5433

---

## EMR Configuration

### Mock mode (default, no real EMR needed)

In `backend/.env`:
```
USE_MOCK_EMR=true
```

Mock patients available for testing:
- First: `Test`, Last: `Patient`, DOB: `1990-01-15`
- First: `Jane`, Last: `Doe`, DOB: `1985-06-20`

### Real EMR mode (Talbot)

1. Set `USE_MOCK_EMR=false` in `backend/.env`.
2. Set `EMR_DATABASE_URL=postgresql+psycopg://postgres:Surf2day!@10.1.104.71:5432/talbotdev`.
3. Run the EMR introspection script to discover table/column names:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.emr.introspect
```

4. Review the output and update `backend/app/emr/talbot_adapter.py` — look for `# TODO:` comments.
5. The adapter uses parameterized queries only. No credentials are hardcoded.

---

## EMR Introspection

```powershell
cd backend
python -m app.emr.introspect
```

This connects to the EMR database (read-only), lists schemas, tables, and columns that look patient-related, and prints the results. **No actual patient data is printed.**

Use the output to update `talbot_adapter.py` table/column names.

---

## PDF Generation

### How it works

1. **With base PDF** (`backend/app/pdf/ODM07216fillx.pdf` present):
   - Tries to fill AcroForm fields by name.
   - Falls back to coordinate-based text placement if AcroForm fields don't match.

2. **Without base PDF (fallback)**:
   - Generates a clean **Application Data Summary PDF** with all filled fields grouped by section.
   - Clearly labeled as a draft/fallback.

### To enable field-filled PDF output

1. Place the original `ODM07216fillx.pdf` in `backend/app/pdf/`.
2. Run the backend and generate a PDF.
3. If fields don't align, inspect the PDF with a tool like Adobe Acrobat to find exact AcroForm field names or coordinates, and update `backend/app/pdf/mappings/odm_07216_mapping.json`.

---

## Mock Mode Indicators

When `USE_MOCK_EMR=true`:
- The frontend shows a yellow "MOCK MODE" banner.
- The API response includes `"is_mock": true`.
- Patient search results have a "mock" badge.
- The backend logs "EMR mode: MOCK".

---

## Adding Real AI / Voice Keys

### Anthropic / Claude (LLM answer extraction + question rewriting)

1. Set `ANTHROPIC_API_KEY=sk-ant-...` in `backend/.env`.
2. That's it — `answer_extractor.py` and `question_rewriter.py` detect the key
   automatically and call `claude-opus-4-8` with adaptive thinking.
   Without the key both modules fall back to rule-based logic transparently.

### OpenAI (optional — not wired)

OpenAI is no longer used. The Claude implementation covers extraction and rewriting.

### Deepgram (speech-to-text)

1. Set `DEEPGRAM_API_KEY=...` in `backend/.env`.
2. Update `backend/app/ai/speech_to_text.py` — uncomment `DeepgramSTTService` and return it from `get_stt_service()`.
3. Wire the STT service into the session answer endpoint for voice input.

### ElevenLabs (text-to-speech)

1. Set `ELEVENLABS_API_KEY=...` in `backend/.env`.
2. Update `backend/app/ai/text_to_speech.py` — uncomment `ElevenLabsTTSService` and return it from `get_tts_service()`.
3. Wire TTS into the assistant page to speak questions aloud.

### LangGraph (full agent flow)

The `backend/app/ai/langgraph_flow.py` file contains a complete `StateGraph` scaffold.
Uncomment the `build_graph()` function and call it from the session service.

---

## Running Tests

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest tests/ -v
```

Test coverage:
- Patient search request validation
- Mock patient search and masking
- EMR-to-form prefill
- Missing field detection
- Dependency skipping (e.g., pregnancy fields skipped when not pregnant)
- Answer save and validation
- Review output
- PDF generation (fallback mode)

---

## Adding a New EMR Table Mapping

After running `python -m app.emr.introspect`:

1. Open `backend/app/emr/talbot_adapter.py`.
2. Find the `# TODO:` comments in `search_patients()` and `get_patient()`.
3. Replace the placeholder table/column names with the real ones from introspection output.
4. If insurance/employment/income are in separate tables, add JOINs and populate `insurance`, `employment`, `income` in the returned `EMRPatient`.

---

## Project Structure

```
AI-Assistant/
├── backend/
│   ├── app/
│   │   ├── main.py                   # FastAPI app entry point
│   │   ├── core/
│   │   │   ├── config.py             # Settings (pydantic-settings)
│   │   │   ├── security.py           # Masking functions
│   │   │   ├── audit.py              # Audit log writer
│   │   │   └── logging.py            # Sensitive-field log filter
│   │   ├── db/
│   │   │   ├── base.py               # SQLAlchemy engine/session
│   │   │   ├── models.py             # FormSession, FormAnswer, GeneratedPdf, AuditLog
│   │   │   └── session.py            # DB dependency + table creation
│   │   ├── emr/
│   │   │   ├── adapter.py            # Abstract EMR adapter
│   │   │   ├── mock_adapter.py       # Mock data adapter
│   │   │   ├── talbot_adapter.py     # Real Talbot EMR adapter (with TODOs)
│   │   │   ├── factory.py            # Selects mock vs real adapter
│   │   │   ├── introspect.py         # EMR schema discovery script
│   │   │   └── schemas.py            # EMRPatient, MaskedPatient models
│   │   ├── forms/
│   │   │   ├── schemas/
│   │   │   │   └── odm_07216.json    # Full ODM form field schema
│   │   │   ├── service.py            # Schema loader
│   │   │   ├── mapper.py             # EMR → form field prefill
│   │   │   ├── missing_fields.py     # Dependency-aware missing field detection
│   │   │   ├── validation.py         # Per-field value validation
│   │   │   └── questions.py          # Question context builder
│   │   ├── ai/
│   │   │   ├── answer_extractor.py   # Rule-based answer extraction (LLM-ready)
│   │   │   ├── question_rewriter.py  # Question rephrasing (LLM-ready)
│   │   │   ├── speech_to_text.py     # STT interface (Deepgram-ready)
│   │   │   ├── text_to_speech.py     # TTS interface (ElevenLabs-ready)
│   │   │   └── langgraph_flow.py     # LangGraph state machine (stub)
│   │   ├── sessions/
│   │   │   ├── router.py             # Session API endpoints
│   │   │   ├── service.py            # Session business logic
│   │   │   └── schemas.py            # Request/response schemas
│   │   ├── patients/
│   │   │   ├── router.py             # Patient search endpoint
│   │   │   ├── service.py            # Patient search logic
│   │   │   └── schemas.py            # Request/response schemas
│   │   └── pdf/
│   │       ├── pdf_service.py        # PDF generation (AcroForm + fallback)
│   │       ├── mappings/
│   │       │   └── odm_07216_mapping.json
│   │       └── generated_pdfs/       # Output directory (gitignored)
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_patient_search.py
│   │   ├── test_form_logic.py
│   │   └── test_session_api.py
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile
├── frontend/
│   ├── app/
│   │   ├── layout.tsx                # Root layout with header/footer
│   │   ├── globals.css               # Tailwind base styles
│   │   ├── page.tsx                  # / — Landing page
│   │   ├── patient-match/page.tsx    # /patient-match
│   │   ├── assistant/[sessionId]/page.tsx  # /assistant/:id
│   │   └── review/[sessionId]/page.tsx     # /review/:id
│   ├── components/
│   │   ├── ConsentSearchForm.tsx
│   │   ├── PatientMatchCard.tsx
│   │   ├── FormProgress.tsx
│   │   ├── QuestionCard.tsx
│   │   ├── MissingFieldsList.tsx
│   │   ├── PrefilledFieldsSummary.tsx
│   │   ├── ReviewSection.tsx
│   │   └── PdfDownloadCard.tsx
│   ├── lib/
│   │   ├── api.ts                    # API client
│   │   └── types.ts                  # TypeScript types
│   ├── .env.local.example
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
├── .gitignore
└── README.md
```

---

## What Is NOT Implemented

- Playwright / browser automation
- Online portal form filling
- Final government portal submission
- Real-time voice streaming (microphone button is a placeholder)
- Appendix A (job-based health coverage) — flagged but deferred
- Full AcroForm coordinate mapping (PDF field coordinates are placeholder values)
- OpenAI / Deepgram / ElevenLabs integration (stubs only — wire in after adding API keys)
- Multi-person household (only Person 1 is in scope for initial release)

---

## Security Notes

- All credentials are in `.env` only — never hardcoded.
- `.env` and `.env.local` are in `.gitignore`.
- SSN, full DOB, and address are marked as sensitive and never logged.
- Patient search results are masked before returning to the frontend.
- EMR queries use parameterized SQL only.
- Audit log entries are written for: patient search, patient confirmed, session created, answer saved, PDF generated.
- Disclaimer shown on every page and in every generated PDF.

---

## Disclaimer

> This assistant helps complete the form but does not determine eligibility or provide legal advice.
> Please review all answers before submitting or using the generated PDF.
