"""
Skills — reusable AI capabilities a form's assistant can use.

A **skill** is a small, typed capability the assistant can invoke while helping a
user: look up a ZIP code, search the form's knowledgebase, define a common term.
The *catalog* of capabilities is **code** (:data:`BUILTINS`); which skills a given
form uses is **data** (the ``form_skills`` table). This mirrors the EMR-adapter
pattern: a stable interface (``SkillSpec.run``) with swappable implementations.

Invocation goes through :func:`run_skill`, which is defensive — a failing skill
returns ``{"error": ...}`` rather than raising, so a bad capability can never break
the answer flow.

🔒 Each skill declares ``needs_phi``; callers should pass only the data a skill needs.
The built-ins here are PHI-light (a ZIP, a term, a field-level query).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillSpec:
    key: str
    name: str
    description: str
    run: Callable[[dict], dict]
    needs_network: bool = False
    needs_phi: bool = False


# ── built-in capabilities ─────────────────────────────────────────────────────
def _zip_lookup(params: dict) -> dict:
    """{"zip": "43215"} -> {"city","state","county"} (needs ZIPCODE_API_KEY)."""
    from app.services.zipcode import lookup_zip

    result = lookup_zip(str(params.get("zip", "")))
    return result or {"error": "ZIP lookup unavailable"}


def _kb_lookup(params: dict) -> dict:
    """{"form_id","query","k"?} -> {"snippets": [...]} from the form's knowledgebase."""
    from app.ai.kb import retrieve
    from app.db.base import SessionLocal

    form_id = params.get("form_id")
    query = str(params.get("query", ""))
    k = int(params.get("k", 3))
    if not form_id or not query:
        return {"snippets": []}
    db = SessionLocal()
    try:
        return {"snippets": retrieve(db, form_id, query, k=k)}
    finally:
        db.close()


_GLOSSARY = {
    "income": "Money you get from work, self-employment, or benefits, before taxes.",
    "household": "You plus the people you live with and claim on taxes (spouse, dependents).",
    "dependent": "Someone you support and claim on your tax return, like a child.",
    "gross": "The amount before taxes or deductions are taken out.",
    "gross income": "Money before taxes, insurance, retirement, or other deductions are taken out.",
    "self-employment": "Work someone does for themselves, such as business, freelance, gig, farming, or contract work.",
    "fpl": "Federal Poverty Level, a yearly federal guideline used in many benefit income rules.",
    "magi": "Modified Adjusted Gross Income, a tax-based income method used for many Medicaid categories.",
    "abd": "Aged, Blind, or Disabled Medicaid, a path for people age 65 or older, legally blind, or disabled.",
    "long-term care": "Help with daily needs at home, in the community, or in a nursing facility.",
    "retroactive": "A look-back period that may let Medicaid review medical bills from recent months.",
    "eligible immigration status": "An immigration status category that may allow someone to qualify for coverage.",
    "mpap": "Medicare Premium Assistance Programs, which may help some Medicare members pay Medicare costs.",
    "premium": "The amount you pay each month for health coverage.",
    "deductible": "What you pay for care before your insurance starts to pay.",
    "ssn": "Your nine-digit Social Security number.",
}


def _glossary(params: dict) -> dict:
    """{"term": "income"} -> {"definition": ...} for a common form term."""
    term = str(params.get("term", "")).strip().lower()
    return {"definition": _GLOSSARY.get(term, "")}


def _odm_income_screen(params: dict) -> dict:
    """{"category","household_size","monthly_income"} -> ODM 2026 screening result."""
    from app.ai.odm_eligibility import screen_magi_income

    return screen_magi_income(
        category=str(params.get("category", "")),
        household_size=int(params.get("household_size", 0) or 0),
        monthly_income=float(params.get("monthly_income", 0) or 0),
    )


BUILTINS: dict[str, SkillSpec] = {
    "zip_lookup": SkillSpec(
        "zip_lookup", "ZIP lookup", "Look up city / state / county for a ZIP code.",
        _zip_lookup, needs_network=True,
    ),
    "kb_lookup": SkillSpec(
        "kb_lookup", "Knowledgebase search", "Find relevant guidance snippets from the form's KB.",
        _kb_lookup,
    ),
    "glossary": SkillSpec(
        "glossary", "Glossary", "Define a common form/insurance term in plain language.",
        _glossary,
    ),
    "odm_income_screen": SkillSpec(
        "odm_income_screen",
        "ODM income screening",
        "Compare monthly income to official Ohio Medicaid 2026 MAGI screening limits.",
        _odm_income_screen,
    ),
}


def list_builtins() -> list[dict]:
    """The skill catalog for the builder (metadata only)."""
    return [
        {"key": s.key, "name": s.name, "description": s.description, "needs_network": s.needs_network}
        for s in BUILTINS.values()
    ]


def run_skill(key: str, params: dict) -> dict:
    """Invoke a built-in skill by key. Returns ``{"error": ...}`` on unknown/failed skill."""
    spec = BUILTINS.get(key)
    if spec is None:
        return {"error": f"unknown skill {key!r}"}
    try:
        return spec.run(params or {})
    except Exception:
        logger.warning("Skill %s failed.", key, exc_info=True)
        return {"error": f"skill {key} failed"}


def get_form_skill_keys(db, form_id: str) -> list[str]:
    """The enabled skill keys attached to a form (empty list if none)."""
    from app.db.models import FormSkill

    try:
        rows = db.query(FormSkill).filter(FormSkill.form_id == form_id, FormSkill.enabled.is_(True)).all()
        return [r.skill_key for r in rows if r.skill_key in BUILTINS]
    except Exception:
        return []
