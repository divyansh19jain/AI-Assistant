import logging
from fastapi import APIRouter, File, UploadFile, Form
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI

from app.core.config import get_settings

router = APIRouter(prefix="/api/stt", tags=["stt"])
logger = logging.getLogger(__name__)


@router.post("")
async def transcribe(
    audio: UploadFile = File(...),
    prompt: str = Form(default=""),
) -> JSONResponse:
    """
    Transcribe audio using OpenAI Whisper.
    `prompt` biases recognition toward expected vocabulary (field label, common values,
    command words like 'skip', 'yes', 'no').
    """
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        return JSONResponse(status_code=503, content={"error": "STT not configured"})

    audio_bytes = await audio.read()
    if not audio_bytes:
        return JSONResponse(status_code=400, content={"error": "Empty audio"})

    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        # Pass the audio as a named file so Whisper knows the format
        # The prompt primes Whisper's vocabulary — it sees these tokens first so it
        # strongly prefers them over phonetically similar alternatives.
        full_prompt = (
            "Ohio Medicaid form. " + prompt
            if prompt
            else "Ohio Medicaid form. Patient name, address, date of birth, skip, yes, no."
        )
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=("audio.webm", audio_bytes, audio.content_type or "audio/webm"),
            language="en",
            prompt=full_prompt,
        )
        transcript = response.text.strip()
        logger.info("STT transcript: %r (prompt hint: %r)", transcript[:80], prompt[:60])
        return JSONResponse(content={"transcript": transcript})
    except Exception:
        logger.warning("Whisper transcription failed", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Transcription failed"})
