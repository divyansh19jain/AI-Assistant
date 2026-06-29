"""Scoring for bundled behavioral-health self-report instruments.

The interview engine stores plain form answers. This module is the deterministic
scoring layer used by review and generated summary PDFs. Keeping scoring here,
instead of in prompts, means the AI can sound human while totals remain auditable.

Important: these are screening results, not diagnoses. The review UI should show
them as decision-support summaries for follow-up, safety review, or clinician
interpretation.
"""

from __future__ import annotations

from typing import Any


CLINICAL_BATTERY_FORM_ID = "BH_SELF_REPORT_BATTERY"

FREQ_0_3 = {
    "Not at all": 0,
    "Several days": 1,
    "More than half the days": 2,
    "Nearly every day": 3,
}

FREQ_0_4 = {
    "Not at all": 0,
    "A little bit": 1,
    "Moderately": 2,
    "Quite a bit": 3,
    "Extremely": 4,
}

WHODAS_0_4 = {
    "None": 0,
    "Mild": 1,
    "Moderate": 2,
    "Severe": 3,
    "Extreme or cannot do": 4,
}

DLA_1_5 = {
    "None": 1,
    "Mild": 2,
    "Moderate": 3,
    "Severe": 4,
    "Extreme or cannot do": 5,
}

TAPS_FREQ = {
    "Never": 0,
    "Less than monthly": 1,
    "Monthly": 2,
    "Weekly": 3,
    "Daily or almost daily": 4,
}

AUDIT_C_MAPS = {
    "auditc.q1": {
        "Never": 0,
        "Monthly or less": 1,
        "2 to 4 times a month": 2,
        "2 to 3 times a week": 3,
        "4 or more times a week": 4,
    },
    "auditc.q2": {
        "1 or 2": 0,
        "3 or 4": 1,
        "5 or 6": 2,
        "7 to 9": 3,
        "10 or more": 4,
    },
    "auditc.q3": {
        "Never": 0,
        "Less than monthly": 1,
        "Monthly": 2,
        "Weekly": 3,
        "Daily or almost daily": 4,
    },
}


def score_clinical_battery(form_id: str, answers: dict[str, Any]) -> list[dict[str, Any]]:
    """Return score summaries for any selected/answered clinical instruments."""
    if form_id != CLINICAL_BATTERY_FORM_ID:
        return []

    results = [
        _score_dsm5_level1(answers),
        _score_sum_tool("phq9", "PHQ-9", answers, [f"phq9.q{i}" for i in range(1, 10)], FREQ_0_3, 27, _phq9_label),
        _score_sum_tool("gad7", "GAD-7", answers, [f"gad7.q{i}" for i in range(1, 8)], FREQ_0_3, 21, _gad7_label),
        _score_cssrs(answers),
        _score_audit_c(answers),
        _score_taps(answers),
        _score_dast10(answers),
        _score_sum_tool("pcl5", "PCL-5", answers, [f"pcl5.q{i}" for i in range(1, 21)], FREQ_0_4, 80, _pcl5_label),
        _score_mdq(answers),
        _score_whodas12(answers),
        _score_sum_tool("dla20", "DLA-20 Self-Report Functioning", answers, [f"dla20.q{i}" for i in range(1, 21)], DLA_1_5, 100, _dla20_label),
    ]
    return [r for r in results if r is not None]


def _selected(answers: dict[str, Any], tool_key: str) -> bool:
    return answers.get(f"selected.{tool_key}") is True


def _value_score(value: Any, score_map: dict[str, int]) -> int | None:
    if value is None or value == "__skipped__":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text in score_map:
        return score_map[text]
    # Tolerate UI or voice paths that include the score prefix, e.g. "2 - Moderate".
    if text and text[0].isdigit():
        try:
            return int(text[0])
        except ValueError:
            return None
    return None


def _score_sum_tool(
    tool_key: str,
    title: str,
    answers: dict[str, Any],
    keys: list[str],
    score_map: dict[str, int],
    max_score: int,
    label_fn,
) -> dict[str, Any] | None:
    if not _selected(answers, tool_key):
        return None
    values = [_value_score(answers.get(k), score_map) for k in keys]
    answered = [v for v in values if v is not None]
    status = "complete" if len(answered) == len(keys) else "incomplete"
    total = sum(answered)
    return {
        "tool_key": tool_key,
        "title": title,
        "status": status,
        "answered_items": len(answered),
        "total_items": len(keys),
        "total_score": total,
        "max_score": max_score,
        "interpretation": label_fn(total) if status == "complete" else "Incomplete - answer remaining items to score.",
    }


def _phq9_label(total: int) -> str:
    if total <= 4:
        return "Minimal depressive symptoms."
    if total <= 9:
        return "Mild depressive symptoms."
    if total <= 14:
        return "Moderate depressive symptoms."
    if total <= 19:
        return "Moderately severe depressive symptoms."
    return "Severe depressive symptoms."


def _gad7_label(total: int) -> str:
    if total <= 4:
        return "Minimal anxiety symptoms."
    if total <= 9:
        return "Mild anxiety symptoms."
    if total <= 14:
        return "Moderate anxiety symptoms."
    return "Severe anxiety symptoms."


def _pcl5_label(total: int) -> str:
    if total >= 33:
        return "Elevated PTSD symptom screen; follow-up assessment is commonly recommended."
    if total >= 20:
        return "Moderate PTSD symptom burden; review trauma history and functional impact."
    return "Lower PTSD symptom burden on this screen."


def _dla20_label(total: int) -> str:
    # The self-report pack stores 1-5 functioning ratings across 20 domains.
    # Convert to a 0-100 impairment-style score for easy comparison in review.
    transformed = round(((total - 20) / 80) * 100)
    if transformed < 25:
        label = "Lower reported functioning difficulty."
    elif transformed < 50:
        label = "Mild to moderate reported functioning difficulty."
    elif transformed < 75:
        label = "Moderate to severe reported functioning difficulty."
    else:
        label = "Severe reported functioning difficulty."
    return f"{label} Transformed score: {transformed}/100."


def _score_audit_c(answers: dict[str, Any]) -> dict[str, Any] | None:
    if not _selected(answers, "auditc"):
        return None

    q1_score = _value_score(answers.get("auditc.q1"), AUDIT_C_MAPS["auditc.q1"])
    if q1_score is None:
        return {
            "tool_key": "auditc",
            "title": "AUDIT-C",
            "status": "incomplete",
            "answered_items": 0,
            "total_items": 1,
            "total_score": 0,
            "max_score": 12,
            "interpretation": "Incomplete - answer alcohol frequency to score.",
        }
    if q1_score == 0:
        return {
            "tool_key": "auditc",
            "title": "AUDIT-C",
            "status": "complete",
            "answered_items": 1,
            "total_items": 1,
            "total_score": 0,
            "max_score": 12,
            "interpretation": "Lower alcohol misuse screen; no alcohol use endorsed.",
        }

    scores = [q1_score, _value_score(answers.get("auditc.q2"), AUDIT_C_MAPS["auditc.q2"]), _value_score(answers.get("auditc.q3"), AUDIT_C_MAPS["auditc.q3"])]
    answered = [s for s in scores if s is not None]
    total = sum(answered)
    status = "complete" if len(answered) == 3 else "incomplete"
    if status != "complete":
        interp = "Incomplete - answer remaining AUDIT-C items to score."
    elif total >= 4:
        interp = "Positive alcohol misuse screen using a common adult cutoff of 4 or more."
    elif total >= 3:
        interp = "Borderline/elevated alcohol screen; some settings use 3 or more for women or older adults."
    else:
        interp = "Lower alcohol misuse screen."
    return {
        "tool_key": "auditc",
        "title": "AUDIT-C",
        "status": status,
        "answered_items": len(answered),
        "total_items": 3,
        "total_score": total,
        "max_score": 12,
        "interpretation": interp,
    }


def _score_dast10(answers: dict[str, Any]) -> dict[str, Any] | None:
    if not _selected(answers, "dast10"):
        return None
    q1_value = answers.get("dast10.q1")
    if not isinstance(q1_value, bool):
        return {
            "tool_key": "dast10",
            "title": "DAST-10",
            "status": "incomplete",
            "answered_items": 0,
            "total_items": 1,
            "total_score": 0,
            "max_score": 10,
            "interpretation": "Incomplete - answer initial drug-use screen item to score.",
        }
    if q1_value is False:
        return {
            "tool_key": "dast10",
            "title": "DAST-10",
            "status": "complete",
            "answered_items": 1,
            "total_items": 1,
            "total_score": 0,
            "max_score": 10,
            "interpretation": "No non-medical drug use endorsed on this screen.",
        }

    keys = [f"dast10.q{i}" for i in range(1, 11)]
    values: list[int | None] = []
    for key in keys:
        value = answers.get(key)
        if not isinstance(value, bool):
            values.append(None)
            continue
        if key == "dast10.q3":
            values.append(0 if value else 1)
        else:
            values.append(1 if value else 0)
    answered = [v for v in values if v is not None]
    total = sum(answered)
    if len(answered) != len(keys):
        interp = "Incomplete - answer remaining DAST-10 items to score."
    elif total == 0:
        interp = "No drug-use problems endorsed on this screen."
    elif total <= 2:
        interp = "Low level of drug-use related problems."
    elif total <= 5:
        interp = "Moderate level of drug-use related problems."
    elif total <= 8:
        interp = "Substantial level of drug-use related problems."
    else:
        interp = "Severe level of drug-use related problems."
    return {
        "tool_key": "dast10",
        "title": "DAST-10",
        "status": "complete" if len(answered) == len(keys) else "incomplete",
        "answered_items": len(answered),
        "total_items": len(keys),
        "total_score": total,
        "max_score": 10,
        "interpretation": interp,
    }


def _score_taps(answers: dict[str, Any]) -> dict[str, Any] | None:
    if not _selected(answers, "taps"):
        return None
    keys = ["taps.tobacco", "taps.alcohol", "taps.rx_misuse", "taps.illicit"]
    scores = [_value_score(answers.get(k), TAPS_FREQ) for k in keys]
    answered = [s for s in scores if s is not None]
    max_score = max(answered) if answered else 0
    positives = [key.split(".")[1] for key, score in zip(keys, scores) if score and score > 0]
    if len(answered) != len(keys):
        interp = "Incomplete - answer remaining TAPS screen items to score."
    elif positives:
        interp = f"Positive TAPS screen for: {', '.join(positives)}. Highest frequency score: {max_score}."
    else:
        interp = "No TAPS substance-use domains endorsed in the screening window."
    return {
        "tool_key": "taps",
        "title": "TAPS Screen",
        "status": "complete" if len(answered) == len(keys) else "incomplete",
        "answered_items": len(answered),
        "total_items": len(keys),
        "total_score": max_score,
        "max_score": 4,
        "interpretation": interp,
        "positive_domains": positives,
    }


def _score_cssrs(answers: dict[str, Any]) -> dict[str, Any] | None:
    if not _selected(answers, "cssrs"):
        return None
    keys = ["cssrs.wish_dead", "cssrs.suicidal_thoughts", "cssrs.behavior"]
    if answers.get("cssrs.suicidal_thoughts") is True:
        keys = ["cssrs.wish_dead", "cssrs.suicidal_thoughts", "cssrs.method", "cssrs.intent", "cssrs.plan", "cssrs.behavior"]
    values = [answers.get(k) if isinstance(answers.get(k), bool) else None for k in keys]
    answered = [v for v in values if v is not None]
    if len(answered) != len(keys):
        level = "Incomplete - answer remaining C-SSRS items to score."
        risk = "incomplete"
    elif any(answers.get(k) is True for k in ("cssrs.intent", "cssrs.plan", "cssrs.behavior")):
        risk, level = "high", "High risk flag - urgent safety review is indicated."
    elif answers.get("cssrs.method") is True:
        risk, level = "moderate", "Moderate risk flag - prompt safety follow-up is indicated."
    elif answers.get("cssrs.suicidal_thoughts") is True:
        risk, level = "moderate", "Moderate risk flag - suicidal thoughts endorsed; prompt safety follow-up is indicated."
    elif answers.get("cssrs.wish_dead") is True:
        risk, level = "low", "Low risk flag - passive death wish endorsed; review safety and supports."
    else:
        risk, level = "none", "No suicidal ideation or behavior endorsed on this screen."
    return {
        "tool_key": "cssrs",
        "title": "C-SSRS Self-Report Screener",
        "status": "complete" if len(answered) == len(keys) else "incomplete",
        "answered_items": len(answered),
        "total_items": len(keys),
        "total_score": sum(1 for v in answered if v is True),
        "max_score": 6,
        "risk_level": risk,
        "interpretation": level,
    }


def _score_mdq(answers: dict[str, Any]) -> dict[str, Any] | None:
    if not _selected(answers, "mdq"):
        return None
    symptom_keys = [f"mdq.q{i}" for i in range(1, 14)]
    symptom_values = [answers.get(k) if isinstance(answers.get(k), bool) else None for k in symptom_keys]
    same_period = answers.get("mdq.same_period")
    impairment = answers.get("mdq.impairment")
    answered_count = len([v for v in symptom_values if v is not None])
    yes_count = len([v for v in symptom_values if v is True])
    needs_followups = answered_count == 13 and yes_count >= 2
    complete = answered_count == 13 and (
        not needs_followups or (isinstance(same_period, bool) and impairment not in (None, "__skipped__"))
    )
    total_items = 15 if needs_followups else 13
    scored_answered_items = answered_count
    if needs_followups:
        scored_answered_items += (1 if isinstance(same_period, bool) else 0)
        scored_answered_items += (1 if impairment not in (None, "__skipped__") else 0)
    impairment_positive = str(impairment) in {"Moderate problem", "Serious problem"}
    positive = bool(complete and yes_count >= 7 and same_period is True and impairment_positive)
    return {
        "tool_key": "mdq",
        "title": "Mood Disorder Questionnaire",
        "status": "complete" if complete else "incomplete",
        "answered_items": scored_answered_items,
        "total_items": total_items,
        "total_score": yes_count,
        "max_score": 13,
        "positive_screen": positive,
        "interpretation": (
            "Positive bipolar-spectrum screen pattern; clinical follow-up is recommended."
            if positive else
            "MDQ positive-screen pattern not met; fewer than two symptom items were endorsed." if complete and not needs_followups else
            "Incomplete - answer remaining MDQ items to score." if not complete else
            "MDQ positive-screen pattern not met."
        ),
    }


def _score_whodas12(answers: dict[str, Any]) -> dict[str, Any] | None:
    if not _selected(answers, "whodas12"):
        return None
    keys = [f"whodas12.q{i}" for i in range(1, 13)]
    scores = [_value_score(answers.get(k), WHODAS_0_4) for k in keys]
    answered = [s for s in scores if s is not None]
    total = sum(answered)
    transformed = round((total / 48) * 100) if len(answered) == len(keys) else None
    return {
        "tool_key": "whodas12",
        "title": "WHODAS 2.0 12-item",
        "status": "complete" if len(answered) == len(keys) else "incomplete",
        "answered_items": len(answered),
        "total_items": len(keys),
        "total_score": total,
        "max_score": 48,
        "transformed_score": transformed,
        "interpretation": (
            f"Simple transformed disability score: {transformed}/100."
            if transformed is not None else
            "Incomplete - answer remaining WHODAS items to score."
        ),
    }


def _score_dsm5_level1(answers: dict[str, Any]) -> dict[str, Any] | None:
    if not _selected(answers, "dsm5_level1"):
        return None
    domains = {
        "depression": ["dsm5.q1", "dsm5.q2"],
        "anger": ["dsm5.q3"],
        "mania": ["dsm5.q4", "dsm5.q5"],
        "anxiety": ["dsm5.q6", "dsm5.q7", "dsm5.q8"],
        "somatic": ["dsm5.q9", "dsm5.q10"],
        "suicidal_ideation": ["dsm5.q11"],
        "psychosis": ["dsm5.q12", "dsm5.q13"],
        "sleep": ["dsm5.q14"],
        "memory": ["dsm5.q15"],
        "repetitive_thoughts_behaviors": ["dsm5.q16", "dsm5.q17"],
        "dissociation": ["dsm5.q18"],
        "personality_function": ["dsm5.q19", "dsm5.q20"],
        "substance_use": ["dsm5.q21", "dsm5.q22", "dsm5.q23"],
    }
    domain_scores: dict[str, int | None] = {}
    flags: list[str] = []
    answered = 0
    for domain, keys in domains.items():
        scores = [_value_score(answers.get(k), FREQ_0_4) for k in keys]
        present = [s for s in scores if s is not None]
        answered += len(present)
        domain_score = max(present) if present else None
        domain_scores[domain] = domain_score
        if domain_score is None:
            continue
        if domain == "suicidal_ideation" and domain_score > 0:
            flags.append(domain)
        elif domain_score >= 2:
            flags.append(domain)
    complete = answered == 23
    return {
        "tool_key": "dsm5_level1",
        "title": "DSM-5-TR Level 1 Cross-Cutting",
        "status": "complete" if complete else "incomplete",
        "answered_items": answered,
        "total_items": 23,
        "total_score": sum(s for s in domain_scores.values() if s is not None),
        "max_score": 52,
        "domain_scores": domain_scores,
        "flagged_domains": flags,
        "interpretation": (
            "Flagged domains: " + ", ".join(flags) if complete and flags else
            "No domains crossed the configured screening flag threshold." if complete else
            "Incomplete - answer remaining Level 1 items to score."
        ),
    }
