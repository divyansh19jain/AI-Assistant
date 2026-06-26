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
    s = str(value).strip()
    formats = ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y", "%Y/%m/%d"]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValidationError("Please provide a valid date in MM/DD/YYYY format.")


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
