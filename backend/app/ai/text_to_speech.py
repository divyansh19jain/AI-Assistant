from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class BaseTTSService(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Convert text to MP3 audio bytes."""
        ...


class ElevenLabsTTSService(BaseTTSService):
    MODEL = "eleven_turbo_v2_5"

    def __init__(self, api_key: str, voice_id: str):
        self._api_key = api_key
        self._voice_id = voice_id

    async def synthesize(self, text: str) -> bytes:
        import httpx
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}"
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": self.MODEL,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 402:
                raise RuntimeError("ElevenLabs quota exceeded or payment required")
            response.raise_for_status()
            return response.content


class OpenAITTSService(BaseTTSService):
    VOICE = "alloy"
    MODEL = "tts-1-hd"

    def __init__(self, api_key: str):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=api_key)

    async def synthesize(self, text: str) -> bytes:
        response = await self._client.audio.speech.create(
            model=self.MODEL,
            voice=self.VOICE,
            input=text,
            response_format="mp3",
        )
        return response.content


class MockTTSService(BaseTTSService):
    async def synthesize(self, text: str) -> bytes:
        return b""


class FallbackTTSService(BaseTTSService):
    """Tries primary service, falls back to secondary on any error."""

    def __init__(self, primary: BaseTTSService, secondary: BaseTTSService):
        self._primary = primary
        self._secondary = secondary

    async def synthesize(self, text: str) -> bytes:
        try:
            return await self._primary.synthesize(text)
        except Exception as e:
            logger.warning("Primary TTS failed (%s), falling back", e)
            return await self._secondary.synthesize(text)


def get_tts_service(form_id: str | None = None) -> BaseTTSService:
    """Build the TTS service, using the form's builder-configured voice if set.

    A per-form ``voice_id`` (from the prompt/voice pack) overrides the global default,
    so each form can speak in its own voice. Falls back to the global default and to
    the rule-based/mock path exactly as before when nothing is configured.
    """
    from app.core.config import get_settings
    from app.forms.prompts import get_voice_config

    settings = get_settings()
    voice_id = get_voice_config(form_id).get("voice_id") or settings.ELEVENLABS_VOICE_ID

    openai_svc = OpenAITTSService(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else MockTTSService()
    if settings.ELEVENLABS_API_KEY:
        eleven_svc = ElevenLabsTTSService(
            api_key=settings.ELEVENLABS_API_KEY,
            voice_id=voice_id,
        )
        return FallbackTTSService(primary=eleven_svc, secondary=openai_svc)
    return openai_svc
