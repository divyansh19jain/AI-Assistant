"""
Form-pack registry — the multi-form platform's loader.

A **form pack** is a self-contained directory under ``app/forms/packs/<FORM_ID>/``
that carries everything the app needs to drive one form. Following the agreed
"fold-in" layout, a pack is:

    <FORM_ID>/
      form.schema.json    # MANDATORY — fields + identity (+ optional "prefill" block)
      pdf.mapping.json     # AcroForm widget mapping
      prompts/             # per-form AI persona + field overrides (Phase 2)
      knowledgebase/       # PHI-free RAG source docs (Phase 3)
      workflow.yaml        # OPTIONAL — pack config: output targets, voice, KB on/off,
                           #   approval, and the web-submission recipe (Phase 5)

``form.schema.json`` is the only required file; ``workflow.yaml`` is optional config
(sensible defaults are used when it is absent — e.g. ``output_targets: ["pdf"]``).

This module is the **single seam** the rest of the codebase uses to go from a
``form_id`` string to that form's assets. It replaces the old hardcoded
``SCHEMA_PATH``/single-form guard in ``app/forms/service.py``. Adding a new form is
therefore dropping in a new pack directory — **no core code changes**.

Storage is abstracted (see ``app/forms/storage.py``): packs come from the local
filesystem by default (dev/tests/CI stay offline) or from S3 in production. This
module consumes that store, so it does not care where packs physically live.

There is **no PHI here**: packs contain only static, form-level definitions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Root directory that holds every bundled form pack. The storage layer may point
# elsewhere (an env-configured dir or an S3 mirror), but this is the default home
# for packs that ship inside the backend package.
PACKS_DIR = Path(__file__).parent / "packs"

# The single mandatory file that marks a directory as a form pack.
SCHEMA_FILENAME = "form.schema.json"
# Optional per-pack config / completion recipe.
WORKFLOW_FILENAME = "workflow.yaml"


class UnknownFormError(ValueError):
    """Raised when a ``form_id`` does not resolve to a discoverable form pack."""


def _read_workflow_config(directory: Path) -> dict:
    """Parse an optional ``workflow.yaml`` into a config dict (``{}`` if absent).

    PyYAML is imported lazily so the dependency is only required when a pack
    actually ships a ``workflow.yaml``; a missing parser or malformed file degrades
    to ``{}`` (defaults apply) with a logged warning rather than crashing boot.
    """
    wf = directory / WORKFLOW_FILENAME
    if not wf.is_file():
        return {}
    try:
        import yaml  # lazy: only needed when a pack uses workflow.yaml
    except ImportError:
        logger.warning("PyYAML not installed; ignoring %s (using defaults).", wf)
        return {}
    try:
        return yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.warning("Failed to parse %s; using defaults.", wf, exc_info=True)
        return {}


@dataclass(frozen=True)
class FormPack:
    """A discovered form pack: its id, directory, parsed schema, and config.

    The schema is parsed once at discovery and cached here (returned by reference —
    callers iterate it, they must not mutate it). ``config`` is the parsed
    ``workflow.yaml`` (or ``{}``). Metadata accessors prefer config, then fall back
    to the schema's own identity fields, then to safe defaults.
    """

    form_id: str
    directory: Path
    schema: dict
    config: dict = field(default_factory=dict)

    # ── metadata (config wins, then schema identity, then default) ──────────
    @property
    def title(self) -> str:
        return self.config.get("title") or self.schema.get("form_title") or self.form_id

    @property
    def version(self) -> str:
        return str(self.config.get("version") or self.schema.get("version") or "0")

    @property
    def output_targets(self) -> list[str]:
        return list(self.config.get("output_targets", ["pdf"]))

    @property
    def active(self) -> bool:
        # A pack present on disk is active unless its config explicitly opts out.
        return bool(self.config.get("active", True))

    @property
    def prefill_map(self) -> dict:
        """Declarative EMR->field prefill block (folded into the schema). ``{}`` if absent."""
        return self.schema.get("prefill", {}) or {}

    # ── pack-relative path helpers ──────────────────────────────────────────
    def _rel(self, value: str | None, default: str) -> Path:
        return self.directory / (value or default)

    @property
    def schema_path(self) -> Path:
        return self.directory / SCHEMA_FILENAME

    @property
    def pdf_mapping_path(self) -> Path:
        pdf_cfg = (self.config.get("pdf") or {})
        return self._rel(pdf_cfg.get("mapping"), "pdf.mapping.json")

    @property
    def workflow_path(self) -> Path:
        return self.directory / WORKFLOW_FILENAME

    @property
    def prompts_dir(self) -> Path:
        return self.directory / "prompts"

    @property
    def knowledgebase_dir(self) -> Path:
        kb = self.config.get("knowledgebase") or {}
        return self._rel(kb.get("dir"), "knowledgebase")


def discover_packs(packs_dir: Path | None = None) -> dict[str, FormPack]:
    """Scan ``packs_dir`` (default :data:`PACKS_DIR`) and return ``{form_id: FormPack}``.

    A subdirectory is a pack iff it contains a readable ``form.schema.json`` with a
    ``form_id``. Malformed packs are skipped with a logged warning (no PHI) rather
    than crashing startup — one bad pack must not take the whole app down.

    Not cached: pass an explicit ``packs_dir`` (e.g. a tmp dir in tests) to discover
    an isolated set of packs. The cached, default-directory view is :func:`_cached`.
    """
    root = packs_dir or PACKS_DIR
    packs: dict[str, FormPack] = {}
    if not root.is_dir():
        logger.warning("Form-pack directory not found: %s", root)
        return packs

    for child in sorted(root.iterdir()):
        schema_file = child / SCHEMA_FILENAME
        if not (child.is_dir() and schema_file.is_file()):
            continue
        try:
            schema = json.loads(schema_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping malformed form pack at %s (%s)", child, exc)
            continue
        form_id = schema.get("form_id")
        if not form_id:
            logger.warning("Skipping form pack at %s: schema has no form_id", child)
            continue
        config = _read_workflow_config(child)
        packs[form_id] = FormPack(form_id=form_id, directory=child, schema=schema, config=config)

    logger.debug("Discovered %d form pack(s): %s", len(packs), ", ".join(packs) or "(none)")
    return packs


@lru_cache(maxsize=1)
def _cached() -> dict[str, FormPack]:
    """Cached discovery over the default :data:`PACKS_DIR` (process-lifetime)."""
    return discover_packs()


def reset_cache() -> None:
    """Clear the discovery cache. For tests that mutate packs on disk."""
    _cached.cache_clear()


def get_pack(form_id: str) -> FormPack:
    """Return the :class:`FormPack` for ``form_id`` or raise :class:`UnknownFormError`."""
    pack = _cached().get(form_id)
    if pack is None:
        known = ", ".join(sorted(_cached())) or "(none)"
        raise UnknownFormError(f"Unknown form_id {form_id!r}. Known forms: {known}")
    return pack


def list_packs(active_only: bool = True) -> list[FormPack]:
    """All discovered packs (optionally only active ones), sorted by ``form_id``."""
    packs = sorted(_cached().values(), key=lambda p: p.form_id)
    return [p for p in packs if p.active] if active_only else packs


def list_form_metadata(active_only: bool = True) -> list[dict]:
    """Lightweight metadata for the ``GET /api/forms`` picker and DB seeding."""
    return [
        {
            "form_id": p.form_id,
            "title": p.title,
            "version": p.version,
            "output_targets": p.output_targets,
            "active": p.active,
        }
        for p in list_packs(active_only=active_only)
    ]


def load_schema(form_id: str) -> dict:
    """Return a form's parsed field schema (cached on the pack; do not mutate)."""
    return get_pack(form_id).schema


def load_prefill_map(form_id: str) -> dict:
    """Return a form's declarative EMR->field prefill block (``{}`` if none)."""
    return get_pack(form_id).prefill_map


def pdf_mapping_path(form_id: str) -> Path:
    """Absolute path to a form's AcroForm PDF mapping. Consumed by ``app/pdf/pdf_service.py``."""
    return get_pack(form_id).pdf_mapping_path
