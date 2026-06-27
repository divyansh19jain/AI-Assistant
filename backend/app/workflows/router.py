"""
Patient-facing workflow API: approve a completed session and trigger completion.

``POST /api/session/{id}/approve`` is the human-approval gate — it records the
approval, marks the session completed, then runs the form's workflow (generate PDF
and/or, later, submit to a portal). ``GET /api/session/{id}/workflow`` returns the
latest run's status for polling. Both are patient actions (no admin token).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import log_event
from app.db.models import FormAnswer, FormApproval, FormSession, utcnow
from app.db.session import get_db
from app.forms.missing_fields import get_missing_applicable_fields
from app.sessions.service import _answers_map, _schema_for_session
from app.workflows.engine import get_latest_run, run_status_dict, run_workflow

router = APIRouter(prefix="/api/session", tags=["workflow"])


class ApproveRequest(BaseModel):
    approved_by: str = "patient"
    note: str | None = None


@router.post("/{session_id}/approve")
def approve_and_run(session_id: str, body: ApproveRequest, db: Session = Depends(get_db)) -> dict:
    """Record approval, mark the session complete, and run its completion workflow."""
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    schema = _schema_for_session(session)
    missing = get_missing_applicable_fields(session.form_id, _answers_map(db, session_id), schema)
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Cannot approve until all applicable fields are answered or skipped.",
                "missing_fields": [f["field_key"] for f in missing],
            },
        )

    if not _latest_approval_is_current(db, session):
        db.add(FormApproval(session_id=session_id, form_id=session.form_id, approved_by=body.approved_by, note=body.note))
    session.status = "completed"
    session.completed_at = utcnow()
    db.commit()
    log_event(db, event_type="session_approved", session_id=session_id)

    run = run_workflow(db, session_id)
    log_event(
        db,
        event_type="workflow_completed" if run.status == "completed" else "workflow_failed",
        session_id=session_id,
        metadata={"status": run.status},
    )
    return run_status_dict(db, run)


@router.get("/{session_id}/workflow")
def workflow_status(session_id: str, db: Session = Depends(get_db)) -> dict:
    """Latest workflow run status for a session (``status='not_started'`` if none)."""
    if db.query(FormSession.id).filter(FormSession.id == session_id).first() is None:
        raise HTTPException(status_code=404, detail="Session not found")
    run = get_latest_run(db, session_id)
    if run is None:
        return {"run_id": None, "status": "not_started", "tasks": []}
    return run_status_dict(db, run)


def _latest_approval_is_current(db: Session, session: FormSession) -> bool:
    """Return True when the newest approval is newer than every stored answer."""
    approval = (
        db.query(FormApproval)
        .filter(FormApproval.session_id == session.id)
        .order_by(FormApproval.created_at.desc())
        .first()
    )
    if approval is None:
        return False
    latest_answer_at = (
        db.query(func.max(FormAnswer.updated_at))
        .filter(FormAnswer.session_id == session.id)
        .scalar()
    )
    return latest_answer_at is None or approval.created_at >= latest_answer_at
