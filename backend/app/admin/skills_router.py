"""
Builder API for skills (reusable AI capabilities).

- ``GET  /api/admin/skills``                 — the capability catalog (built-ins)
- ``POST /api/admin/skills/{key}/run``        — invoke a skill (for testing in the UI)
- ``GET  /api/admin/forms/{id}/skills``       — which skills a form has attached
- ``PUT  /api/admin/forms/{id}/skills``       — set the attached skill keys

The catalog is code (app/skills/registry.py); attachment is data (form_skills).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.admin.router import _verify_token
from app.db.models import Form, FormSkill
from app.db.session import get_db
from app.skills import registry

router = APIRouter(prefix="/api/admin", tags=["admin:skills"])


class SkillRunRequest(BaseModel):
    params: dict = Field(default_factory=dict)


class FormSkillsUpdate(BaseModel):
    skill_keys: list[str]


def _ensure_form(db: Session, form_id: str) -> None:
    if db.query(Form).filter(Form.form_id == form_id).first() is None:
        raise HTTPException(status_code=404, detail=f"Form {form_id!r} not found")


@router.get("/skills")
def list_skill_catalog(_admin: Annotated[str, Depends(_verify_token)]) -> list[dict]:
    """The built-in skill catalog (key / name / description)."""
    return registry.list_builtins()


@router.post("/skills/{key}/run")
def run_skill(
    key: str,
    body: SkillRunRequest,
    _admin: Annotated[str, Depends(_verify_token)],
) -> dict:
    """Invoke a skill with params and return its result (for try-it-out in the builder)."""
    if key not in registry.BUILTINS:
        raise HTTPException(status_code=404, detail=f"Unknown skill {key!r}")
    return registry.run_skill(key, body.params)


@router.get("/forms/{form_id}/skills")
def get_form_skills(
    form_id: str,
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> dict:
    """Return ``{"attached": [skill_key, ...]}`` for a form."""
    _ensure_form(db, form_id)
    rows = db.query(FormSkill).filter(FormSkill.form_id == form_id, FormSkill.enabled.is_(True)).all()
    return {"attached": [r.skill_key for r in rows]}


@router.put("/forms/{form_id}/skills")
def set_form_skills(
    form_id: str,
    body: FormSkillsUpdate,
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> dict:
    """Replace a form's attached skills with the given built-in keys."""
    _ensure_form(db, form_id)
    unknown = [k for k in body.skill_keys if k not in registry.BUILTINS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown skill key(s): {', '.join(unknown)}")
    valid = list(dict.fromkeys(body.skill_keys))
    db.query(FormSkill).filter(FormSkill.form_id == form_id).delete()
    for key in valid:
        db.add(FormSkill(form_id=form_id, skill_key=key, enabled=True))
    db.commit()
    return {"attached": valid}
