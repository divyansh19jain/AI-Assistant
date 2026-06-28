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

import hashlib
import json
import logging
import re

from app.forms import registry

logger = logging.getLogger(__name__)


def _build_prompt_json(pack) -> str | None:
    """Assemble a pack's field overrides into ``prompt_json`` (or None).

    The bundled system persona (``prompts/system.md``) is intentionally NOT baked into
    the DB here: it stays authoritative in the pack file so prompt improvements ship on
    redeploy without a manual DB edit (otherwise ``db_system or pack_system`` in
    ``app.forms.prompts`` would pin an old seeded persona forever). Admin edits made in
    the builder still write ``system`` into ``prompt_json`` and take precedence.
    """
    overrides_file = pack.prompts_dir / "field_overrides.json"
    overrides: dict = {}
    if overrides_file.is_file():
        try:
            overrides = json.loads(overrides_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Pack %s has unparseable field_overrides.json; ignoring.", pack.form_id)
    if not overrides:
        return None
    return json.dumps({"field_overrides": overrides})


def _build_workflow_json(pack) -> str | None:
    """Persist a pack's completion-workflow config (``workflow.yaml``) into the form's
    ``workflow_json`` so bundled task config and ``approval`` (incl. ``require_signature``)
    survive seeding. Returns None when the pack defines no custom workflow (defaults
    apply via :func:`app.workflows.engine.get_workflow_def`).
    """
    cfg = pack.config if isinstance(pack.config, dict) else {}
    wf = cfg.get("workflow") if isinstance(cfg.get("workflow"), dict) else {}
    tasks = wf.get("tasks") if isinstance(wf.get("tasks"), list) else (
        cfg.get("tasks") if isinstance(cfg.get("tasks"), list) else None
    )
    approval = wf.get("approval") if isinstance(wf.get("approval"), dict) else (
        cfg.get("approval") if isinstance(cfg.get("approval"), dict) else None
    )
    if tasks is None and approval is None:
        return None
    from app.workflows.engine import _default_tasks

    return json.dumps({
        "tasks": tasks if tasks is not None else _default_tasks(pack.output_targets),
        "approval": approval if approval is not None else {"required": True},
    })


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
                    workflow_json=_build_workflow_json(pack),
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


def _doc_key_for_path(path) -> str:
    """Stable key for a bundled KB source file.

    Admin-created KB documents use title slugs. Bundled documents use the file stem
    so redeploying an updated pack updates the same row instead of creating dupes.
    """
    return re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")[:120] or "doc"


def _title_from_text(path, text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()[:256] or path.stem
    return path.stem.replace("-", " ").replace("_", " ").title()[:256]


def _iter_bundled_kb_files(pack):
    kb_cfg = pack.config.get("knowledgebase") if isinstance(pack.config, dict) else {}
    if isinstance(kb_cfg, dict) and kb_cfg.get("enabled") is False:
        return []

    root = pack.knowledgebase_dir
    if not root.is_dir():
        return []

    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.name.upper() == "SOURCES.MD":
            continue
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        files.append(path)
    return files


def seed_kb_from_packs(db) -> int:
    """Seed bundled per-form KB documents and embeddings on startup.

    This makes committed ``knowledgebase/*.md`` files available in every fresh
    deployment without a manual admin upload. It is idempotent:
    - missing bundled docs are inserted and embedded;
    - changed bundled docs are re-embedded;
    - admin-created docs with different ``source`` values are left alone.
    """
    from app.ai import kb
    from app.db.models import Form, KbDocument

    changed = 0
    try:
        known_forms = {row.form_id for row in db.query(Form.form_id).all()}
        for pack in registry.list_packs(active_only=False):
            if pack.form_id not in known_forms:
                continue
            for path in _iter_bundled_kb_files(pack):
                text = path.read_text(encoding="utf-8").strip()
                if not text:
                    continue
                rel = path.relative_to(pack.directory).as_posix()
                source = f"bundled:{pack.form_id}/{rel}"
                doc_key = _doc_key_for_path(path)
                checksum = hashlib.md5(text.encode()).hexdigest()
                doc = (
                    db.query(KbDocument)
                    .filter(KbDocument.form_id == pack.form_id, KbDocument.doc_key == doc_key)
                    .first()
                )
                if doc is not None and doc.source != source:
                    # Same key but not our bundled row. Preserve the admin's document.
                    continue
                if doc is None:
                    doc = KbDocument(
                        form_id=pack.form_id,
                        doc_key=doc_key,
                        title=_title_from_text(path, text),
                        source=source,
                        mime="text/markdown" if path.suffix.lower() == ".md" else "text/plain",
                        text=text,
                        status="pending",
                        checksum=checksum,
                    )
                    db.add(doc)
                    db.commit()
                    db.refresh(doc)
                elif doc.checksum == checksum and doc.status == "embedded":
                    continue
                else:
                    doc.title = _title_from_text(path, text)
                    doc.text = text
                    doc.mime = "text/markdown" if path.suffix.lower() == ".md" else "text/plain"
                    doc.checksum = checksum
                    doc.status = "pending"
                    db.commit()
                    db.refresh(doc)
                kb.ingest_document(db, doc)
                changed += 1
        if changed:
            logger.info("Seeded or refreshed %d bundled KB document(s).", changed)
    except Exception:
        db.rollback()
        logger.warning("Bundled KB seeding failed; continuing without default KB refresh.", exc_info=True)
    return changed
