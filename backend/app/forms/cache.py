"""
In-memory schema cache — bridges DB-authoritative forms to the form engine.

Now that the **database** is the source of truth for forms (edited via the builder
UI), the form engine still needs a cheap, synchronous ``form_id -> schema dict``
lookup with the *same signature it always had* (``service.load_form_schema(form_id)``
takes no DB session). This module is that bridge:

- At startup we load every published form's ``schema_json`` from the DB into a
  process-local dict (:func:`refresh_all`).
- Builder CRUD writes call :func:`set_schema` / :func:`refresh` to keep it current.
- Reads (:func:`get`) are a plain dict lookup — no DB round-trip on the hot path.

**Resilience / fallback:** if a form is not in the cache (e.g. the DB has not been
seeded yet, or we are in a test that never seeded its DB), callers fall back to the
filesystem **registry** (the bundled packs). So the engine keeps working whether or
not the DB is populated — the DB is authoritative *when present*, and the packs are
the seed + safety net. This is what keeps the test suite green without fighting the
in-memory-SQLite setup.

🔒 No PHI: schemas are static form definitions only.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Process-local cache: form_id -> parsed schema dict (from forms.schema_json).
_SCHEMAS: dict[str, dict] = {}


def set_schema(form_id: str, schema: dict) -> None:
    """Insert/replace one form's schema in the cache (called after a CRUD write)."""
    _SCHEMAS[form_id] = schema


def drop(form_id: str) -> None:
    """Evict one form from the cache (e.g. after delete/unpublish)."""
    _SCHEMAS.pop(form_id, None)


def clear() -> None:
    """Empty the cache. For tests and full reloads."""
    _SCHEMAS.clear()


def get(form_id: str) -> dict | None:
    """Return the cached schema for ``form_id`` or ``None`` (caller then falls back)."""
    return _SCHEMAS.get(form_id)


def refresh(db, form_id: str) -> dict | None:
    """Reload one form's schema from the DB into the cache. Returns it or ``None``.

    Best-effort: a DB/parse failure is logged (no PHI) and returns ``None`` so the
    caller falls back to the filesystem registry rather than erroring.
    """
    from app.db.models import Form  # local import avoids any import-time ORM coupling

    try:
        row = db.query(Form).filter(Form.form_id == form_id).first()
        if row is None:
            return None
        schema = json.loads(row.schema_json)
        _SCHEMAS[form_id] = schema
        return schema
    except Exception:
        logger.warning("Failed to refresh form schema cache for %s.", form_id, exc_info=True)
        return None


def refresh_all(db) -> int:
    """Load all forms' schemas from the DB into the cache. Returns the count loaded.

    Called once at startup (after seeding). Best-effort: failures are logged and the
    cache simply stays partial — the registry fallback covers any gaps.
    """
    from app.db.models import Form

    count = 0
    try:
        for row in db.query(Form).all():
            try:
                _SCHEMAS[row.form_id] = json.loads(row.schema_json)
                count += 1
            except Exception:
                logger.warning("Skipping unparseable schema_json for form %s.", row.form_id)
    except Exception:
        logger.warning("Could not load forms into schema cache; using filesystem packs.", exc_info=True)
    return count
