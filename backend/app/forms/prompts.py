"""
Per-form prompt packs + voice config.

The builder lets each form carry its own **AI persona** (system prompt), **per-field
question/help overrides**, and **voice settings**. Like the schema cache
(:mod:`app.forms.cache`), these are held in a process-local cache so the AI helpers
can look them up by ``form_id`` synchronously, without a DB session — the helpers
are called deep in the answer flow where threading a ``Session`` would be awkward.

Resolution order (mirrors the schema cache):
1. the DB-backed cache (populated from ``forms.prompt_json`` / ``forms.voice_json``
   at startup and on builder writes);
2. the bundled **pack files** (``prompts/system.md``, ``prompts/field_overrides.json``,
   and the ``voice:`` block of ``workflow.yaml``) as a fallback.

Everything degrades to "no customization" (``None`` / ``{}``) so the default global
persona and rule-based fallbacks are used when a form has no prompt pack — keeping
existing behavior and tests unchanged.

🔒 No PHI: prompt packs + voice config are static, form-level strings only.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# form_id -> {"system": str | None, "field_overrides": {field_key: {"question"?, "help"?}}}
_PROMPTS: dict[str, dict] = {}
# form_id -> {"voice_id": str|None, "persona": str|None, "stt_vocabulary": str|None}
_VOICE: dict[str, dict] = {}

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _clean_system(text: str | None) -> str | None:
    """Strip HTML-comment authoring notes from a system.md persona."""
    if not text:
        return None
    cleaned = _HTML_COMMENT.sub("", text).strip()
    return cleaned or None


def _overrides_map(field_overrides) -> dict:
    """Normalize a field_overrides blob to a flat ``{field_key: {...}}`` map.

    Tolerates both the canonical flat shape and the pack-file shape that wraps the
    map under an ``"overrides"`` key (alongside ``//`` comment keys).
    """
    if not isinstance(field_overrides, dict):
        return {}
    if isinstance(field_overrides.get("overrides"), dict):
        return field_overrides["overrides"]
    # Flat map: drop any "//"-prefixed comment keys defensively.
    return {k: v for k, v in field_overrides.items() if not str(k).startswith("//")}


def set_prompt_pack(form_id: str, prompt: dict | None, voice: dict | None) -> None:
    """Insert/replace a form's prompt pack + voice config in the cache (after a write)."""
    _PROMPTS[form_id] = {
        "system": _clean_system((prompt or {}).get("system")),
        "field_overrides": _overrides_map((prompt or {}).get("field_overrides")),
    }
    _VOICE[form_id] = voice or {}


def drop(form_id: str) -> None:
    _PROMPTS.pop(form_id, None)
    _VOICE.pop(form_id, None)


def clear() -> None:
    _PROMPTS.clear()
    _VOICE.clear()


def _ensure_loaded(form_id: str) -> None:
    """Populate the cache for ``form_id`` from the bundled pack files if absent.

    Best-effort: any failure leaves the form uncustomized (defaults apply).
    """
    if form_id in _PROMPTS:
        return
    try:
        from app.forms import registry

        pack = registry.get_pack(form_id)
        system_file = pack.prompts_dir / "system.md"
        overrides_file = pack.prompts_dir / "field_overrides.json"
        system = _clean_system(system_file.read_text(encoding="utf-8")) if system_file.is_file() else None
        overrides = (
            _overrides_map(json.loads(overrides_file.read_text(encoding="utf-8")))
            if overrides_file.is_file()
            else {}
        )
        _PROMPTS[form_id] = {"system": system, "field_overrides": overrides}
        _VOICE[form_id] = (pack.config.get("voice") if isinstance(pack.config, dict) else {}) or {}
    except Exception:
        # Unknown form / unreadable pack: cache "no customization" so we don't retry.
        _PROMPTS[form_id] = {"system": None, "field_overrides": {}}
        _VOICE[form_id] = {}


def get_system_persona(form_id: str | None) -> str | None:
    """The form's AI persona (system prompt), or ``None`` to use the global default."""
    if not form_id:
        return None
    _ensure_loaded(form_id)
    return _PROMPTS.get(form_id, {}).get("system")


def get_field_override(form_id: str | None, field_key: str) -> dict:
    """Per-field ``{"question"?, "help"?}`` overrides for a form (``{}`` if none)."""
    if not form_id:
        return {}
    _ensure_loaded(form_id)
    return _PROMPTS.get(form_id, {}).get("field_overrides", {}).get(field_key, {}) or {}


def get_voice_config(form_id: str | None) -> dict:
    """The form's voice config (``voice_id`` / ``persona`` / ``stt_vocabulary``)."""
    if not form_id:
        return {}
    _ensure_loaded(form_id)
    return _VOICE.get(form_id, {})


def refresh(db, form_id: str) -> None:
    """Reload one form's prompt pack + voice from the DB into the cache (best-effort)."""
    from app.db.models import Form

    try:
        row = db.query(Form).filter(Form.form_id == form_id).first()
        if row is None:
            return
        prompt = json.loads(row.prompt_json) if row.prompt_json else {}
        voice = json.loads(row.voice_json) if row.voice_json else {}
        set_prompt_pack(form_id, prompt, voice)
    except Exception:
        logger.warning("Failed to refresh prompt pack for %s.", form_id, exc_info=True)


def refresh_all(db) -> int:
    """Load all forms' prompt packs + voice from the DB. Returns the count loaded."""
    from app.db.models import Form

    count = 0
    try:
        for row in db.query(Form).all():
            try:
                prompt = json.loads(row.prompt_json) if row.prompt_json else {}
                voice = json.loads(row.voice_json) if row.voice_json else {}
                set_prompt_pack(row.form_id, prompt, voice)
                count += 1
            except Exception:
                logger.warning("Skipping unparseable prompt/voice JSON for form %s.", row.form_id)
    except Exception:
        logger.warning("Could not load prompt packs; using pack-file fallback.", exc_info=True)
    return count
