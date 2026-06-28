import json
from types import SimpleNamespace


def test_agent_tool_only_turn_rejects_early_review_and_asks_next_question(client, db, monkeypatch):
    """A duplicate/correction-style tool-only model turn must not dead-end the UI."""
    from app.ai.agent import run_agent_turn
    from app.core.config import get_settings

    schema = {
        "form_id": "AGENT_STALL",
        "form_title": "Agent Stall",
        "version": "1.0",
        "sections": [
            {
                "section_key": "s",
                "section_title": "Applicant",
                "fields": [
                    {
                        "field_key": "s.name",
                        "label": "Name",
                        "section": "s",
                        "type": "text",
                        "required": True,
                        "question_text": "What is your name?",
                    },
                    {
                        "field_key": "s.middle",
                        "label": "Middle name",
                        "section": "s",
                        "type": "text",
                        "required": False,
                        "question_text": "Do you have a middle name? Say skip if none.",
                    },
                ],
            }
        ],
    }
    token = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/admin/forms", headers=headers, json={"form_id": "AGENT_STALL", "title": "Agent Stall"})
    client.put("/api/admin/forms/AGENT_STALL/schema", headers=headers, json={"schema": schema})
    client.post("/api/admin/forms/AGENT_STALL/publish", headers=headers)
    session_id = client.post(
        "/api/session/create",
        json={"form_id": "AGENT_STALL", "manual_mode": True},
    ).json()["session_id"]

    def call(name: str, arguments: dict, call_id: str):
        return SimpleNamespace(
            id=call_id,
            function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
        )

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                message = SimpleNamespace(
                    content="",
                    tool_calls=[
                        call("save_answers", {"items": [{"field_key": "s.name", "value": "Tony Stark"}]}, "save_1"),
                        call("go_to_review", {}, "review_1"),
                    ],
                )
            else:
                # Real tool-calling models can occasionally end with no spoken text
                # after tool output. The backend must fill in the next prompt.
                message = SimpleNamespace(content="", tool_calls=[])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    get_settings.cache_clear()
    try:
        result = run_agent_turn(db, session_id, "Tony Stark", input_mode="voice")
    finally:
        get_settings.cache_clear()

    assert result is not None
    assert result["done"] is False
    assert result["go_to_review"] is False
    assert result["state"]["next_field_key"] == "s.middle"
    assert result["state"]["missing_count"] == 1
    assert "middle name" in result["assistant_message"].lower()
    assert result["assistant_message"] != "Okay!"

    review = client.get(f"/api/session/{session_id}/review").json()
    assert review["missing_applicable"] == ["s.middle"]


def test_voice_date_capture_requires_readback_confirmation(client, db, monkeypatch):
    """Voice-captured dates are saved but stay blocked until the user confirms them."""
    from app.ai.agent import run_agent_turn
    from app.core.config import get_settings
    from app.db.models import FormAnswer

    schema = {
        "form_id": "AGENT_READBACK",
        "form_title": "Agent Readback",
        "version": "1.0",
        "sections": [
            {
                "section_key": "s",
                "section_title": "Applicant",
                "fields": [
                    {
                        "field_key": "person1.dob",
                        "label": "Date of Birth",
                        "section": "s",
                        "type": "date",
                        "required": True,
                        "sensitive": True,
                        "question_text": "What is your date of birth?",
                        "validation_rule": {"format": "date"},
                    }
                ],
            }
        ],
    }
    token = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/admin/forms", headers=headers, json={"form_id": "AGENT_READBACK", "title": "Agent Readback"})
    client.put("/api/admin/forms/AGENT_READBACK/schema", headers=headers, json={"schema": schema})
    client.post("/api/admin/forms/AGENT_READBACK/publish", headers=headers)
    session_id = client.post(
        "/api/session/create",
        json={"form_id": "AGENT_READBACK", "manual_mode": True},
    ).json()["session_id"]

    class FakeCompletions:
        def create(self, **_kwargs):
            message = SimpleNamespace(content="Thanks, I have that.", tool_calls=[])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    get_settings.cache_clear()
    try:
        result = run_agent_turn(
            db,
            session_id,
            "January 5th 1980",
            input_mode="voice",
            answered_field_key="person1.dob",
        )
    finally:
        get_settings.cache_clear()

    row = db.query(FormAnswer).filter(
        FormAnswer.session_id == session_id,
        FormAnswer.field_key == "person1.dob",
    ).one()
    assert row.value_json == '"1980-01-05"'
    assert row.confidence < 0.75
    assert result["done"] is False
    assert result["state"]["next_field_key"] == "person1.dob"
    assert result["next_field"]["type"] == "confirmation"
    assert "is that right" in result["assistant_message"].lower()

    get_settings.cache_clear()
    try:
        confirmed = run_agent_turn(
            db,
            session_id,
            "yes",
            input_mode="voice",
            answered_field_key="person1.dob",
        )
    finally:
        get_settings.cache_clear()

    db.refresh(row)
    assert row.confidence == 1.0
    assert confirmed["state"]["next_field_key"] is None


def test_agent_help_request_explains_current_field_without_saving(client, db, monkeypatch):
    """A help question about the active field must not be stored as an answer."""
    from app.ai.agent import run_agent_turn
    from app.core.config import get_settings
    from app.db.models import FormAnswer

    schema = {
        "form_id": "AGENT_HELP",
        "form_title": "Agent Help",
        "version": "1.0",
        "sections": [
            {
                "section_key": "s",
                "section_title": "Programs",
                "fields": [
                    {
                        "field_key": "applicant.programs.wic",
                        "label": "Applying for WIC",
                        "section": "s",
                        "type": "boolean",
                        "required": False,
                        "question_text": "Are you applying for WIC (Women, Infants and Children)?",
                    }
                ],
            }
        ],
    }
    token = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/admin/forms", headers=headers, json={"form_id": "AGENT_HELP", "title": "Agent Help"})
    client.put("/api/admin/forms/AGENT_HELP/schema", headers=headers, json={"schema": schema})
    client.post("/api/admin/forms/AGENT_HELP/publish", headers=headers)
    session_id = client.post(
        "/api/session/create",
        json={"form_id": "AGENT_HELP", "manual_mode": True},
    ).json()["session_id"]

    class FakeCompletions:
        def create(self, **_kwargs):
            raise AssertionError("Help turns should be answered before the model call.")

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    monkeypatch.setattr("app.ai.llm.get_chat_model", lambda: None)
    get_settings.cache_clear()
    try:
        result = run_agent_turn(
            db,
            session_id,
            "I don't know what that is can you explain",
            input_mode="voice",
            answered_field_key="applicant.programs.wic",
        )
    finally:
        get_settings.cache_clear()

    assert result is not None
    assert result["state"]["next_field_key"] == "applicant.programs.wic"
    assert result["next_field"]["field_key"] == "applicant.programs.wic"
    assert "wic" in result["assistant_message"].lower()
    assert "women" in result["assistant_message"].lower()
    assert not result["assistant_message"].lower().startswith("got it")
    assert db.query(FormAnswer).filter(FormAnswer.session_id == session_id).count() == 0


def test_agent_start_fallback_introduces_form_and_checklist(client, db, monkeypatch):
    """If the LLM fails on startup, the deterministic opening still orients the user."""
    from app.ai.agent import run_agent_turn
    from app.core.config import get_settings

    schema = {
        "form_id": "AGENT_START",
        "form_title": "Ohio Medicaid Application",
        "version": "1.0",
        "sections": [
            {
                "section_key": "s",
                "section_title": "Applicant",
                "fields": [
                    {
                        "field_key": "person1.first_name",
                        "label": "First Name",
                        "section": "s",
                        "type": "text",
                        "required": True,
                        "question_text": "What is your first name?",
                    },
                    {
                        "field_key": "income.emp1_gross_wages",
                        "label": "Gross wages",
                        "section": "s",
                        "type": "number",
                        "required": False,
                        "question_text": "What is your gross pay before taxes?",
                    },
                ],
            }
        ],
    }
    token = client.post("/api/admin/login", json={"username": "admin", "password": "admin1234"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/admin/forms", headers=headers, json={"form_id": "AGENT_START", "title": "Ohio Medicaid Application"})
    client.put("/api/admin/forms/AGENT_START/schema", headers=headers, json={"schema": schema})
    client.post("/api/admin/forms/AGENT_START/publish", headers=headers)
    session_id = client.post(
        "/api/session/create",
        json={"form_id": "AGENT_START", "manual_mode": True},
    ).json()["session_id"]

    class FakeCompletions:
        def create(self, **_kwargs):
            raise RuntimeError("simulated quota or provider failure")

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    get_settings.cache_clear()
    try:
        result = run_agent_turn(db, session_id, "__start__", input_mode="voice")
    finally:
        get_settings.cache_clear()

    text = result["assistant_message"].lower()
    assert "smart ai assistant" in text
    assert "ohio medicaid application" in text
    assert "10 to 15 minutes" in text
    assert "review everything" in text
    assert "income" in text
    assert "what is your first name" in text
    assert not text.startswith("got it")
