import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.audit import log_event
from app.patients.schemas import PatientSearchRequest, PatientSearchResponse
from app.patients.service import search_patients

router = APIRouter(prefix="/api/patient", tags=["patient"])
logger = logging.getLogger(__name__)


@router.post("/search", response_model=PatientSearchResponse)
def search_patient(
    request: PatientSearchRequest,
    db: Session = Depends(get_db),
) -> PatientSearchResponse:
    log_event(
        db,
        event_type="patient_search_requested",
        metadata={"first_name_initial": request.first_name[0] if request.first_name else ""},
    )

    matches, is_mock = search_patients(request.first_name, request.last_name, request.dob)

    message = None
    if is_mock:
        message = "MOCK MODE: Results are simulated. Set USE_MOCK_EMR=false and configure EMR_DATABASE_URL to use real data."

    return PatientSearchResponse(
        matches=[m.model_dump() for m in matches],
        count=len(matches),
        is_mock=is_mock,
        message=message,
    )
