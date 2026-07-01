"""Caseworker-style pre-approval review.

Before a person approves, a good caseworker doesn't just check "is it complete?" — they
glance for what's missing, what was heard with low confidence, what looks off, what was
auto-filled or skipped, and which documents the county will likely ask for. This builds
that view by reusing the CaseProfile (so it stays in sync with the readiness gate) and
adding a documents-likely-needed list derived from the answers.

🔒 PHI-safe: returns field keys + labels and document *names*, never sensitive values.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.ai.case_profile import build_case_profile
from app.forms.readiness import _deserialize, _has_value


def documents_likely_needed(answers: dict[str, Any]) -> list[dict]:
    """Best-effort list of documents the county commonly asks for, from the answers.

    Conservative and additive — only suggests a document when a triggering answer is
    actually present, and never blocks anything (these are reminders, not requirements).
    """
    docs: list[dict] = [{"document": "Photo ID", "why": "to confirm identity"}]

    employment = str(answers.get("income.has_employment") or "").lower()
    if employment == "employed":
        docs.append({"document": "Recent pay stubs", "why": "to verify wages"})
    elif employment == "self_employed":
        docs.append({"document": "Self-employment records", "why": "to verify self-employment income"})

    persons = sorted({
        k.split(".")[0] for k in answers
        if k.split(".")[0].startswith("person") and k.split(".")[0][6:].isdigit()
    }) or ["person1", "person2"]

    if any(answers.get(f"{p}.us_citizen_or_national") is False for p in persons):
        docs.append({"document": "Immigration documents", "why": "to verify immigration status"})

    if any(answers.get(f"{p}.medical_bills_last_3_months") is True for p in persons):
        docs.append({"document": "Recent medical bills (last 3 months)", "why": "to consider retroactive coverage"})

    if any(key.endswith(".ssn") and _has_value(value) for key, value in answers.items()):
        docs.append({"document": "Social Security card", "why": "to confirm the Social Security number"})

    return docs


def build_caseworker_review(form_id: str, schema: dict, answer_rows: Iterable[Any]) -> dict:
    """Combine the CaseProfile, completion summary, and likely documents into one view."""
    rows = list(answer_rows)
    profile = build_case_profile(form_id, schema, rows)
    answers = {r.field_key: _deserialize(getattr(r, "value_json", None)) for r in rows}
    labels = profile["labels"]

    def listed(keys: list[str]) -> list[dict]:
        return [{"field_key": k, "label": labels.get(k, k)} for k in keys]

    return {
        "ready": profile["ready"],
        "summary": {
            "answered": len(profile["answered"]),
            "inferred": len(profile["inferred"]),
            "skipped": len(profile["skipped"]),
            "needs_confirmation": len(profile["needs_confirmation"]),
            "inconsistent": len(profile["inconsistent"]),
            "remaining": len(profile["remaining"]),
        },
        "remaining": listed(profile["remaining"]),
        "needs_confirmation": listed(profile["needs_confirmation"]),
        "inconsistent": listed(profile["inconsistent"]),
        "inferred": listed(profile["inferred"]),
        "skipped": listed(profile["skipped"]),
        "documents_likely_needed": documents_likely_needed(answers),
    }
