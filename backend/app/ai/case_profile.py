"""CaseProfile — a case-manager's working memory over the raw answers.

The agent already sees the field-by-field form state. The CaseProfile adds the
*judgement* layer a human caseworker keeps in their head: what is already known (so
they never ask again), what was auto-derived, what was heard with low confidence (so
they read it back), what looks inconsistent (so they gently double-check), and what is
still needed. It is built from the deterministic readiness gate plus answer provenance,
so it stays in sync with completion logic instead of drifting.

🔒 PHI-safe: sensitive values (SSN/DOB/phone) are never rendered into the agent
context — only field keys and labels (the *fact* that something is known/confirmed).
"""

from __future__ import annotations

from typing import Any, Iterable

from app.forms.missing_fields import SKIPPED, is_field_applicable
from app.forms.readiness import _deserialize, _has_value, build_session_readiness
from app.forms.service import get_all_fields_from_schema

# Answers the system derived rather than the person stating them outright.
_INFERRED_SOURCES = {"carry_forward", "autofill", "zip_autofill", "emr", "inference"}


def build_case_profile(form_id: str, schema: dict, answer_rows: Iterable[Any]) -> dict:
    """Classify the current answers into the dimensions a caseworker tracks."""
    rows = list(answer_rows)
    answers = {r.field_key: _deserialize(getattr(r, "value_json", None)) for r in rows}
    sources = {r.field_key: (getattr(r, "source", "") or "") for r in rows}
    readiness = build_session_readiness(form_id, schema, rows)

    fields = get_all_fields_from_schema(schema)
    by_key = {f["field_key"]: f for f in fields}
    applicable = [f for f in fields if is_field_applicable(f, answers, by_key)]

    answered = [
        f["field_key"] for f in applicable
        if _has_value(answers.get(f["field_key"])) and answers.get(f["field_key"]) != SKIPPED
    ]
    skipped = [i["field_key"] for i in readiness["skipped_fields"]]
    inferred = [k for k in answered if sources.get(k) in _INFERRED_SOURCES]
    needs_confirmation = [i["field_key"] for i in readiness["low_confidence_fields"]]
    inconsistent = [
        w["field_key"] for w in readiness["warnings"]
        if w.get("kind") in {"future_date", "implausible_date"}
    ]
    remaining = list(readiness["missing_applicable"])

    referenced = set(answered) | set(skipped) | set(needs_confirmation) | set(inconsistent) | set(remaining)
    return {
        "answered": answered,
        "inferred": inferred,
        "skipped": skipped,
        "needs_confirmation": needs_confirmation,
        "inconsistent": inconsistent,
        "remaining": remaining,
        "do_not_reask": sorted(set(answered) | set(skipped)),
        "labels": {k: by_key.get(k, {}).get("label", k) for k in referenced},
        "ready": readiness["ready"],
    }


def render_case_notes(profile: dict) -> str:
    """Compact, instruction-shaped notes for the agent — field keys/labels only."""
    labels = profile.get("labels", {})

    def names(keys: list[str], limit: int = 12) -> str:
        picked = keys[:limit]
        more = len(keys) - len(picked)
        rendered = ", ".join(labels.get(k, k) for k in picked)
        return rendered + (f", +{more} more" if more > 0 else "")

    lines = ["CASE NOTES (your working memory — use it so you never repeat yourself):"]
    if profile["do_not_reask"]:
        lines.append(f"- ALREADY KNOWN, do not ask again unless the person corrects it: {names(profile['do_not_reask'])}.")
    if profile["inferred"]:
        lines.append(f"- Auto-filled from earlier answers (proceed; confirm only if it seems off): {names(profile['inferred'])}.")
    if profile["needs_confirmation"]:
        lines.append(f"- Heard with LOW confidence — read these back to confirm before moving on: {names(profile['needs_confirmation'])}.")
    if profile["inconsistent"]:
        lines.append(f"- Looks unusual — gently double-check: {names(profile['inconsistent'])}.")
    if profile["remaining"]:
        lines.append(f"- Still needed: {names(profile['remaining'])}.")
    else:
        lines.append("- Nothing left to collect — confirm and offer to review.")
    return "\n".join(lines)
