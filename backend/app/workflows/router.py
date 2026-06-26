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
from sqlalchemy.orm import Session

from app.core.audit import log_event
from app.db.models import FormApproval, FormSession, utcnow
from app.db.session import get_db
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
    run = get_latest_run(db, session_id)
    if run is None:
        return {"run_id": None, "status": "not_started", "tasks": []}
    return run_status_dict(db, run)
