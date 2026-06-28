from pydantic import BaseModel, Field
from typing import Any


class CreateSessionRequest(BaseModel):
    patient_id: str | None = None
    form_id: str = "ODM_07216"
    manual_mode: bool = False
    # Optional startup answers for form-level gates chosen before the interview.
    # Used by the clinical battery picker to activate only the selected tools.
    initial_answers: dict[str, Any] | None = None


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
    field_type: str = "text"
    options: list[Any] | None = None
    value: Any
    source: str
    section: str
    section_title: str
    is_sensitive: bool = False
    is_required: bool = True
    confidence: float | None = None


class ReadinessIssue(BaseModel):
    field_key: str
    label: str
    section: str
    severity: str
    kind: str
    message: str
    action: str
    confidence: float | None = None
    source: str | None = None


class PdfReadiness(BaseModel):
    form_id: str
    has_mapping: bool
    mapping_path: str | None = None
    base_pdf: str | None = None
    base_pdf_exists: bool
    mapped_field_count: int
    excluded_field_count: int
    unmapped_schema_fields: list[str]
    stale_mapping_fields: list[str]
    missing_pdf_widgets: list[str]
    official_pdf_ready: bool
    mapped_field_keys: list[str]


class ReadinessReport(BaseModel):
    ready: bool
    status: str
    confidence_threshold: float
    summary: dict[str, int]
    blockers: list[ReadinessIssue]
    warnings: list[ReadinessIssue]
    missing_required: list[str]
    missing_optional: list[str]
    missing_applicable: list[str]
    invalid_fields: list[ReadinessIssue]
    low_confidence_fields: list[ReadinessIssue]
    skipped_fields: list[ReadinessIssue]
    pdf: PdfReadiness
    unknown_answer_keys: list[str]


class ReviewResponse(BaseModel):
    session_id: str
    form_id: str
    form_title: str
    sections: dict[str, list[ReviewField]]
    missing_required: list[str]
    missing_applicable: list[str]
    is_complete: bool
    readiness: ReadinessReport
    scores: list[dict[str, Any]] = Field(default_factory=list)


class GeneratePdfResponse(BaseModel):
    session_id: str
    download_url: str
    file_name: str
    is_fallback: bool
