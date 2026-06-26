"""
Builder CRUD API for per-form knowledgebase documents (admin-only).

The KB manager in the builder uses these to add/list/remove the PHI-free guidance
documents the AI uses to help a user understand a question. Creating or re-embedding
a document chunks + embeds it immediately (see app/ai/kb.py).

🔒 KB content must be PHI-free, form-level guidance only.
"""

from __future__ import annotations

import hashlib
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.admin.router import _verify_token
from app.ai import kb
from app.db.models import KbChunk, KbDocument
from app.db.session import get_db

router = APIRouter(prefix="/api/admin/forms", tags=["admin:kb"])


class KbDocCreate(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1)
    source: str | None = None


class KbDocSummary(BaseModel):
    id: int
    doc_key: str
    title: str
    source: str | None = None
    status: str
    chunk_count: int


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:120] or "doc"


def _summary(db: Session, doc: KbDocument) -> KbDocSummary:
    count = db.query(KbChunk).filter(KbChunk.kb_document_id == doc.id).count()
    return KbDocSummary(
        id=doc.id, doc_key=doc.doc_key, title=doc.title, source=doc.source,
        status=doc.status, chunk_count=count,
    )


@router.get("/{form_id}/kb", response_model=list[KbDocSummary])
def list_kb(
    form_id: str,
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> list[KbDocSummary]:
    docs = db.query(KbDocument).filter(KbDocument.form_id == form_id).order_by(KbDocument.id).all()
    return [_summary(db, d) for d in docs]


@router.post("/{form_id}/kb", response_model=KbDocSummary, status_code=201)
def create_kb(
    form_id: str,
    body: KbDocCreate,
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> KbDocSummary:
    """Add a KB document and embed it immediately."""
    doc = KbDocument(
        form_id=form_id,
        doc_key=_slug(body.title),
        title=body.title,
        source=body.source,
        mime="text/plain",
        text=body.text,
        status="pending",
        checksum=hashlib.md5(body.text.encode()).hexdigest(),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    kb.ingest_document(db, doc)  # chunk + embed now
    db.refresh(doc)
    return _summary(db, doc)


@router.post("/{form_id}/kb/{doc_id}/reembed", response_model=KbDocSummary)
def reembed_kb(
    form_id: str,
    doc_id: int,
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> KbDocSummary:
    doc = db.query(KbDocument).filter(KbDocument.id == doc_id, KbDocument.form_id == form_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="KB document not found")
    kb.ingest_document(db, doc)
    db.refresh(doc)
    return _summary(db, doc)


@router.delete("/{form_id}/kb/{doc_id}", status_code=204)
def delete_kb(
    form_id: str,
    doc_id: int,
    _admin: Annotated[str, Depends(_verify_token)],
    db: Session = Depends(get_db),
) -> None:
    doc = db.query(KbDocument).filter(KbDocument.id == doc_id, KbDocument.form_id == form_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="KB document not found")
    db.delete(doc)  # cascade drops chunks
    db.commit()
