"""
Builder CRUD API for forms (admin-only).

The write side of the platform: the ``/admin`` builder UI uses these endpoints to
create, edit, publish, and delete forms. All routes are protected by the same JWT
bearer dependency as the rest of the admin API (``_verify_token`` from
:mod:`app.admin.router`).

**Source-of-truth + cache coherence.** The ``forms`` table is authoritative. Because
the form engine reads schemas from a process-local cache
(:mod:`app.forms.cache`) for a no-DB-on-the-hot-path lookup, every write here keeps
that cache coherent:
- publish / schema-edit of a published form -> :func:`cache.set_schema`
- unpublish / delete / draft edit -> :func:`cache.drop`

So a form edited in the builder is immediately reflected in the patient flow once
published — closing the create-in-UI -> run-end-to-end loop.

🔒 No PHI: forms are static definitions. (The admin auth defaults remain insecure for
prod and are hardened separately — see docs/ai/IMPROVEMENT-BACKLOG.md I-3.)
"""

from __future__ import annotations

import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.admin.router import _verify_token  # reuse the admin JWT bearer dependency
from app.db.models import Form, utcnow
from app.db.session import get_db
from app.forms import cache

router = APIRouter(prefix="/api/admin/forms", tags=["admin:forms"])

# form_id is an identifier used in URLs, the cache, and pack folder names: keep it to a
# safe, predictable shape (letters/digits/_/-, e.g. "ODM_07216").
_FORM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,64}$")


# ──────────────────────────── request / response models ────────────────────────────
class FormSummary(BaseModel):
    """List-view row for the builder's forms table."""

    form_id: str
    title: str
    version: str
    status: str
    output_targets: list[str]
    updated_at: str | None = None


class FormDetail(FormSummary):
    """Full form record for the editor (parsed JSON documents).

    The field is ``form_schema`` (the name ``schema`` would shadow pydantic's
    ``BaseModel.schema()``); the JSON key stays ``"schema"`` via the alias. FastAPI
    serializes response models by alias, so clients still see ``"schema"``.
    """

    model_config = ConfigDict(populate_by_name=True)
    form_schema: dict = Field(alias="schema")
    prompt: dict | None = None
    voice: dict | None = None


class FormCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    form_id: str
    title: str = Field(min_length=1, max_length=256)
    version: str = "1.0"
    output_targets: list[str] = ["pdf"]
    # Optional starting schema; JSON key "schema" via alias (see FormDetail note).
    form_schema: dict | None = Field(default=None, alias="schema")

    @field_validator("form_id")
    @classmethod
    def _valid_form_id(cls, v: str) -> str:
        if not _FORM_ID_RE.match(v):
            raise ValueError("form_id must be 2-64 chars of letters, digits, '_' or '-'")
        return v


class FormMetaUpdate(BaseModel):
    """Partial update of a form's metadata (not its schema — see :class:`SchemaUpdate`)."""

    title: str | None = Field(default=None, max_length=256)
    version: str | None = None
    output_targets: list[str] | None = None


class SchemaUpdate(BaseModel):
    """Replace a form's field schema (what the schema/field editor saves)."""

    model_config = ConfigDict(populate_by_name=True)
    form_schema: dict = Field(alias="schema")

    @field_validator("form_schema")
    @classmethod
    def _has_sections(cls, v: dict) -> dict:
        # Minimal structural validation: the engine iterates schema["sections"][*]["fields"].
        if not isinstance(v.get("sections"), list):
            raise ValueError("schema must contain a 'sections' list")
        return v


# ──────────────────────────────── helpers ────────────────────────────────
def _targets_to_list(value: str | None) -> list[str]:
    return value.split(",") if value else ["pdf"]


def _to_summary(row: Form) -> FormSummary:
    return FormSummary(
        form_id=row.form_id,
        title=row.title,
        version=row.version,
        status=row.status,
        output_targets=_targets_to_list(row.output_targets),
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def _to_detail(row: Form) -> FormDetail:
    return FormDetail(
        **_to_summary(row).model_dump(),
        form_schema=json.loads(row.schema_json),
        prompt=json.loads(row.prompt_json) if row.prompt_json else None,
        voice=json.loads(row.voice_json) if row.voice_json else None,
    )


def _get_or_404(db: Session, form_id: str) -> Form:
    row = db.query(Form).filter(Form.form_id == form_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Form {form_id!r} not found")
    return row


def _sync_cache(row: Form) -> None:
    """Keep the engine's schema cache coherent with a form's status after a write."""
    if row.status == "published":
        cache.set_schema(row.form_id, json.loads(row.schema_json))
    else:
        cache.drop(row.form_id)


_EMPTY_SCHEMA_SECTIONS: list[dict] = [
    {"section_key": "section_1", "section_title": "Section 1", "fields": []}
]


# ──────────────────────────────── endpoints ────────────────────────────────
@router.get("", response_model=list[FormSummary])
def list_all_forms(
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> list[FormSummary]:
    """All forms (any status) for the builder table, newest first."""
    rows = db.query(Form).order_by(Form.updated_at.desc()).all()
    return [_to_summary(r) for r in rows]


@router.get("/{form_id}", response_model=FormDetail)
def get_form(
    form_id: str,
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> FormDetail:
    """Full form record (schema + prompt + voice) for the editor."""
    return _to_detail(_get_or_404(db, form_id))


@router.post("", response_model=FormDetail, status_code=201)
def create_form(
    body: FormCreate,
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> FormDetail:
    """Create a new (draft) form. Drafts are editable but not runnable until published."""
    if db.query(Form).filter(Form.form_id == body.form_id).first() is not None:
        raise HTTPException(status_code=409, detail=f"Form {body.form_id!r} already exists")

    schema = body.form_schema or {
        "form_id": body.form_id,
        "form_title": body.title,
        "version": body.version,
        "sections": _EMPTY_SCHEMA_SECTIONS,
    }
    row = Form(
        form_id=body.form_id,
        title=body.title,
        version=body.version,
        status="draft",
        output_targets=",".join(body.output_targets),
        schema_json=json.dumps(schema),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    # Draft -> intentionally not cached until published.
    return _to_detail(row)


@router.put("/{form_id}", response_model=FormDetail)
def update_form_meta(
    form_id: str,
    body: FormMetaUpdate,
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> FormDetail:
    """Update a form's metadata (title / version / output targets)."""
    row = _get_or_404(db, form_id)
    if body.title is not None:
        row.title = body.title
    if body.version is not None:
        row.version = body.version
    if body.output_targets is not None:
        row.output_targets = ",".join(body.output_targets)
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    _sync_cache(row)
    return _to_detail(row)


@router.put("/{form_id}/schema", response_model=FormDetail)
def update_form_schema(
    form_id: str,
    body: SchemaUpdate,
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> FormDetail:
    """Replace a form's field schema (the schema/field editor's save action)."""
    row = _get_or_404(db, form_id)
    row.schema_json = json.dumps(body.form_schema)
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    _sync_cache(row)  # if published, the patient flow sees the new schema immediately
    return _to_detail(row)


@router.post("/{form_id}/publish", response_model=FormDetail)
def publish_form(
    form_id: str,
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> FormDetail:
    """Publish a form so it appears in the patient picker and is runnable."""
    row = _get_or_404(db, form_id)
    row.status = "published"
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    cache.set_schema(row.form_id, json.loads(row.schema_json))
    return _to_detail(row)


@router.post("/{form_id}/unpublish", response_model=FormDetail)
def unpublish_form(
    form_id: str,
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> FormDetail:
    """Return a form to draft (hidden from the patient picker)."""
    row = _get_or_404(db, form_id)
    row.status = "draft"
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    cache.drop(row.form_id)
    return _to_detail(row)


@router.delete("/{form_id}", status_code=204)
def delete_form(
    form_id: str,
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> None:
    """Delete a form definition. (Sessions/answers are unaffected — they reference form_id by value.)"""
    row = _get_or_404(db, form_id)
    db.delete(row)
    db.commit()
    cache.drop(form_id)
