"""
Speech-to-text service interface.

Current implementation: mock/passthrough (returns input string unchanged).
Architecture is ready to plug in Deepgram, OpenAI Whisper, or another STT provider.

TODO: Implement real STT by replacing MockSTTService with DeepgramSTTService or WhisperSTTService.
"""

from abc import ABC, abstractmethod


class BaseSTTService(ABC):
    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, language: str = "en-US") -> str:
        """Convert audio bytes to a text transcript."""
        ...


class MockSTTService(BaseSTTService):
    """Passthrough mock — returns the raw_text passed directly (simulates typed input)."""

    async def transcribe(self, audio_bytes: bytes, language: str = "en-US") -> str:
        # In mock mode, the frontend sends typed text over the voice channel
        return audio_bytes.decode("utf-8", errors="replace")


# TODO: Implement DeepgramSTTService:
# class DeepgramSTTService(BaseSTTService):
#     def __init__(self):
#         from deepgram import DeepgramClient
#         from app.core.config import get_settings
#         self._client = DeepgramClient(get_settings().DEEPGRAM_API_KEY)
#
#     async def transcribe(self, audio_bytes: bytes, language: str = "en-US") -> str:
#         response = await self._client.listen.prerecorded.v("1").transcribe_file(
#             {"buffer": audio_bytes, "mimetype": "audio/webm"},
#             {"model": "nova-2", "language": language},
#         )
#         return response.results.channels[0].alternatives[0].transcript


def get_stt_service() -> BaseSTTService:
    from app.core.config import get_settings
    settings = get_settings()
    if settings.DEEPGRAM_API_KEY:
        # TODO: return DeepgramSTTService()
        pass
    return MockSTTService()
