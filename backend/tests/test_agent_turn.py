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
