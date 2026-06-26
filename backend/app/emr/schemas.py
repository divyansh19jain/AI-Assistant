from pydantic import BaseModel
from typing import Any


class EMRAddress(BaseModel):
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    county: str | None = None


class EMRPatient(BaseModel):
    external_patient_id: str
    first_name: str
    middle_name: str | None = None
    last_name: str
    suffix: str | None = None
    dob: str | None = None  # YYYY-MM-DD
    sex: str | None = None
    ssn: str | None = None
    phone: str | None = None
    email: str | None = None
    marital_status: str | None = None
    language: str | None = None
    address: EMRAddress = EMRAddress()
    insurance: list[Any] = []
    employment: list[Any] = []
    income: list[Any] = []


class MaskedPatient(BaseModel):
    external_patient_id: str
    first_name: str
    last_name: str
    dob: str
    phone: str | None = None
    is_mock: bool = False
