# Backend conventions (FastAPI / Python 3.11)

> How the existing code is written. Match it. New code should be
> indistinguishable from what's already there.

## Package shape

Every feature is a package with three files:

- `router.py` — `APIRouter(prefix="/api/<thing>", tags=["<thing>"])`, thin
  handlers, `db: Session = Depends(get_db)`, returns Pydantic models.
- `service.py` — business logic; owns DB queries and orchestration; calls
  `emr/`, `forms/`, `ai/`, `pdf/`.
- `schemas.py` — Pydantic v2 request/response models for that feature.

Routers do **not** contain business logic. Services do **not** import FastAPI
request/response objects. Keep that separation.

## Typing & Pydantic

- Full type hints everywhere, Python 3.11 union syntax: `str | None`, not
  `Optional[str]`.
- Pydantic **v2** models. Use `field_validator` for input rules (e.g. consent
  required). Keep response models explicit (`response_model=...` on routes).
- Dataclasses are used for in-process orchestration state (e.g. the assistant
  flow state) — that's fine; don't convert those to Pydantic without reason.

## Settings & config

- All config goes through `app/core/config.py::Settings` (pydantic-settings) and
  is read via `get_settings()` (it is `@lru_cache`d — never re-instantiate
  `Settings()` directly).
- Add a new setting by adding a typed field with a sensible **non-secret**
  default. Secrets default to `""` and are supplied via `.env`.
- Don't read `os.environ` directly in feature code; add a field to `Settings`.

## Database

- **SQLAlchemy 2.0, synchronous.** Models use `Mapped[...]` +
  `mapped_column(...)` (see `app/db/models.py`). No async ORM.
- Get a session via `Depends(get_db)` in routers; pass the `Session` down into
  service functions. Services call `db.query(...)`, `db.add(...)`,
  `db.commit()`, `db.refresh(...)`.
- Timestamps: always timezone-aware UTC via the `utcnow()` helper.
- Schema is created at startup with `create_tables()` (metadata `create_all`).
  There are **no Alembic migrations yet** — if you change a model, note it; a
  real migration story is a backlog item. Don't silently rely on `create_all`
  picking up column changes on an existing DB (it won't).

## Error handling

- Raise `fastapi.HTTPException(status_code=..., detail=...)` for client-facing
  errors in routers/services.
- Domain validation raises the form `ValidationError` from
  `app/forms/validation.py`; let the session flow translate it into a re-ask,
  not a 500.
- EMR/AI integration code **degrades gracefully**: on failure, log (without PHI)
  and return `None`/`[]` so the app keeps working. Preserve this — don't let an
  EMR or LLM outage become a hard error for the user.

## Logging

- `logger = logging.getLogger(__name__)` per module.
- `setup_logging()` (called in `main.py` lifespan) installs the
  `SensitiveFilter`. Log identifiers, never PHI (see SECURITY-AND-PHI.md).
- Use `logger.debug` for expected no-key/fallback paths, `warning`/`error` (with
  `exc_info=True`) for real failures.

## Sync vs async

- Business logic, DB, form logic, PDF: **synchronous**.
- `async def` only where there's real network I/O — the STT/TTS routers and
  their `httpx.AsyncClient` calls. Don't sprinkle `async` elsewhere.

## AI modules

- All LLM access goes through `app/ai/llm.py` (`get_chat_model()`,
  `structured_model(schema)`, `ai_enabled()`). Never construct `ChatOpenAI`
  (or any provider client) anywhere else.
- Every AI feature MUST have a deterministic rule-based fallback that runs when
  the model is `None`. See [AI-LLM-INTEGRATION.md](./AI-LLM-INTEGRATION.md).
- Temperature stays `0.0` for extraction/validation (deterministic).

## Naming

- Private helpers prefixed `_` (`_llm_extract`, `_deserialize`).
- Module-level constants `UPPER_SNAKE` (`_CONFIRM_THRESHOLD`, `_SKIP_PHRASES`).
- Field keys are dot-notation strings (`applicant.first_name`) and come from the
  form schema — don't invent ad-hoc keys.

## Dependencies

- Add a dependency to `backend/requirements.txt` with a `>=` floor matching the
  existing style. Prefer the libraries already present (FastAPI, SQLAlchemy,
  Pydantic, LangChain, PyMuPDF, httpx, pyjwt) before adding new ones.

## Commands

```bash
cd backend
python -m venv .venv && .\.venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000              # run
pytest tests/ -v                                       # test
python -m app.emr.introspect                           # EMR schema discovery (real EMR mode)
```
