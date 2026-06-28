"""Field-level validation for form answers."""

import re
from datetime import datetime
from typing import Any


class ValidationError(Exception):
    pass


def validate_answer(field: dict, value: Any) -> Any:
    """
    Validate and normalize a value against a field schema.
    Returns the normalized value or raises ValidationError.
    """
    field_type = field.get("type", "text")
    rule = field.get("validation_rule") or {}

    # Normalize booleans
    if field_type == "boolean":
        return _parse_boolean(value)

    # Normalize dates
    if field_type == "date":
        return _parse_date(value)

    # Normalize phone
    if field_type == "phone":
        return _parse_phone(value)

    # Normalize SSN
    if field_type == "ssn":
        return _parse_ssn(value)

    # Normalize number
    if field_type == "number":
        return _parse_number(value, rule)

    # Text / email / select
    value = str(value).strip() if value is not None else ""
    if field_type in {"text", "textarea", "email", "select"} and _looks_like_non_answer_text(value):
        label = field.get("label", "this field")
        raise ValidationError(
            f"That sounds like an instruction or question, not an answer for {label}. Please give the actual value."
        )

    # Medicaid PDF fields often store state as a two-letter code, but callers are
    # humans using voice. Accept "Ohio" and normalize to "OH" instead of asking
    # the user to know the form's internal abbreviation requirement.
    if _looks_like_state_field(field):
        value = normalize_us_state(value) or value.upper()

    if rule.get("min_length") and len(value) < rule["min_length"]:
        raise ValidationError(f"Must be at least {rule['min_length']} characters.")

    if rule.get("max_length") and len(value) > rule["max_length"]:
        raise ValidationError(f"Must be at most {rule['max_length']} characters.")

    if rule.get("pattern"):
        if not re.match(rule["pattern"], value):
            raise ValidationError(f"Value does not match expected format.")

    if rule.get("allowed_values"):
        matched = _match_allowed_value(value, rule["allowed_values"])
        if matched is None and value != "":
            raise ValidationError(f"Must be one of: {', '.join(str(v) for v in rule['allowed_values'])}")
        # Return the canonical allowed value (e.g. spoken "junior" -> "Jr")
        return matched if matched is not None else value

    return value


# Spoken / natural-language synonyms mapped to canonical select values.
# Keys are lowercased; values must match an entry in the field's allowed_values
# (case-insensitively).
_VALUE_SYNONYMS: dict[str, str] = {
    # Name suffixes
    "junior": "jr",
    "jr.": "jr",
    "senior": "sr",
    "sr.": "sr",
    "the second": "ii",
    "second": "ii",
    "2nd": "ii",
    "two": "ii",
    "the third": "iii",
    "third": "iii",
    "3rd": "iii",
    "three": "iii",
    "the fourth": "iv",
    "fourth": "iv",
    "4th": "iv",
    "four": "iv",
    # Yes / No style selects
    "yeah": "yes",
    "yep": "yes",
    "yup": "yes",
    "correct": "yes",
    "nope": "no",
    "nah": "no",
    # Voter registration phrasing
    "already registered": "already_registered",
    "already": "already_registered",
    "registered": "already_registered",
}


def _match_allowed_value(value: str, allowed_values: list) -> str | None:
    """
    Match a user value against allowed_values, tolerant of spoken synonyms and
    formatting (case, surrounding punctuation, spaces vs underscores).
    Returns the canonical allowed value, or None if no match.
    """
    # Map allowed values by a normalized key for lookup.
    canonical_by_norm = {}
    for v in allowed_values:
        canonical_by_norm[_norm_token(str(v))] = v

    candidate = _norm_token(value)

    # 1) Direct (normalized) match
    if candidate in canonical_by_norm:
        return canonical_by_norm[candidate]

    # 2) Synonym match — map the spoken word to a canonical token, then look up.
    raw_lower = value.strip().lower().rstrip(".")
    synonym = _VALUE_SYNONYMS.get(raw_lower) or _VALUE_SYNONYMS.get(candidate)
    if synonym and synonym in canonical_by_norm:
        return canonical_by_norm[synonym]

    return None


def _norm_token(s: str) -> str:
    """Lowercase, strip surrounding punctuation/whitespace, unify separators."""
    s = s.strip().lower().rstrip(".")
    s = re.sub(r"[\s_-]+", "_", s)
    return s


_BOOL_TRUE = {
    "true", "yes", "yeah", "yep", "yup", "y", "1", "ok", "okay", "sure",
    "correct", "right", "affirmative", "please", "definitely", "absolutely",
    "of course", "i do", "we do", "they do",
}
_BOOL_FALSE = {
    "false", "no", "nope", "nah", "n", "0", "negative", "never",
    "i don't", "i do not", "we don't", "they don't", "not really",
}


def _parse_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    # Lowercase and strip surrounding punctuation/whitespace ("Yes." -> "yes")
    s = str(value).strip().lower().strip(".,!?;: ")
    if s in _BOOL_TRUE:
        return True
    if s in _BOOL_FALSE:
        return False
    # Fall back to a leading-word check ("yes, please" -> yes)
    tokens = s.split()
    first = tokens[0].strip(".,!?;:") if tokens else ""
    if first in _BOOL_TRUE:
        return True
    if first in _BOOL_FALSE:
        return False
    raise ValidationError("Please answer yes or no.")


def _parse_date(value: Any) -> str:
    """Normalize to YYYY-MM-DD."""
    s = _clean_date_text(str(value).strip())
    compact = re.sub(r"\D", "", s)
    if len(compact) in {6, 7, 8}:
        # Voice/STT often turns "01/01/1992" into "0101 1992". In this US form
        # context, prefer MMDDYYYY unless the value clearly starts with a year.
        compact_candidates = [compact]
        if len(compact) == 6:
            # "1 1 1992" may arrive as "111992"; try M-D-YYYY with zero padding.
            compact_candidates.extend([f"0{compact[0]}0{compact[1:]}", f"0{compact}"])
        elif len(compact) == 7:
            compact_candidates.extend([f"0{compact}", f"{compact[:2]}0{compact[2:]}"])
        for candidate in compact_candidates:
            compact_formats = ["%Y%m%d"] if candidate[:4].startswith(("19", "20")) else ["%m%d%Y", "%Y%m%d"]
            for fmt in compact_formats:
                try:
                    dt = datetime.strptime(candidate, fmt)
                    return dt.strftime("%Y-%m-%d")
                except ValueError:
                    continue
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%B %d %Y",
        "%b %d %Y",
        "%B %d, %Y",
        "%b %d, %Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValidationError("Please provide a valid date in MM/DD/YYYY format.")


def _clean_date_text(value: str) -> str:
    """Prepare common spoken dates, e.g. "January 5th 1980", for parsing."""
    s = value.strip()
    s = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\bof\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    return s


_NON_ANSWER_EXACT = {
    "send", "submit", "stop", "start", "next", "back", "cancel", "go",
    "voice", "mute", "unmute", "voice on", "voice off", "start listening",
    "stop listening", "skip this question", "tap the mic", "type your answer",
}


def _looks_like_non_answer_text(value: str) -> bool:
    """Detect non-answer utterances before they are saved as text answers.

    The voice assistant receives UI-bound answers, so a repeated prompt like
    "what is your first name" or a recognised button label like "send" can
    otherwise validate as free text. Rejecting them here keeps both the LLM and
    deterministic paths from storing UI/assistant text as a user's data.
    """
    s = re.sub(r"\s+", " ", value.strip().lower()).strip(" .!?")
    if not s:
        return False
    if s in _NON_ANSWER_EXACT:
        return True
    question_starts = (
        "what is ", "what's ", "whats ", "why ", "how ", "when ", "where ",
        "who ", "can you ", "could you ", "do i ", "should i ", "explain ",
        "help me ",
    )
    if s.startswith(question_starts):
        return True
    return value.strip().endswith("?") and len(s.split()) >= 3


def _parse_phone(value: Any) -> str:
    """Normalize to 10-digit string."""
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValidationError("Please provide a 10-digit phone number.")
    return digits


def _parse_ssn(value: Any) -> str:
    """Normalize to 9-digit string."""
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 9:
        raise ValidationError("SSN must be 9 digits.")
    return digits


def _parse_number(value: Any, rule: dict) -> int | float:
    try:
        num = float(str(value).strip())
    except ValueError:
        raise ValidationError("Please provide a valid number.")
    if rule.get("min") is not None and num < rule["min"]:
        raise ValidationError(f"Must be at least {rule['min']}.")
    if rule.get("max") is not None and num > rule["max"]:
        raise ValidationError(f"Must be at most {rule['max']}.")
    return int(num) if num == int(num) else num


_US_STATE_CODES: dict[str, str] = {
    "ALABAMA": "AL",
    "ALASKA": "AK",
    "ARIZONA": "AZ",
    "ARKANSAS": "AR",
    "CALIFORNIA": "CA",
    "COLORADO": "CO",
    "CONNECTICUT": "CT",
    "DELAWARE": "DE",
    "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL",
    "GEORGIA": "GA",
    "HAWAII": "HI",
    "IDAHO": "ID",
    "ILLINOIS": "IL",
    "INDIANA": "IN",
    "IOWA": "IA",
    "KANSAS": "KS",
    "KENTUCKY": "KY",
    "LOUISIANA": "LA",
    "MAINE": "ME",
    "MARYLAND": "MD",
    "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI",
    "MINNESOTA": "MN",
    "MISSISSIPPI": "MS",
    "MISSOURI": "MO",
    "MONTANA": "MT",
    "NEBRASKA": "NE",
    "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM",
    "NEW YORK": "NY",
    "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND",
    "OHIO": "OH",
    "OKLAHOMA": "OK",
    "OREGON": "OR",
    "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN",
    "TEXAS": "TX",
    "UTAH": "UT",
    "VERMONT": "VT",
    "VIRGINIA": "VA",
    "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI",
    "WYOMING": "WY",
}

_US_CODE_SET = set(_US_STATE_CODES.values())


def normalize_us_state(value: Any) -> str | None:
    """Return a two-letter US state code from a state name/code if present."""
    raw = str(value or "").strip()
    if not raw:
        return None
    compact = re.sub(r"[^A-Za-z ]+", " ", raw).upper()
    compact = re.sub(r"\s+", " ", compact).strip()
    if compact in _US_CODE_SET:
        return compact
    if compact in _US_STATE_CODES:
        return _US_STATE_CODES[compact]
    # Voice answers often include another value in the same breath, such as
    # "Ohio 614 555 9800". Pull out the state token and let the other field parse
    # the remaining information separately.
    for name, code in sorted(_US_STATE_CODES.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", compact):
            return code
    for code in _US_CODE_SET:
        if re.search(rf"\b{re.escape(code)}\b", compact):
            return code
    return None


def _looks_like_state_field(field: dict) -> bool:
    """Identify schema fields that should store US state abbreviations."""
    key = str(field.get("field_key", "")).lower()
    label = str(field.get("label", "")).lower()
    question = str(field.get("question_text", "")).lower()
    rule = field.get("validation_rule") or {}
    max_length = rule.get("max_length")
    has_state_name = (
        key.endswith(".state")
        or key.endswith("_state")
        or re.search(r"\bstate\b", label) is not None
        or re.search(r"\bstate\b", question) is not None
    )
    return bool(has_state_name and (max_length is None or int(max_length) <= 2))
