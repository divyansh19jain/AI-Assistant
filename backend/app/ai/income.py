"""Income interview engine — turn a conversational income picture into a monthly total.

A caseworker doesn't ask for a single number; they walk through who works, how often
each person is paid, whether it's hourly, and any other income (Social Security,
unemployment, pension, child support, rental, cash help). This module aggregates those
sources into one monthly figure and screens it against the 2026 ODM limits via the
deterministic eligibility tools. It fails soft: a source it can't resolve is reported,
not guessed, so the agent re-asks.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.odm_eligibility import monthly_from_pay, screen_magi_income

# Income kinds we recognize (all counted as gross monthly income for MAGI screening).
INCOME_KINDS = {
    "wages", "self_employment", "social_security", "unemployment",
    "pension", "child_support", "rental", "cash_help", "other",
}


@dataclass
class IncomeSource:
    kind: str = "wages"
    amount: float = 0.0
    frequency: str = "monthly"            # weekly | biweekly | semimonthly | monthly | annual | hourly | ...
    person: str = "applicant"
    before_tax: bool = True
    hours_per_week: float | None = None   # only used when frequency == "hourly"


def _source_monthly(source: IncomeSource) -> dict:
    freq = (source.frequency or "").strip().lower()
    if freq == "hourly":
        if not source.hours_per_week:
            return {"ok": False, "error": "missing_hours"}
        try:
            weekly = float(source.amount or 0) * float(source.hours_per_week)
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_amount"}
        return monthly_from_pay(weekly, "weekly")
    return monthly_from_pay(source.amount, source.frequency)


def aggregate_income(sources: list[IncomeSource]) -> dict:
    """Sum recognized sources into a monthly total; report any that can't be resolved."""
    total = 0.0
    resolved: list[dict] = []
    unresolved: list[dict] = []
    for source in sources:
        monthly = _source_monthly(source)
        if monthly.get("ok"):
            total += monthly["monthly_income"]
            resolved.append({
                "person": source.person,
                "kind": source.kind,
                "monthly": monthly["monthly_income"],
                "before_tax": source.before_tax,
            })
        else:
            unresolved.append({"person": source.person, "kind": source.kind, "error": monthly.get("error")})
    return {"monthly_total": round(total, 2), "resolved": resolved, "unresolved": unresolved}


def screen_income_sources(category: str, household_size: int, sources: list[IncomeSource]) -> dict:
    """Aggregate the household's income and screen it against the 2026 ODM limit.

    If any source couldn't be resolved (e.g. an hourly rate with no hours), the result is
    flagged ``incomplete`` and ``screening_result`` becomes ``"incomplete"`` so the agent
    asks for the missing details instead of presenting a confident screen of a partial total.
    """
    agg = aggregate_income(sources)
    result = {
        **screen_magi_income(category, household_size, agg["monthly_total"]),
        "monthly_total": agg["monthly_total"],
        "resolved": agg["resolved"],
        "unresolved": agg["unresolved"],
    }
    if agg["unresolved"]:
        result["incomplete"] = True
        result["screening_result"] = "incomplete"
        result["plain_language"] = (
            "I can't screen the income yet — I'm missing some details "
            f"({', '.join(u.get('kind', 'income') for u in agg['unresolved'])}). "
            "Let's fill those in first, then I'll check it against the guideline."
        )
    return result
