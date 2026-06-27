"""
Patient-facing workflow API: approve a completed session and trigger completion.

``POST /api/session/{id}/approve`` is the human-approval gate: it records the
approval, runs the form's workflow (generate PDF and/or, later, submit to a portal),
then marks the session completed only when the workflow succeeds.
``GET /api/session/{id}/workflow`` returns the
latest run's status for polling. Both are patient actions (no admin token).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.audit import log_event
from app.db.models import FormAnswer, FormApproval, FormSession, utcnow
from app.db.session import get_db
from app.sessions.service import get_session_readiness
from app.workflows.engine import get_latest_run, run_status_dict, run_workflow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/session", tags=["workflow"])


class ApproveRequest(BaseModel):
    approved_by: str = "patient"
    note: str | None = None


@router.post("/{session_id}/approve")
def approve_and_run(session_id: str, body: ApproveRequest, db: Session = Depends(get_db)) -> dict:
    """Record approval, run completion, and finalize status from the result."""
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    readiness = get_session_readiness(db, session_id)
    if not readiness or not readiness["ready"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Cannot approve until the readiness gate passes.",
                "missing_fields": (readiness or {}).get("missing_applicable", []),
                "readiness": readiness,
            },
        )

    if not _latest_approval_is_current(db, session):
        db.add(FormApproval(session_id=session_id, form_id=session.form_id, approved_by=body.approved_by, note=body.note))
    session.status = "ready_for_review"
    session.completed_at = None
    db.commit()
    log_event(db, event_type="session_approved", session_id=session_id)

    settings = get_settings()
    if settings.WORKFLOW_ENGINE.lower() == "temporal":
        try:
            from app.workflows.temporal_engine import execute_completion_workflow_sync

            result = execute_completion_workflow_sync(session_id)
        except Exception as exc:
            logger.warning("Temporal workflow unavailable for session %s; falling back to local engine.", session_id, exc_info=True)
            result = _run_local_fallback(db, session, session_id)
            _finalize_completion_status(db, session, result.get("status") == "completed")
            log_event(
                db,
                event_type="workflow_completed" if result.get("status") == "completed" else "workflow_failed",
                session_id=session_id,
                metadata={"status": result.get("status"), "engine": "local-fallback"},
            )
            return result
        _finalize_completion_status(db, session, result.get("status") == "completed")
        log_event(
            db,
            event_type="workflow_completed" if result.get("status") == "completed" else "workflow_failed",
            session_id=session_id,
            metadata={"status": result.get("status"), "engine": "temporal"},
        )
        return result

    run = run_workflow(db, session_id)
    _finalize_completion_status(db, session, run.status == "completed")
    log_event(
        db,
        event_type="workflow_completed" if run.status == "completed" else "workflow_failed",
        session_id=session_id,
        metadata={"status": run.status, "engine": "local"},
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


def _run_local_fallback(db: Session, session: FormSession, session_id: str) -> dict:
    """Use the in-process engine if Temporal cannot be reached."""
    try:
        run = run_workflow(db, session_id)
        return run_status_dict(db, run)
    except Exception as exc:
        logger.warning("Local fallback workflow failed for session %s.", session_id, exc_info=True)
        _finalize_completion_status(db, session, False)
        log_event(
            db,
            event_type="workflow_failed",
            session_id=session_id,
            metadata={"status": "failed", "engine": "local-fallback"},
        )
        raise HTTPException(
            status_code=503,
            detail="Completion service is temporarily unavailable. Please try again.",
        ) from exc


def _finalize_completion_status(db: Session, session: FormSession, completed: bool) -> None:
    """Keep session status aligned with actual completion side effects."""
    if completed:
        session.status = "completed"
        session.completed_at = utcnow()
    else:
        session.status = "ready_for_review"
        session.completed_at = None
    db.commit()


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
