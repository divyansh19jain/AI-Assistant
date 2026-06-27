import pytest


def test_settings_audio_defaults_are_current_and_configurable(monkeypatch):
    from app.core.config import Settings

    for env_name in (
        "OPENAI_STT_MODEL",
        "OPENAI_TTS_MODEL",
        "OPENAI_TTS_VOICE",
        "OPENAI_TTS_INSTRUCTIONS",
    ):
        monkeypatch.delenv(env_name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.OPENAI_STT_MODEL == "gpt-4o-transcribe"
    assert settings.OPENAI_TTS_MODEL == "gpt-4o-mini-tts"
    assert settings.OPENAI_TTS_VOICE == "marin"
    assert "plain-language" in settings.OPENAI_TTS_INSTRUCTIONS


def test_ai_health_check_masks_secret_values(client):
    response = client.get("/health/ai")

    assert response.status_code == 200
    data = response.json()
    assert data["openai_configured"] in {True, False}
    assert data["elevenlabs_configured"] in {True, False}
    assert isinstance(data["stt"]["model"], str)
    assert isinstance(data["tts"]["openai_model"], str)
    assert "OPENAI_API_KEY" not in data
    assert "ELEVENLABS_API_KEY" not in data


@pytest.mark.asyncio
async def test_openai_tts_uses_configured_model_voice_and_instructions(monkeypatch):
    from app.ai import text_to_speech

    captured_payload = {}

    class FakeSpeechClient:
        async def create(self, **payload):
            captured_payload.update(payload)
            return type("FakeSpeechResponse", (), {"content": b"mp3-bytes"})()

    class FakeOpenAIClient:
        def __init__(self, api_key: str):
            self.api_key = api_key
            self.audio = type("FakeAudioClient", (), {"speech": FakeSpeechClient()})()

    monkeypatch.setattr(text_to_speech, "AsyncOpenAI", FakeOpenAIClient)

    service = text_to_speech.OpenAITTSService(
        api_key="test-key",
        model="gpt-4o-mini-tts",
        voice="marin",
        instructions="Use plain language.",
    )

    audio = await service.synthesize("What is your full legal name?")

    assert audio == b"mp3-bytes"
    assert captured_payload == {
        "model": "gpt-4o-mini-tts",
        "voice": "marin",
        "input": "What is your full legal name?",
        "response_format": "mp3",
        "instructions": "Use plain language.",
    }


@pytest.mark.asyncio
async def test_openai_tts_omits_instructions_for_legacy_tts_models(monkeypatch):
    from app.ai import text_to_speech

    captured_payload = {}

    class FakeSpeechClient:
        async def create(self, **payload):
            captured_payload.update(payload)
            return type("FakeSpeechResponse", (), {"content": b"mp3-bytes"})()

    class FakeOpenAIClient:
        def __init__(self, api_key: str):
            self.api_key = api_key
            self.audio = type("FakeAudioClient", (), {"speech": FakeSpeechClient()})()

    monkeypatch.setattr(text_to_speech, "AsyncOpenAI", FakeOpenAIClient)

    service = text_to_speech.OpenAITTSService(
        api_key="test-key",
        model="tts-1-hd",
        voice="alloy",
        instructions="Use plain language.",
    )

    await service.synthesize("Hello.")

    assert "instructions" not in captured_payload
