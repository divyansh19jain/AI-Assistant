import logging
from fastapi import APIRouter, Depends, HTTPException
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
from app.forms.missing_fields import get_missing_applicable_fields

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


@router.get("/{session_id}/review")
def get_review(session_id: str, db: DBSession = Depends(get_db)) -> dict:
    review = svc.get_review_data(db, session_id)
    if not review:
        raise HTTPException(status_code=404, detail="Session not found")
    return review


@router.post("/{session_id}/generate-pdf")
def generate_pdf(session_id: str, db: DBSession = Depends(get_db)) -> dict:
    from app.pdf.pdf_service import generate_session_pdf
    from app.db.models import FormAnswer, FormApproval, FormSession

    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    schema = svc._schema_for_session(session)
    answers = svc._answers_map(db, session_id)
    missing = get_missing_applicable_fields(session.form_id, answers, schema)
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Cannot generate a PDF until all applicable fields are answered or skipped.",
                "missing_fields": [f["field_key"] for f in missing],
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
