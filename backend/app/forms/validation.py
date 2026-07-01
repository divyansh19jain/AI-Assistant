"""Field-level validation for form answers."""

import re
from datetime import datetime
from typing import Any


class ValidationError(Exception):
    pass


# ── Name-field rule-based pre-filter ─────────────────────────────────────────
# These checks run BEFORE the LLM semantic validator so we never rely solely
# on an AI call that can fail silently or be too lenient.

# Common English words that are definitively NOT human names.
# Extended with food/drink, actions, phrases, objects, and gibberish patterns.
_NAME_BLOCKLIST: frozenset[str] = frozenset({
    # Phrases / multi-word non-names
    "give me some", "give me", "tell me", "show me", "help me",
    "i want", "i need", "i would", "i will", "i can", "i am",
    "some info", "some information", "something",
    # Foods & drinks
    "shake", "mojito", "smoothie", "coffee", "latte", "espresso", "tea",
    "soda", "beer", "wine", "burger", "pizza", "taco", "sushi", "sandwich",
    "salad", "soup", "pasta", "donut", "cookie", "cake", "pie", "apple",
    "banana", "mango", "grape", "lemon", "lime", "orange",
    # Actions / verbs used as inputs
    "yoga", "swim", "run", "jump", "fly", "walk", "shop", "buy",
    "sell", "work", "sleep", "eat", "drink", "cook", "play", "dance",
    # Objects / concepts
    "blue", "green", "red", "yellow", "black", "white", "purple", "pink",
    "chair", "table", "phone", "laptop", "car", "truck", "house", "room",
    "river", "mountain", "ocean", "forest", "cloud", "star", "moon",
    "money", "cash", "dollar", "euro",
    # Brands / places that aren't also common names
    "youtube", "google", "amazon", "walmart", "target", "starbucks",
    "facebook", "instagram", "twitter", "tiktok", "netflix", "uber",
    # Gibberish patterns caught elsewhere, but explicit common ones
    "abc", "xyz", "test", "none", "null", "unknown",
})

# Multi-word answers that span 3+ words are almost never a single name.
# Exception: hyphenated names like "Mary-Jane", "Jean-Pierre" still single token.
_NAME_MAX_WORDS = 3

# Characters that belong in a name: letters, hyphens, apostrophes, spaces, periods.
_NAME_PATTERN = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ'\-\. ]+$")


def validate_name_field(label: str, value: str) -> None:
    """
    Rule-based guard for personal name fields (first, last, middle, full name).
    Raises ValidationError if the value is clearly not a human name.
    This runs before (and regardless of) the LLM semantic validator.
    """
    v = value.strip()
    if not v:
        return  # emptiness is handled separately by required-field checks

    v_lower = v.lower()

    # 1. Exact blocklist match
    if v_lower in _NAME_BLOCKLIST:
        raise ValidationError(
            f"That doesn't look like a name. Please enter your actual {label.lower()}."
        )

    # 2. Partial blocklist match (phrase contained in the value)
    for blocked in _NAME_BLOCKLIST:
        if " " in blocked and blocked in v_lower:
            raise ValidationError(
                f"That doesn't look like a name. Please enter your actual {label.lower()}."
            )

    # 3. Too many words — names don't span 4+ separate words
    words = v.split()
    if len(words) > _NAME_MAX_WORDS:
        raise ValidationError(
            f"That looks like more than a name. Please enter just your {label.lower()}."
        )

    # 4. Non-name characters (digits, special chars outside letters/hyphens/apostrophes)
    if not _NAME_PATTERN.match(v):
        raise ValidationError(
            f"Names should only contain letters. Please enter your {label.lower()}."
        )

    # 5. Single very-short tokens that aren't initials or real names
    if len(words) == 1 and len(v) == 1 and not v.isupper():
        raise ValidationError(
            f"That doesn't look like a complete {label.lower()}. Could you enter the full name?"
        )


def _is_name_label(label: str) -> bool:
    """Return True if the field label suggests a personal name field."""
    low = label.lower()
    return any(w in low for w in ("first name", "last name", "middle name", "full name", "maiden name"))


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
    label_str = field.get("label", "this field")
    if field_type in {"text", "textarea", "email", "select"} and _looks_like_non_answer_text(value):
        raise ValidationError(
            f"That sounds like an instruction or question, not an answer for {label_str}. Please give the actual value."
        )

    # Name-field rule-based guard — must run before LLM, deterministic.
    if field_type in {"text", "textarea"} and _is_name_label(label_str):
        validate_name_field(label_str, value)

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
    # Name suffixes — spoken forms and preference phrases
    "junior": "jr",
    "jr.": "jr",
    "i'm a junior": "jr",
    "i am a junior": "jr",
    "senior": "sr",
    "sr.": "sr",
    "i'm a senior": "sr",
    "i am a senior": "sr",
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

    # 3) Strip common spoken prefixes ("I prefer Junior" -> "Junior",
    #    "it's Junior" -> "Junior", "say Junior" -> "Junior") and retry.
    _SPOKEN_PREFIXES = (
        "i prefer ", "i'd say ", "it's ", "it is ", "say ", "mine is ",
        "that's ", "that is ", "use ", "put ", "the answer is ", "i am ",
    )
    for prefix in _SPOKEN_PREFIXES:
        if raw_lower.startswith(prefix):
            stripped = value.strip()[len(prefix):]
            result = _match_allowed_value(stripped, allowed_values)
            if result is not None:
                return result
            break

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
    # A spelled-out month ("February 19 1999") MUST go through the named-month
    # formats below. The compact-digit heuristic strips non-digits, which would drop
    # the month word entirely and misread the leftover digits — e.g. "February 19
    # 1999" -> "191999" -> strptime "%Y%m%d" -> 1919-09-09 (single-digit %m/%d).
    has_alpha = any(c.isalpha() for c in s)
    compact = re.sub(r"\D", "", s)
    if not has_alpha and len(compact) in {6, 7, 8}:
        # Voice/STT often turns "01/01/1992" into "0101 1992". In this US form
        # context, prefer MMDDYYYY unless the value clearly starts with a year.
        compact_candidates = [compact]
        if len(compact) == 6:
            # "1 1 1992" may arrive as "111992"; try M-D-YYYY with zero padding.
            compact_candidates.extend([f"0{compact[0]}0{compact[1:]}", f"0{compact}"])
        elif len(compact) == 7:
            compact_candidates.extend([f"0{compact}", f"{compact[:2]}0{compact[2:]}"])
        for candidate in compact_candidates:
            # Only treat a candidate as YYYYMMDD when it is a full 8 digits — otherwise
            # strptime's single-digit month/day fallback turns "191999" into 1919-09-09.
            if candidate[:4].startswith(("19", "20")) and len(candidate) == 8:
                compact_formats = ["%Y%m%d"]
            else:
                compact_formats = ["%m%d%Y"] + (["%Y%m%d"] if len(candidate) == 8 else [])
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
        "%d %B %Y",   # day-first spoken: "19 February 1999"
        "%d %b %Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValidationError("Please provide a valid date in MM/DD/YYYY format.")


_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30,
    # ordinals
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
    # compound ordinals like "twenty-second" handled below
}
_TENS_ORD = {
    "twenty": 20, "thirty": 30,
}


def _spoken_to_int(word: str) -> int | None:
    """Convert a single spoken number/ordinal word to int, or None if unknown."""
    w = word.lower().replace("-", " ")
    if w in _ONES:
        return _ONES[w]
    # "twenty second" / "twenty-second" / "thirtieth" compound
    parts = w.split()
    if len(parts) == 2 and parts[0] in _TENS_ORD and parts[1] in _ONES:
        return _TENS_ORD[parts[0]] + _ONES[parts[1]]
    return None


def _year_words_to_digits(s: str) -> str:
    """Convert spoken year patterns to 4-digit integers.

    Handles:
      "nineteen ninety"           -> "1990"
      "nineteen eighty five"      -> "1985"
      "nineteen ninety nine"      -> "1999"
      "two thousand"              -> "2000"
      "two thousand five"         -> "2005"
      "twenty twenty"             -> "2020"  (only when following a digit/month)
    """
    # "nineteen TENS [UNITS]" — e.g. "nineteen eighty five" -> 1985
    # tens must be a tens-place word (twenty, thirty, … ninety), units optional.
    _tens_words = {
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    }
    _units_words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9,
    }

    def _repl_19(m: re.Match) -> str:
        tens_word = m.group(1).lower()
        units_word = (m.group(2) or "").lower()
        tens = _tens_words.get(tens_word)
        if tens is None:
            return m.group(0)
        units = _units_words.get(units_word, 0)
        return str(1900 + tens + units)

    s = re.sub(
        r"\bninete(?:en)?\s+(\w+)(?:\s+(\w+))?",
        _repl_19,
        s, flags=re.IGNORECASE,
    )

    # "two thousand [X]"
    def _repl_2k(m: re.Match) -> str:
        extra_word = (m.group(1) or "").lower()
        extra = _ONES.get(extra_word, 0) if extra_word else 0
        return str(2000 + extra)

    s = re.sub(r"\btwo\s+thousand(?:\s+(\w+))?", _repl_2k, s, flags=re.IGNORECASE)

    # "twenty XX" as a year ONLY when it looks like a 2020s year context
    # (i.e. "twenty twenty" or "twenty twenty-one" after a month word).
    # We DON'T replace "twenty" generically here — that breaks "twenty second".
    _month_names = (
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    )
    month_pat = "|".join(_month_names)

    def _repl_20s(m: re.Match) -> str:
        units_word = m.group(2).lower()
        units = _ONES.get(units_word)
        if units is None or units > 9:  # only 2020-2029
            return m.group(0)
        return m.group(1) + " " + str(2020 + units)

    # Only convert "twenty X" when preceded by a digit (day) or month name
    s = re.sub(
        r"(\d{1,2}|" + month_pat + r")\s+twenty\s+(\w+)",
        _repl_20s, s, flags=re.IGNORECASE,
    )
    return s


def _clean_date_text(value: str) -> str:
    """Normalize spoken/STT dates to a form strptime can parse.

    Handles:
      "March fifth nineteen ninety"            -> "March 5 1990"
      "the fifth of March 1990"                -> "5 March 1990"
      "January first two thousand"             -> "January 1 2000"
      "May twenty second nineteen eighty five" -> "May 22 1985"
      "December thirty first nineteen ninety nine" -> "December 31 1999"
      "March 5th 1990"                         -> "March 5 1990"  (existing)
    """
    s = value.strip()
    # Strip leading "the" before ordinals ("the fifth of march")
    s = re.sub(r"^the\s+", "", s, flags=re.IGNORECASE)
    # Remove ordinal suffixes on digits: "5th" -> "5"
    s = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", s, flags=re.IGNORECASE)
    # Remove filler words
    s = re.sub(r"\bof\b", " ", s, flags=re.IGNORECASE)

    # Replace compound day ordinals BEFORE year conversion so "twenty second"
    # is turned to "22" and not misread as part of a year.
    def _replace_compound_day(m: re.Match) -> str:
        n = _spoken_to_int(m.group(0))
        return str(n) if n is not None else m.group(0)

    s = re.sub(
        r"\b(?:twenty|thirty)[\s\-]"
        r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|"
        r"tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|"
        r"seventeenth|eighteenth|nineteenth|twentieth|thirtieth|"
        r"one|two|three|four|five|six|seven|eight|nine)\b",
        _replace_compound_day, s, flags=re.IGNORECASE,
    )

    # Convert spoken year patterns (nineteen XX, two thousand, etc.)
    s = _year_words_to_digits(s)

    # Convert remaining single spoken ordinal/number words for the day position.
    def _replace_day(m: re.Match) -> str:
        n = _spoken_to_int(m.group(0))
        return str(n) if n is not None else m.group(0)

    s = re.sub(
        r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
        r"eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|"
        r"eighteenth|nineteenth|twentieth|thirtieth)\b",
        _replace_day, s, flags=re.IGNORECASE,
    )

    # Plain number words adjacent to a month name (e.g. "eleven january 1999" → "11 january 1999").
    # Only replace when a month name is within two tokens — avoids corrupting names/phrases.
    _month_pat = (
        r"(?:january|february|march|april|may|june|july|august|"
        r"september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)"
    )
    _day_words = (
        r"(?:one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
        r"eighteen|nineteen|twenty|thirty)"
    )

    def _replace_plain_day(m: re.Match) -> str:
        n = _ONES.get(m.group(1).lower())
        return str(n) + m.group(2) if n is not None else m.group(0)

    # Pattern: day-word followed by month ("eleven january 1999")
    s = re.sub(
        rf"\b{_day_words}\b(\s+{_month_pat})",
        lambda m: str(_ONES.get(m.group(0).split()[0].lower(), m.group(0).split()[0])) + m.group(0)[len(m.group(0).split()[0]):],
        s, flags=re.IGNORECASE,
    )
    # Pattern: month followed by day-word ("january eleven 1999")
    s = re.sub(
        rf"({_month_pat}\s+){_day_words}\b",
        lambda m: m.group(0)[:len(m.group(1))] + str(_ONES.get(m.group(0)[len(m.group(1)):].lower(), m.group(0)[len(m.group(1)):])),
        s, flags=re.IGNORECASE,
    )

    s = re.sub(r"\s+", " ", s).strip()
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
