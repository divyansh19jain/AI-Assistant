"""
Form schema accessors.

Thin, form-agnostic helpers the rest of the backend uses to read a form's field
definitions. Schema *loading* is delegated to :mod:`app.forms.registry` (the
form-pack loader); this module just exposes convenient field-level views over it.

Historically this file hardcoded the single ODM 07216 schema path and rejected any
other ``form_id``. That guard is gone — any form id resolvable to a pack works, so
the platform is multi-form. ``form_id`` defaults to ``"ODM_07216"`` only to preserve
the call sites that predate multi-form; new callers should pass it explicitly.
"""

from app.forms import cache, registry


def load_form_schema(form_id: str = "ODM_07216") -> dict:
    """Return the parsed field schema for ``form_id``.

    Resolution order, reflecting "DB is the source of truth, packs are the seed":
    1. the DB-backed in-memory cache (:mod:`app.forms.cache`), populated from the
       ``forms`` table at startup and on every builder CRUD write;
    2. the filesystem **registry** (bundled packs) as a fallback when the form is not
       in the cache (fresh/un-seeded DB, or tests that never seeded).

    Raises :class:`app.forms.registry.UnknownFormError` if neither source has it.
    The returned dict is shared/cached — treat it as read-only.
    """
    cached = cache.get(form_id)
    if cached is not None:
        return cached
    return registry.load_schema(form_id)


def get_all_fields(form_id: str = "ODM_07216") -> list[dict]:
    """Flatten the schema's sections into a single ordered list of field dicts."""
    schema = load_form_schema(form_id)
    fields: list[dict] = []
    for section in schema.get("sections", []):
        for field in section.get("fields", []):
            fields.append(field)
    return fields


def get_field(field_key: str, form_id: str = "ODM_07216") -> dict | None:
    """Return a single field dict by ``field_key``, or ``None`` if not in the form."""
    for field in get_all_fields(form_id):
        if field["field_key"] == field_key:
            return field
    return None
