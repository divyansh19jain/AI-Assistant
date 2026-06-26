"""
Public forms API.

Exposes the catalog of forms the patient-facing flow can start. This is the read
side of the platform: the builder UI writes forms (Phase B, under ``/api/admin``),
and this endpoint lists the **published** ones for the form picker.

DB-first with a filesystem fallback (same philosophy as
:func:`app.forms.service.load_form_schema`): if the ``forms`` table is populated we
serve it; if not (a fresh/un-seeded DB, or the test suite), we fall back to the
bundled packs so the catalog is never empty in a working install.

🔒 No PHI: only form-level metadata is returned.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import Form
from app.db.session import get_db
from app.forms import registry

router = APIRouter(prefix="/api/forms", tags=["forms"])


@router.get("")
def list_forms(db: Session = Depends(get_db)) -> dict:
    """Return ``{"forms": [{form_id, title, version, output_targets}]}`` (published)."""
    rows = (
        db.query(Form)
        .filter(Form.status == "published")
        .order_by(Form.form_id)
        .all()
    )
    if rows:
        forms = [
            {
                "form_id": r.form_id,
                "title": r.title,
                "version": r.version,
                "output_targets": r.output_targets.split(",") if r.output_targets else ["pdf"],
            }
            for r in rows
        ]
    else:
        # DB has no forms yet (un-seeded / tests): serve bundled packs so the picker works.
        forms = [
            {
                "form_id": m["form_id"],
                "title": m["title"],
                "version": m["version"],
                "output_targets": m["output_targets"],
            }
            for m in registry.list_form_metadata()
        ]
    return {"forms": forms}
