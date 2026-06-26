# Workflows / recipes (the common enhancement tasks)

Step-by-step playbooks for the changes you'll actually be asked to make.
Each ends with the same gate: tests/build green + PHI checklist.

---

## A. Add or change a form field (ODM 07216)

The form is **data-driven** by `backend/app/forms/schemas/odm_07216.json`. Most
field changes are JSON edits, not new code.

1. **Edit the schema** `app/forms/schemas/odm_07216.json`: add the field with its
   `key` (dot-notation), `label`, `type`, `section`, `question_text`,
   `validation`/rule, `required`, any `depends_on` (skip-logic), and
   `sensitive: true` if it's PHI that must never be echoed/logged.
2. **Prefill** (if the value can come from the EMR): map it in
   `app/forms/mapper.py` from the `EMRPatient` field. If the EMR column is new,
   add it to `EMRPatient`/the adapter SELECT (see recipe B).
3. **Validation**: if it needs a new value type/normalizer, extend
   `app/forms/validation.py`. Reuse existing normalizers (boolean/date/phone/SSN)
   where possible.
4. **Missing-field logic**: dependencies are honored by
   `app/forms/missing_fields.py` from the schema's `depends_on` — usually no code
   change, but verify the field appears/skips correctly.
5. **Question phrasing**: `app/forms/questions.py` builds the prompt from the
   schema; the optional LLM rewriter improves it. Set good `question_text`.
6. **PDF mapping**: add the `field_key -> widget` entry in
   `app/pdf/mappings/odm_07216_mapping.json` (use `app/pdf/inspect_fields.py` to
   discover AcroForm widget names). Handle date format (ISO -> MM/DD/YYYY) and
   radio/checkbox on-states as the existing entries do.
7. **Tests**: add to `test_form_logic.py` (prefill + validation + dependency
   branch) and, if it affects the PDF, `test_session_api.py`.
8. **Gate**: `pytest tests/ -v` + PHI checklist (sensitive flag set? not logged?).

---

## B. Map a new EMR column / wire the real EMR

1. **Discover** real schema: `python -m app.emr.introspect` (read-only; prints no
   patient values). Note the real table/column names.
2. **Adapter**: update `app/emr/talbot_adapter.py` — extend the parameterized
   `text()` SELECT and map columns into `EMRPatient`. Keep:
   - **named bind params only** (no string interpolation),
   - the soft-delete filter (`"IsDeleted" = false`),
   - graceful degradation (log without PHI, return `None`/`[]` on error).
3. **Schema model**: add the field to `app/emr/schemas.py` (`EMRPatient`, and
   `MaskedPatient` only if it should appear in masked search output — mask it in
   `app/core/security.py` first).
4. **Mock parity**: add the field to `MockEMRAdapter` sample data so mock mode
   still mirrors real mode.
5. **Tests**: extend `test_patient_search.py` (masking + search) and the prefill
   test in `test_form_logic.py`.
6. **Gate**: tests green; confirm EMR stays read-only and unmasked `EMRPatient`
   never reaches an HTTP response.

---

## C. Add a backend endpoint

1. Pick/extend the feature package (`sessions`, `patients`, `admin`, or a new
   one). Create `router.py` + `service.py` + `schemas.py` if new.
2. `router.py`: `APIRouter(prefix="/api/<thing>")`, thin handler,
   `db: Session = Depends(get_db)`, `response_model=<Schema>`. Include the router
   in `app/main.py`.
3. `service.py`: business logic + DB. `schemas.py`: Pydantic v2 request/response.
4. Audit the action if it's significant (`app/core/audit.py`, sanitized
   metadata).
5. Frontend: add a method to `frontend/lib/api.ts` + a type in `lib/types.ts`.
6. Tests + PHI checklist.

---

## D. Add / edit a frontend component or page

1. Types first in `lib/types.ts`; data access only via `lib/api.ts`.
2. Client component (`"use client"`) if it has state/voice/browser APIs.
3. Tailwind utilities + the shared classes in `globals.css`; reuse the
   `ai-*`/`surface-*` palette. No new UI library.
4. Add `aria-label`s to icon buttons; don't regress the disclaimer or the
   MOCK-mode banner.
5. Gate: `npm run build` (typecheck) + `npm run lint`.

---

## E. Wire a real AI provider / model

See [AI-LLM-INTEGRATION.md](./AI-LLM-INTEGRATION.md). Touch **only**
`app/ai/llm.py` + `Settings`. Keep every helper's rule-based fallback intact and
confirm the app still runs with the key removed.

---

## F. Enable real voice (STT/TTS)

1. Set the provider key(s) in `.env` (`DEEPGRAM_API_KEY` / `ELEVENLABS_API_KEY`
   + `ELEVENLABS_VOICE_ID`).
2. Implement/return the real service from `speech_to_text.py` / `text_to_speech.py`
   (interfaces already exist).
3. The `/api/stt` + `/api/tts` routers and `frontend/lib/useVoice.ts` already
   call them; verify the sensitive-field voice guard still holds.

---

## G. Database schema change

There are **no Alembic migrations yet** (`create_all` runs at startup and will
**not** alter existing columns). For any model change beyond a fresh DB:

1. Change the model in `app/db/models.py`.
2. Until Alembic is set up (backlog item I-2), document the manual
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` needed for existing databases and
   include it in the PR. Do not assume `create_all` migrates it.
