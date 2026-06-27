from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # The documented dev command starts Uvicorn from ``backend/`` while Docker
    # and root-level scripts commonly keep secrets in the repo-root ``.env``.
    # Load both locations so local AI/voice keys are actually seen by FastAPI
    # without copying secrets into tracked files.
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    APP_ENV: str = "development"
    APP_DATABASE_URL: str = "postgresql+psycopg://ai_assistant:ai_assistant@localhost:5433/ai_assistant"
    EMR_DATABASE_URL: str = ""
    USE_MOCK_EMR: bool = True

    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    DEEPGRAM_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = "ZSNL4hPqCnqoMPaI4jGX"

    # AI provider for the conversational assistant. Currently "openai".
    LLM_PROVIDER: str = "openai"
    # OpenAI chat model used for extraction, rephrasing, and help answers.
    # Kept in config (not hardcoded) because model lineups change frequently.
    OPENAI_MODEL: str = "gpt-5.4-mini"
    # Temperature for the assistant. 0 = deterministic extraction.
    OPENAI_TEMPERATURE: float = 0.0
    # Audio models are configurable because voice quality and latency improve
    # over time. These defaults use the current OpenAI audio endpoints while
    # preserving the existing batch STT/TTS pipeline.
    OPENAI_STT_MODEL: str = "gpt-4o-transcribe"
    OPENAI_TTS_MODEL: str = "gpt-4o-mini-tts"
    OPENAI_TTS_VOICE: str = "marin"
    OPENAI_TTS_INSTRUCTIONS: str = (
        "Speak like a calm Ohio Medicaid application helper. Use a warm, patient, "
        "plain-language tone for someone who may not understand government forms."
    )

    PDF_OUTPUT_DIR: str = "app/pdf/generated_pdfs"

    # Web-submission. Default driver is a safe DRY-RUN mock (no network egress).
    # Set WEB_SUBMIT_DRIVER=browserless + BROWSERLESS_URL to enable real portal submission.
    WEB_SUBMIT_DRIVER: str = "mock"
    BROWSERLESS_URL: str = ""

    ZIPCODE_API_KEY: str = ""

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin1234"
    ADMIN_JWT_SECRET: str = "change-me-in-production"
    ADMIN_JWT_EXPIRE_MINUTES: int = 480

    # Comma-separated allowed CORS origins used when APP_ENV != "development".
    # In development the permissive localhost rules apply; off dev, only these origins.
    CORS_ALLOWED_ORIGINS: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
