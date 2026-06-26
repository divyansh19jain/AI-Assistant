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
) -> dict:
    sessions = (
        db.query(FormSession)
        .order_by(FormSession.created_at.desc())
        .limit(200)
        .all()
    )

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

    total = db.query(func.count(FormSession.id)).scalar() or 0
    completed = db.query(func.count(FormSession.id)).filter(FormSession.status == "completed").scalar() or 0
    active = db.query(func.count(FormSession.id)).filter(FormSession.status == "active").scalar() or 0

    return {
        "stats": {
            "total": total,
            "completed": completed,
            "active": active,
        },
        "sessions": [
            {
                "id": s.id,
                "first_name": first_names.get(s.id, ""),
                "form_id": s.form_id,
                "patient_external_id": s.patient_external_id,
                "status": s.status,
                "mock_mode": s.mock_mode,
                "answer_count": answer_counts.get(s.id, 0),
                "has_pdf": s.id in pdf_sessions,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            }
            for s in sessions
        ],
    }
