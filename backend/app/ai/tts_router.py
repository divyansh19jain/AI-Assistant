import asyncio
import hashlib
import logging
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter(prefix="/api/tts", tags=["tts"])
logger = logging.getLogger(__name__)

# In-memory cache: text_hash -> audio bytes. Capped at 200 entries (LRU-style eviction).
_tts_cache: dict[str, bytes] = {}
_TTS_CACHE_MAX = 200
# Dedup in-flight requests: same text arriving concurrently shares one API call
_tts_inflight: dict[str, asyncio.Future] = {}


class TTSRequest(BaseModel):
    text: str


@router.post("")
async def synthesize(request: TTSRequest) -> Response:
    text = request.text.strip()
    if not text:
        return Response(content=b"", media_type="audio/mpeg")

    key = hashlib.md5(text.encode()).hexdigest()

    if key in _tts_cache:
        return Response(content=_tts_cache[key], media_type="audio/mpeg")

    # Dedup concurrent identical requests
    loop = asyncio.get_event_loop()
    if key in _tts_inflight:
        try:
            audio = await asyncio.shield(_tts_inflight[key])
            return Response(content=audio, media_type="audio/mpeg")
        except Exception:
            return Response(status_code=503, content=b"")

    future: asyncio.Future = loop.create_future()
    _tts_inflight[key] = future

    from app.ai.text_to_speech import get_tts_service
    svc = get_tts_service()
    try:
        audio = await svc.synthesize(text)
        if len(_tts_cache) >= _TTS_CACHE_MAX:
            oldest = next(iter(_tts_cache))
            del _tts_cache[oldest]
        _tts_cache[key] = audio
        future.set_result(audio)
        return Response(content=audio, media_type="audio/mpeg")
    except Exception:
        logger.warning("TTS synthesis failed", exc_info=True)
        if not future.done():
            future.set_exception(RuntimeError("TTS failed"))
        return Response(status_code=503, content=b"")
    finally:
        _tts_inflight.pop(key, None)
