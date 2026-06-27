import logging
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession
from app.db.session import get_db
from app.core.audit import log_event
from app.sessions.schemas import (
    CreateSessionRequest, AnswerRequest, SessionState,
    ReviewResponse, GeneratePdfResponse,
)
from app.sessions import service as svc
from app.forms.registry import UnknownFormError

from pydantic import BaseModel


class AgentTurnRequest(BaseModel):
    """One turn of the conversational agent: the person's utterance (typed or transcribed)."""
    message: str = ""
    input_mode: str = "voice"


class HouseholdMemberIn(BaseModel):
    first_name: str = ""
    middle_name: str = ""
    last_name: str = ""
    relationship: str = "other"
    applying: bool = True
    dob: str | None = None
    sex: str | None = None
    is_tax_dependent: bool = False


class HouseholdRequest(BaseModel):
    members: list[HouseholdMemberIn] = []


router = APIRouter(prefix="/api/session", tags=["session"])
logger = logging.getLogger(__name__)


@router.post("/create")
def create_session(
    request: CreateSessionRequest,
    db: DBSession = Depends(get_db),
) -> dict:
    try:
        state = svc.create_session(
            db,
            form_id=request.form_id,
            patient_id=request.patient_id,
            manual_mode=request.manual_mode,
        )
    except UnknownFormError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_event(db, event_type="session_created", session_id=state["session_id"])
    return state


@router.get("/{session_id}")
def get_session(session_id: str, db: DBSession = Depends(get_db)) -> dict:
    state = svc.get_session_state(db, session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    return state


@router.post("/{session_id}/answer")
def submit_answer(
    session_id: str,
    request: AnswerRequest,
    db: DBSession = Depends(get_db),
) -> dict:
    result = svc.save_answer(
        db,
        session_id=session_id,
        field_key=request.field_key,
        raw_answer=request.raw_answer,
        input_mode=request.input_mode,
        confirmed=request.confirmed,
    )
    if not result.get("success"):
        log_event(db, event_type="answer_validation_error", session_id=session_id,
                  metadata={"field_key": request.field_key})
        return result

    log_event(db, event_type="answer_saved", session_id=session_id,
              metadata={"field_key": request.field_key, "mode": request.input_mode})
    return result


@router.post("/{session_id}/skip")
def skip_field(
    session_id: str,
    request: AnswerRequest,
    db: DBSession = Depends(get_db),
) -> dict:
    result = svc.skip_field(db, session_id=session_id, field_key=request.field_key)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    if result.get("success") is True:
        log_event(db, event_type="field_skipped", session_id=session_id,
                  metadata={"field_key": request.field_key})
    return result


@router.post("/{session_id}/back")
def go_back(session_id: str, db: DBSession = Depends(get_db)) -> dict:
    state = svc.go_back(db, session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    log_event(db, event_type="answer_undone", session_id=session_id)
    return state


@router.post("/{session_id}/agent")
def agent_turn(
    session_id: str,
    request: "AgentTurnRequest",
    db: DBSession = Depends(get_db),
) -> dict:
    """Conversational agent turn: the smart, multi-field, human assistant path."""
    from app.ai.agent import run_agent_turn

    state = svc.get_session_state(db, session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    result = run_agent_turn(db, session_id, request.message, input_mode=request.input_mode)
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="Conversational agent unavailable (no AI key configured).",
        )
    # 🔒 Audit metadata only — never the message content (PHI).
    log_event(db, event_type="agent_turn", session_id=session_id,
              metadata={"mode": request.input_mode, "done": result.get("done")})
    return result


@router.get("/{session_id}/review")
def get_review(session_id: str, db: DBSession = Depends(get_db)) -> dict:
    review = svc.get_review_data(db, session_id)
    if not review:
        raise HTTPException(status_code=404, detail="Session not found")
    return review


@router.get("/{session_id}/readiness")
def get_readiness(session_id: str, db: DBSession = Depends(get_db)) -> dict:
    """Deterministic completion gate used by review, approval, PDF, and tests."""
    readiness = svc.get_session_readiness(db, session_id)
    if not readiness:
        raise HTTPException(status_code=404, detail="Session not found")
    return readiness


@router.get("/{session_id}/caseworker-review")
def caseworker_review(session_id: str, db: DBSession = Depends(get_db)) -> dict:
    """Caseworker-style pre-approval view: what's missing, low-confidence, looks off,
    was inferred/skipped, and which documents the county will likely ask for."""
    from app.ai.caseworker_review import build_caseworker_review
    from app.db.models import FormAnswer, FormSession

    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    schema = svc._schema_for_session(session)
    rows = db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
    return build_caseworker_review(session.form_id, schema, rows)


@router.post("/{session_id}/household")
def apply_household(session_id: str, body: HouseholdRequest, db: DBSession = Depends(get_db)) -> dict:
    """Build the household once and populate ODM applicant/Person 2 fields from it,
    deriving the answers instead of asking raw PDF questions one by one."""
    from app.ai.household import HouseholdMember, household_size, to_odm_field_values
    from app.db.models import FormSession

    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    members = [HouseholdMember(**m.model_dump()) for m in body.members]
    schema = svc._schema_for_session(session)
    applied: list[str] = []
    errors: list[dict] = []
    # Insertion order keeps the Person 2 gate ahead of its dependent fields.
    for field_key, value in to_odm_field_values(members).items():
        result = svc.set_field(db, session, schema, field_key, value)
        if result.get("ok"):
            applied.append(field_key)
        else:
            errors.append({"field_key": field_key, "error": result.get("error")})
    size = household_size(members)
    log_event(db, event_type="household_applied", session_id=session_id,
              metadata={"applied": len(applied), "errors": len(errors), "size": size})
    return {"applied": applied, "errors": errors, "household_size": size}


@router.post("/{session_id}/extract-document")
async def extract_document(
    session_id: str,
    file: UploadFile = File(...),
    db: DBSession = Depends(get_db),
) -> dict:
    """OCR a document photo (pay stub, ID, benefit letter) into validated field
    SUGGESTIONS. They are never auto-saved — the person/agent confirms each first."""
    from app.ai.document_extract import _MAX_IMAGE_BYTES, extract_fields_from_image, ocr_enabled
    from app.db.models import FormSession

    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not ocr_enabled():
        raise HTTPException(status_code=503, detail="Document capture is not enabled for this environment.")

    # Reject an oversized upload BEFORE reading it into memory.
    if file.size is not None and file.size > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 8 MB).")

    data = await file.read()
    schema = svc._schema_for_session(session)
    answers = svc._answers_map(db, session_id)  # scope OCR to active, unanswered fields
    result = extract_fields_from_image(data, file.content_type or "image/jpeg", schema, answers)
    # 🔒 audit metadata only — never the extracted values (PHI).
    log_event(db, event_type="document_extract", session_id=session_id,
              metadata={"ok": result.get("ok"), "count": len(result.get("suggestions", []))})
    return result


@router.post("/{session_id}/generate-pdf")
def generate_pdf(session_id: str, db: DBSession = Depends(get_db)) -> dict:
    from app.pdf.pdf_service import generate_session_pdf
    from app.db.models import FormAnswer, FormApproval, FormSession

    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    readiness = svc.get_session_readiness(db, session_id)
    if not readiness or not readiness["ready"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Cannot generate a PDF until the readiness gate passes.",
                "missing_fields": (readiness or {}).get("missing_applicable", []),
                "readiness": readiness,
            },
        )
    latest_approval = (
        db.query(FormApproval)
        .filter(FormApproval.session_id == session_id)
        .order_by(FormApproval.created_at.desc())
        .first()
    )
    if latest_approval is None:
        raise HTTPException(status_code=403, detail="PDF generation requires approval.")
    latest_answer_at = (
        db.query(func.max(FormAnswer.updated_at))
        .filter(FormAnswer.session_id == session_id)
        .scalar()
    )
    if latest_answer_at is not None and latest_approval.created_at < latest_answer_at:
        raise HTTPException(status_code=403, detail="PDF generation requires a fresh approval.")

    result = generate_session_pdf(db, session_id)
    if not result:
        raise HTTPException(status_code=500, detail="PDF generation failed")

    log_event(db, event_type="pdf_generated", session_id=session_id)
    return result


@router.get("/{session_id}/download-pdf")
def download_pdf(session_id: str, db: DBSession = Depends(get_db)):
    from app.db.models import GeneratedPdf
    import os
    pdf_record = (
        db.query(GeneratedPdf)
        .filter(GeneratedPdf.session_id == session_id)
        .order_by(GeneratedPdf.created_at.desc())
        .first()
    )
    if not pdf_record or not os.path.exists(pdf_record.file_path):
        raise HTTPException(status_code=404, detail="PDF not found. Generate it first.")
    return FileResponse(
        pdf_record.file_path,
        media_type="application/pdf",
        filename=pdf_record.file_name,
    )
