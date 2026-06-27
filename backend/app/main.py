import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.base import SessionLocal
from app.db.session import create_tables
from app.forms import cache as form_cache
from app.forms import prompts as form_prompts
from app.forms.seed import seed_from_packs
from app.patients.router import router as patients_router
from app.sessions.router import router as sessions_router
from app.forms.router import router as forms_router
from app.workflows.router import router as workflow_router
from app.ai.tts_router import router as tts_router
from app.ai.stt_router import router as stt_router
from app.admin.router import router as admin_router
from app.admin.forms_router import router as admin_forms_router
from app.admin.kb_router import router as admin_kb_router
from app.admin.skills_router import router as admin_skills_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    create_tables()
    # Bring the DB-authoritative form catalog up to date, then warm the schema cache.
    # Both steps are best-effort (they swallow + log their own failures) so a DB hiccup
    # can never block startup — the form engine falls back to the bundled filesystem
    # packs (see app/forms/cache.py + service.load_form_schema).
    db = SessionLocal()
    try:
        seed_from_packs(db)        # import bundled packs not yet in the DB
        loaded = form_cache.refresh_all(db)  # load schemas DB -> in-memory cache
        form_prompts.refresh_all(db)         # load per-form prompt packs + voice config
        logger.info("Form schema cache warmed with %d form(s).", loaded)
    finally:
        db.close()
    yield


app = FastAPI(
    title="AI-Assistant API",
    description="EMR-assisted AI voice form completion system",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: permissive localhost in development; locked to explicit origins off dev.
_settings = get_settings()
if _settings.APP_ENV == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001"],
        allow_origin_regex=r"http://localhost:\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    _origins = [o.strip() for o in _settings.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(patients_router)
app.include_router(sessions_router)
app.include_router(forms_router)
app.include_router(workflow_router)
app.include_router(tts_router)
app.include_router(stt_router)
app.include_router(admin_router)
app.include_router(admin_forms_router)
app.include_router(admin_kb_router)
app.include_router(admin_skills_router)


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok", "service": "AI-Assistant API"}


@app.get("/health/ai")
def ai_health_check() -> dict:
    """Expose AI/voice readiness without returning secrets or raw prompt text."""
    settings = get_settings()
    return {
        "status": "ok",
        "openai_configured": bool(settings.OPENAI_API_KEY),
        "elevenlabs_configured": bool(settings.ELEVENLABS_API_KEY),
        "llm": {
            "provider": settings.LLM_PROVIDER,
            "model": settings.OPENAI_MODEL,
        },
        "stt": {
            "provider": "openai",
            "configured": bool(settings.OPENAI_API_KEY),
            "model": settings.OPENAI_STT_MODEL,
        },
        "tts": {
            "provider_order": ["elevenlabs", "openai"] if settings.ELEVENLABS_API_KEY else ["openai"],
            "openai_configured": bool(settings.OPENAI_API_KEY),
            "openai_model": settings.OPENAI_TTS_MODEL,
            "openai_voice": settings.OPENAI_TTS_VOICE,
            "elevenlabs_configured": bool(settings.ELEVENLABS_API_KEY),
            "elevenlabs_voice_configured": bool(settings.ELEVENLABS_VOICE_ID),
        },
    }
