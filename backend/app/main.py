import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.logging import setup_logging
from app.db.base import SessionLocal
from app.db.session import create_tables
from app.forms import cache as form_cache
from app.forms.seed import seed_from_packs
from app.patients.router import router as patients_router
from app.sessions.router import router as sessions_router
from app.forms.router import router as forms_router
from app.ai.tts_router import router as tts_router
from app.ai.stt_router import router as stt_router
from app.admin.router import router as admin_router

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001"],
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(patients_router)
app.include_router(sessions_router)
app.include_router(forms_router)
app.include_router(tts_router)
app.include_router(stt_router)
app.include_router(admin_router)


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok", "service": "AI-Assistant API"}
