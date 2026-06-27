from pydantic import BaseModel
from typing import Any


class CreateSessionRequest(BaseModel):
    patient_id: str | None = None
    form_id: str = "ODM_07216"
    manual_mode: bool = False


class AnswerRequest(BaseModel):
    field_key: str
    raw_answer: str
    input_mode: str = "typed"  # typed | voice
    # True when the user is confirming a previously-extracted value (the raw
    # value the assistant read back during a smart-confirm prompt).
    confirmed: bool = False


class SessionFieldSummary(BaseModel):
    field_key: str
    label: str
    value: Any
    source: str
    section: str
    is_sensitive: bool = False


class SessionState(BaseModel):
    session_id: str
    form_id: str
    form_title: str
    status: str
    mock_mode: bool
    prefilled_count: int
    missing_count: int
    total_required: int
    next_question: dict | None
    prefilled_fields: list[SessionFieldSummary]
    answers: dict[str, Any]


class ReviewField(BaseModel):
    field_key: str
    label: str
    value: Any
    source: str
    section: str
    section_title: str
    is_sensitive: bool = False
    is_required: bool = True


class ReviewResponse(BaseModel):
    session_id: str
    form_id: str
    form_title: str
    sections: dict[str, list[ReviewField]]
    missing_required: list[str]
    missing_applicable: list[str]
    is_complete: bool


class GeneratePdfResponse(BaseModel):
    session_id: str
    download_url: str
    file_name: str
    is_fallback: bool
