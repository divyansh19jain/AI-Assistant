"""Deterministic Ohio Medicaid income screening helpers.

This is not an eligibility engine. It is a guarded screening aid for the voice
agent so income-limit answers come from official ODM 2026 chart values instead
of model memory. The county/state eligibility system still makes the final
decision after household, category, deductions, verifications, and program rules
are reviewed.
"""

from __future__ import annotations

from typing import Any

SOURCE_2026_MAGI = (
    "Ohio Medicaid MEPL 194 / 2026 Monthly Financial Eligibility, effective 2026-03-01"
)

CATEGORY_LABELS = {
    "parent_caretaker": "Parents or caretaker relatives, 90% FPL",
    "adult_19_64": "MAGI adults age 19-64, 133% FPL",
    "child_with_insurance": "Children with creditable insurance, 156% FPL",
    "pregnant": "Pregnant women, 200% FPL",
    "child_without_insurance": "Children without creditable insurance, 206% FPL",
}

# Monthly dollar limits from ODM's 2026 chart for children, families, and adults.
MAGI_2026_LIMITS: dict[int, dict[str, int]] = {
    1: {"parent_caretaker": 1197, "adult_19_64": 1769, "child_with_insurance": 2075, "pregnant": 2660, "child_without_insurance": 2740},
    2: {"parent_caretaker": 1623, "adult_19_64": 2399, "child_with_insurance": 2814, "pregnant": 3607, "child_without_insurance": 3715},
    3: {"parent_caretaker": 2049, "adult_19_64": 3028, "child_with_insurance": 3552, "pregnant": 4554, "child_without_insurance": 4690},
    4: {"parent_caretaker": 2475, "adult_19_64": 3658, "child_with_insurance": 4290, "pregnant": 5500, "child_without_insurance": 5665},
    5: {"parent_caretaker": 2901, "adult_19_64": 4288, "child_with_insurance": 5029, "pregnant": 6447, "child_without_insurance": 6641},
    6: {"parent_caretaker": 3327, "adult_19_64": 4917, "child_with_insurance": 5767, "pregnant": 7394, "child_without_insurance": 7616},
    7: {"parent_caretaker": 3753, "adult_19_64": 5547, "child_with_insurance": 6506, "pregnant": 8340, "child_without_insurance": 8591},
    8: {"parent_caretaker": 4179, "adult_19_64": 6176, "child_with_insurance": 7244, "pregnant": 9287, "child_without_insurance": 9566},
    9: {"parent_caretaker": 4605, "adult_19_64": 6806, "child_with_insurance": 7982, "pregnant": 10234, "child_without_insurance": 10541},
    10: {"parent_caretaker": 5031, "adult_19_64": 7435, "child_with_insurance": 8721, "pregnant": 11180, "child_without_insurance": 11516},
    11: {"parent_caretaker": 5457, "adult_19_64": 8065, "child_with_insurance": 9459, "pregnant": 12127, "child_without_insurance": 12491},
    12: {"parent_caretaker": 5883, "adult_19_64": 8694, "child_with_insurance": 10198, "pregnant": 13074, "child_without_insurance": 13466},
}


def screen_magi_income(category: str, household_size: int, monthly_income: float) -> dict[str, Any]:
    """Compare monthly income to an ODM 2026 MAGI screening limit.

    Returns a model-friendly dict with a plain-language result and explicit caveats.
    Unknown categories or unsupported household sizes fail closed with instructions
    rather than guessing.
    """
    category = (category or "").strip().lower()
    try:
        household_size = int(household_size)
        monthly_income = float(monthly_income if monthly_income is not None else 0)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": "invalid_number",
            "message": "I need a whole-number household size and a dollar amount to screen income.",
        }
    if category not in CATEGORY_LABELS:
        return {
            "ok": False,
            "error": "unknown_category",
            "supported_categories": CATEGORY_LABELS,
        }
    if household_size not in MAGI_2026_LIMITS:
        return {
            "ok": False,
            "error": "unsupported_household_size",
            "supported_household_sizes": sorted(MAGI_2026_LIMITS),
        }

    threshold = MAGI_2026_LIMITS[household_size][category]
    difference = round(float(monthly_income) - threshold, 2)
    within = difference <= 0
    if within:
        plain = (
            f"For screening only, ${monthly_income:,.2f} per month is at or below "
            f"the 2026 ODM monthly guide of ${threshold:,.0f} for {CATEGORY_LABELS[category]} "
            f"with household size {household_size}."
        )
    else:
        plain = (
            f"For screening only, ${monthly_income:,.2f} per month is ${difference:,.2f} "
            f"above the 2026 ODM monthly guide of ${threshold:,.0f} for "
            f"{CATEGORY_LABELS[category]} with household size {household_size}."
        )

    return {
        "ok": True,
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "household_size": household_size,
        "monthly_income": round(float(monthly_income), 2),
        "monthly_limit": threshold,
        "difference": difference,
        "screening_result": "at_or_below_limit" if within else "above_limit",
        "plain_language": plain,
        "caveat": (
            "This is not a final eligibility decision. Other categories, deductions, "
            "medical bills, household rules, verification, and state/county review can matter."
        ),
        "source": SOURCE_2026_MAGI,
    }


# Convert a pay amount at a stated frequency to an approximate MONTHLY figure, the way
# a caseworker does the math (52 weeks / 26 biweekly periods per year ÷ 12 months).
PAY_FREQUENCY_FACTORS: dict[str, float] = {
    "weekly": 52 / 12,
    "every_two_weeks": 26 / 12,
    "biweekly": 26 / 12,
    "twice_a_month": 2.0,
    "semimonthly": 2.0,
    "monthly": 1.0,
    "yearly": 1 / 12,
    "annual": 1 / 12,
}

# Natural-language frequency phrasings the voice agent may hear, mapped to the keys above.
_FREQUENCY_ALIASES: dict[str, str] = {
    "week": "weekly", "wk": "weekly", "per_week": "weekly", "a_week": "weekly",
    "two_weeks": "every_two_weeks", "every_other_week": "every_two_weeks",
    "bi_weekly": "biweekly", "fortnightly": "every_two_weeks", "every_2_weeks": "every_two_weeks",
    "twice_a_month": "twice_a_month", "semi_monthly": "semimonthly", "twice_monthly": "twice_a_month",
    "month": "monthly", "per_month": "monthly", "a_month": "monthly",
    "year": "yearly", "per_year": "yearly", "a_year": "yearly", "annually": "annual",
}


def monthly_from_pay(amount: Any, frequency: str) -> dict[str, Any]:
    """Normalize a per-paycheck amount + how often it's paid into a monthly amount.

    Fails closed on a bad number or an unrecognized frequency so the agent re-asks
    instead of guessing. ``monthly_income`` in the result feeds ``screen_magi_income``.
    """
    try:
        amount = float(amount if amount is not None else 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_amount"}
    raw = (frequency or "").strip().lower().replace("-", " ")
    key = raw.replace(" ", "_")
    if key not in PAY_FREQUENCY_FACTORS:
        key = _FREQUENCY_ALIASES.get(key, "")
    if key not in PAY_FREQUENCY_FACTORS:
        return {"ok": False, "error": "unknown_frequency", "supported_frequencies": sorted(PAY_FREQUENCY_FACTORS)}
    monthly = round(amount * PAY_FREQUENCY_FACTORS[key], 2)
    return {"ok": True, "amount": round(amount, 2), "frequency": key, "monthly_income": monthly}
