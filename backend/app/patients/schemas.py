from pydantic import BaseModel, field_validator
from datetime import date


class PatientSearchRequest(BaseModel):
    first_name: str
    last_name: str
    dob: str  # YYYY-MM-DD
    consent: bool

    @field_validator("consent")
    @classmethod
    def consent_required(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Consent is required to search the EMR database.")
        return v

    @field_validator("first_name", "last_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name fields cannot be empty.")
        return v.strip()


class PatientSearchResponse(BaseModel):
    matches: list[dict]
    count: int
    is_mock: bool
    message: str | None = None
