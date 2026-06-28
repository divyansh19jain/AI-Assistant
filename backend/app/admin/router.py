import logging
from datetime import datetime, timezone, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.db.models import FormSession, FormAnswer, GeneratedPdf
from app.db.session import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=True)


class LoginRequest(BaseModel):
    username: str
    password: str


def _issue_token(username: str) -> str:
    cfg = get_settings()
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=cfg.ADMIN_JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, cfg.ADMIN_JWT_SECRET, algorithm="HS256")


def _verify_token(credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)]) -> str:
    cfg = get_settings()
    try:
        payload = jwt.decode(credentials.credentials, cfg.ADMIN_JWT_SECRET, algorithms=["HS256"])
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post("/login")
def admin_login(body: LoginRequest) -> dict:
    cfg = get_settings()
    # Fail closed off dev: insecure built-in defaults must be overridden by env.
    if cfg.APP_ENV != "development" and (
        cfg.ADMIN_PASSWORD == "admin1234" or cfg.ADMIN_JWT_SECRET == "change-me-in-production"
    ):
        raise HTTPException(status_code=503, detail="Admin auth is not configured for this environment")
    if body.username != cfg.ADMIN_USERNAME or body.password != cfg.ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = _issue_token(body.username)
    return {"token": token}


@router.get("/dashboard")
def admin_dashboard(
    _admin: Annotated[str, Depends(_verify_token)],
    db: DBSession = Depends(get_db),
    include_archived: bool = False,
) -> dict:
    q = db.query(FormSession)
    if not include_archived:
        q = q.filter(FormSession.archived.is_(False))
    sessions = q.order_by(FormSession.created_at.desc()).limit(200).all()

    answer_counts: dict[str, int] = {}
    first_names: dict[str, str] = {}
    if sessions:
        session_ids = [s.id for s in sessions]
        rows = (
            db.query(FormAnswer.session_id, func.count(FormAnswer.id))
            .filter(FormAnswer.session_id.in_(session_ids))
            .group_by(FormAnswer.session_id)
            .all()
        )
        answer_counts = {sid: cnt for sid, cnt in rows}

        import json as _json
        name_rows = (
            db.query(FormAnswer.session_id, FormAnswer.value_json)
            .filter(
                FormAnswer.session_id.in_(session_ids),
                FormAnswer.field_key == "applicant.first_name",
            )
            .all()
        )
        for sid, val in name_rows:
            try:
                first_names[sid] = _json.loads(val) if val else ""
            except Exception:
                first_names[sid] = val or ""

    pdf_sessions: set[str] = set()
    if sessions:
        pdf_rows = (
            db.query(GeneratedPdf.session_id)
            .filter(GeneratedPdf.session_id.in_([s.id for s in sessions]))
            .distinct()
            .all()
        )
        pdf_sessions = {r.session_id for r in pdf_rows}

    # Stats are over NON-archived sessions so the numbers match the working list.
    live = db.query(func.count(FormSession.id)).filter(FormSession.archived.is_(False))
    total = live.scalar() or 0
    completed = live.filter(FormSession.status == "completed").scalar() or 0
    active = live.filter(FormSession.status == "active").scalar() or 0
    ready_for_review = live.filter(FormSession.status == "ready_for_review").scalar() or 0
    # Orphan = active but never answered a single question (abandoned, safe to archive).
    answered_ids = db.query(FormAnswer.session_id).distinct()
    orphan = (
        db.query(func.count(FormSession.id))
        .filter(
            FormSession.archived.is_(False),
            FormSession.status == "active",
            ~FormSession.id.in_(answered_ids),
        )
        .scalar()
        or 0
    )
    archived = db.query(func.count(FormSession.id)).filter(FormSession.archived.is_(True)).scalar() or 0

    return {
        "stats": {
            "total": total,
            "completed": completed,
            "active": active,
            "ready_for_review": ready_for_review,
            "orphan": orphan,
            "archived": archived,
        },
        "sessions": [
            {
                "id": s.id,
                "first_name": first_names.get(s.id, ""),
                "form_id": s.form_id,
                "patient_external_id": s.patient_external_id,
                "status": s.status,
                "mock_mode": s.mock_mode,
                "archived": s.archived,
                "answer_count": answer_counts.get(s.id, 0),
                "has_pdf": s.id in pdf_sessions,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            }
            for s in sessions
        ],
    }


def _get_session_or_404(db: DBSession, session_id: str) -> FormSession:
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/sessions/{session_id}/archive")
def archive_session(session_id: str, _admin: Annotated[str, Depends(_verify_token)], db: DBSession = Depends(get_db)) -> dict:
    session = _get_session_or_404(db, session_id)
    session.archived = True
    db.commit()
    return {"id": session_id, "archived": True}


@router.post("/sessions/{session_id}/unarchive")
def unarchive_session(session_id: str, _admin: Annotated[str, Depends(_verify_token)], db: DBSession = Depends(get_db)) -> dict:
    session = _get_session_or_404(db, session_id)
    session.archived = False
    db.commit()
    return {"id": session_id, "archived": False}


@router.post("/sessions/archive-orphans")
def archive_orphans(_admin: Annotated[str, Depends(_verify_token)], db: DBSession = Depends(get_db)) -> dict:
    """Archive every active session that has no answers yet (abandoned)."""
    answered_ids = db.query(FormAnswer.session_id).distinct()
    orphans = (
        db.query(FormSession)
        .filter(
            FormSession.archived.is_(False),
            FormSession.status == "active",
            ~FormSession.id.in_(answered_ids),
        )
        .all()
    )
    for session in orphans:
        session.archived = True
    db.commit()
    return {"archived_count": len(orphans)}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, _admin: Annotated[str, Depends(_verify_token)], db: DBSession = Depends(get_db)) -> dict:
    """Permanently delete a session and everything attached to it."""
    from app.db.models import FormApproval, SessionMessage, WorkflowRun, WorkflowTaskRun

    session = _get_session_or_404(db, session_id)
    run_ids = [r.id for r in db.query(WorkflowRun.id).filter(WorkflowRun.session_id == session_id).all()]
    if run_ids:
        db.query(WorkflowTaskRun).filter(WorkflowTaskRun.workflow_run_id.in_(run_ids)).delete(synchronize_session=False)
    db.query(WorkflowRun).filter(WorkflowRun.session_id == session_id).delete(synchronize_session=False)
    db.query(FormApproval).filter(FormApproval.session_id == session_id).delete(synchronize_session=False)
    db.query(SessionMessage).filter(SessionMessage.session_id == session_id).delete(synchronize_session=False)
    db.query(GeneratedPdf).filter(GeneratedPdf.session_id == session_id).delete(synchronize_session=False)
    db.query(FormAnswer).filter(FormAnswer.session_id == session_id).delete(synchronize_session=False)
    db.delete(session)
    db.commit()
    return {"id": session_id, "deleted": True}
