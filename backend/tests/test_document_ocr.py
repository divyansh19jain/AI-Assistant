import json
from types import SimpleNamespace


def test_document_ocr_disabled_returns_503(client):
    sid = client.post(
        "/api/session/create", json={"form_id": "ODM_07216", "manual_mode": True}
    ).json()["session_id"]
    resp = client.post(
        f"/api/session/{sid}/extract-document",
        files={"file": ("stub.jpg", b"\xff\xd8\xff fake jpeg bytes", "image/jpeg")},
    )
    # Off by default (PHI egress) — never silently accepts an upload.
    assert resp.status_code == 503


def test_document_ocr_extracts_and_validates_suggestions(monkeypatch):
    from app.core.config import get_settings
    from app.forms.service import load_form_schema
    from app.ai import document_extract

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DOCUMENT_OCR_ENABLED", "true")
    get_settings.cache_clear()

    payload = json.dumps({"extractions": [
        {"field_key": "person1.first_name", "value": "Tony", "confidence": 0.95},
        {"field_key": "person1.dob", "value": "01/15/1985", "confidence": 0.9},
        {"field_key": "person1.ssn", "value": "12", "confidence": 0.4},       # invalid SSN -> dropped
        {"field_key": "not.a.real.field", "value": "x", "confidence": 0.9},   # unknown -> dropped
    ]})

    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    try:
        schema = load_form_schema("ODM_07216")
        result = document_extract.extract_fields_from_image(b"fake-image-bytes", "image/jpeg", schema)
    finally:
        get_settings.cache_clear()

    assert result["ok"] is True
    by_key = {s["field_key"]: s for s in result["suggestions"]}
    assert by_key["person1.first_name"]["value"] == "Tony"
    assert by_key["person1.dob"]["value"] == "1985-01-15"   # validated + normalized
    assert "person1.ssn" not in by_key                       # invalid -> never offered
    assert "not.a.real.field" not in by_key                  # unknown -> dropped


def test_document_ocr_rejects_oversized_image(monkeypatch):
    from app.core.config import get_settings
    from app.ai import document_extract

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DOCUMENT_OCR_ENABLED", "true")
    get_settings.cache_clear()
    try:
        huge = b"x" * (9 * 1024 * 1024)
        result = document_extract.extract_fields_from_image(huge, "image/jpeg", {"sections": []})
    finally:
        get_settings.cache_clear()
    assert result == {"ok": False, "error": "invalid_image"}
