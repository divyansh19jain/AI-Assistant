"""
Seed DB-authoritative forms from the bundled filesystem packs.

The platform's source of truth is the database, but forms still ship as filesystem
**packs** (``app/forms/packs/<FORM_ID>/``) for version control, review, and as a
starting point. :func:`seed_from_packs` imports any pack that is not yet present in
the ``forms`` table — so a fresh database boots with the bundled ODM 07216 form, and
once an admin edits it in the builder the DB copy wins (we never overwrite an
existing row here).

This is the bridge from the v1 filesystem registry to the v2 DB authority. The same
function is the basis for the explicit "import a pack" action added in Phase H.

🔒 No PHI: packs are static form definitions.
"""

from __future__ import annotations

import json
import logging

from app.forms import registry

logger = logging.getLogger(__name__)


def _build_prompt_json(pack) -> str | None:
    """Assemble a pack's prompt assets (``prompts/``) into a JSON document, or None."""
    prompts_dir = pack.prompts_dir
    system_file = prompts_dir / "system.md"
    overrides_file = prompts_dir / "field_overrides.json"

    system = system_file.read_text(encoding="utf-8") if system_file.is_file() else None
    overrides: dict = {}
    if overrides_file.is_file():
        try:
            overrides = json.loads(overrides_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Pack %s has unparseable field_overrides.json; ignoring.", pack.form_id)

    if system is None and not overrides:
        return None
    return json.dumps({"system": system, "field_overrides": overrides})


def seed_from_packs(db) -> int:
    """Insert any bundled pack not already in the ``forms`` table. Returns count added.

    Idempotent and **non-destructive**: an existing ``forms`` row (e.g. one edited in
    the builder) is left untouched. Best-effort — a failure is rolled back and logged
    (no PHI) so it can never block application startup; the schema cache's filesystem
    fallback keeps the app working even if seeding is skipped.
    """
    from app.db.models import Form  # local import keeps the form layer ORM-light

    added = 0
    try:
        existing = {row.form_id for row in db.query(Form.form_id).all()}
        for pack in registry.list_packs(active_only=False):
            if pack.form_id in existing:
                continue
            voice = (pack.config.get("voice") if isinstance(pack.config, dict) else None) or None
            db.add(
                Form(
                    form_id=pack.form_id,
                    title=pack.title,
                    version=pack.version,
                    status="published",  # bundled packs are ready to use
                    output_targets=",".join(pack.output_targets),
                    schema_json=json.dumps(pack.schema),
                    prompt_json=_build_prompt_json(pack),
                    voice_json=json.dumps(voice) if voice else None,
                )
            )
            added += 1
        if added:
            db.commit()
            logger.info("Seeded %d form(s) from bundled packs.", added)
    except Exception:
        db.rollback()
        logger.warning("Form seeding from packs failed; continuing on filesystem packs.", exc_info=True)
    return added
