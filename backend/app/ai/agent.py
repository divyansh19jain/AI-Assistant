"""
Conversational form-filling agent (the "real assistant" brain).

This replaces the rigid one-field-at-a-time pipeline with a single tool-calling
conversation. On each user turn the LLM sees the whole form (what's filled, what's
still needed) plus the recent dialogue, and it decides what to do: fill one or many
fields, skip optionals, fix an earlier answer, explain a term in plain words, or ask
the next best question — the way a patient person helping a less-literate applicant
would.

Tools the agent can call:
  - save_answers(items)  -> validate + persist one or more field values
  - skip_fields(keys)    -> mark optional fields as intentionally blank
  - screen_income(...)   -> compare income to official ODM 2026 screening chart
  - go_to_review()       -> when every applicable field is answered or skipped

Falls back gracefully: if no OPENAI_API_KEY is configured or the provider fails,
run_agent_turn uses deterministic field handling instead of leaving the user stuck.

🔒 PHI: the patient's words are never logged. Sensitive field VALUES are never sent
back into the model context or spoken — only the fact that they're filled.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.core.config import get_settings
from app.db.models import FormAnswer, FormSession, SessionMessage
from app.forms.service import get_all_fields_from_schema
from app.forms.missing_fields import (
    get_missing_applicable_fields,
    get_missing_required_fields,
    is_field_applicable,
)
from app.forms.validation import ValidationError, validate_answer
from app.sessions import service as svc

logger = logging.getLogger(__name__)

SKIPPED = "__skipped__"
_MAX_TOOL_ROUNDS = 6           # safety cap on tool-call/▸model ping-pong per turn
_HISTORY_TURNS = 24            # how many prior user/assistant messages to replay
_DIRECT_SKIP_WORDS = {
    "skip", "skipped", "skip it", "skip this", "none", "n/a", "na",
    "no answer", "leave blank", "blank", "not applicable",
}
# Read-back answers use the existing readiness low-confidence blocker instead of a
# separate pending-confirmation table. Keep this below LOW_CONFIDENCE_THRESHOLD.
_READBACK_CONFIDENCE = 0.5


# ───────────────────────── form state → model context ─────────────────────────

def _field_status(field: dict, answers: dict[str, Any]) -> tuple[str, Any]:
    """Return (status, display_value) for a field given current answers."""
    key = field["field_key"]
    if key not in answers:
        return "missing", None
    val = answers[key]
    if val == SKIPPED:
        return "skipped", None
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return "missing", None
    try:
        validate_answer(field, val)
    except ValidationError:
        return "invalid", None
    return "filled", val


def _build_form_context(schema: dict, answers: dict[str, Any]) -> str:
    """A compact, section-grouped snapshot of the form for the system prompt."""
    section_titles = {s["section_key"]: s.get("section_title", s["section_key"]) for s in schema.get("sections", [])}
    lines: list[str] = [
        "RULE: Any field marked FILLED or SKIPPED is DONE — do NOT ask for it again under any circumstances.",
    ]
    current_section = None
    fields = get_all_fields_from_schema(schema)
    fields_by_key = {f["field_key"]: f for f in fields}
    for field in fields:
        if not is_field_applicable(field, answers, fields_by_key):
            continue
        sec = field.get("section")
        if sec != current_section:
            current_section = sec
            lines.append(f"\n## {section_titles.get(sec, sec)}")
        status, value = _field_status(field, answers)
        req = "required" if field.get("required", False) else "optional"
        opts = ""
        rule = field.get("validation_rule") or {}
        allowed = rule.get("allowed_values") or field.get("options")
        if isinstance(allowed, list) and allowed:
            opts = f" choices={allowed}"
        if field.get("sensitive"):
            shown = "FILLED (hidden)" if status == "filled" else status.upper()
        else:
            shown = f'FILLED="{value}"' if status == "filled" else status.upper()
        lines.append(
            f"- [{field['field_key']}] {field.get('label', field['field_key'])} "
            f"({field.get('type','text')}, {req}){opts} → {shown}"
        )
    return "\n".join(lines)


def _prioritized_next(form_id: str, answers: dict[str, Any], missing: list[dict]) -> dict | None:
    """The single next field to ask — strictly the next missing field in schema order.

    The agent is told (in NEXT FIELD GUIDANCE) to ask EXACTLY this field, so the question,
    the tappable chips, and the answer binding are always the same field. We deliberately
    do NOT let the model pick the order — that's what made the chips disagree with the
    question (Yes/No under 'ZIP code?', county under 'date of birth?')."""
    return missing[0] if missing else None


def _next_missing(form_id: str, schema: dict, answers: dict[str, Any]) -> dict | None:
    return _prioritized_next(form_id, answers, get_missing_applicable_fields(form_id, answers, schema))


def _coerce_yes_no(text: str, field_key: str) -> bool | None:
    """Map a free-text reply to True/False for a yes/no field, or None if unclear.
    Handles the indirect phrasings the agent uses (e.g. 'just me' for the add-a-person gate)."""
    t = (text or "").strip().lower().strip(".!?")
    if not t:
        return None
    if re.search(r"adding_person\d+$", field_key):
        if any(w in t for w in ("just me", "only me", "myself", "just for me", "for myself",
                                "no one else", "by myself", "just mine", "only myself", "nobody else",
                                "that's all", "thats all", "no more", "done", "no one")):
            return False
        if any(w in t for w in ("spouse", "wife", "husband", "partner", "kid", "child", "children",
                                "son", "daughter", "family", "others", "other people", "another person", "add",
                                "more people", "someone else", "another member")):
            return True
    if "email" in field_key:  # "do you want emails, or mail only?"
        if "mail only" in t or t in ("mail", "just mail", "by mail", "paper", "mail please"):
            return False
        if "email" in t or "e-mail" in t or "emails" in t:
            return True
    no_words = {"no", "nope", "nah", "n", "negative", "i don't", "i do not", "none"}
    yes_words = {"yes", "yeah", "yep", "yup", "sure", "correct", "right", "y", "i do", "we do", "ok", "okay"}
    if t in no_words or t.split()[0] in ("no", "nope", "nah"):
        return False
    if t in yes_words or t.split()[0] in ("yes", "yeah", "yep", "yup", "sure"):
        return True
    return None


def _needs_agent_readback(field: dict, input_mode: str) -> bool:
    """Voice-captured dates, phones, and ZIPs must be confirmed before approval."""
    if input_mode != "voice":
        return False
    key = field.get("field_key", "").lower()
    ftype = field.get("type", "text")
    rule = field.get("validation_rule") or {}
    return (
        ftype in {"date", "phone"}
        or key.endswith(".zip")
        or key.endswith("_zip")
        or rule.get("pattern") == r"^\d{5}(-\d{4})?$"
    )


def _agent_save_confidence(field: dict, input_mode: str) -> float:
    """Mark required read-back values low-confidence until the user says they are right."""
    return _READBACK_CONFIDENCE if _needs_agent_readback(field, input_mode) else 1.0


def _format_readback_value(field: dict, value: Any) -> str:
    """Human-friendly rendering for the value the assistant reads back."""
    text = str(value)
    if field.get("type") == "date":
        try:
            from datetime import datetime

            return datetime.strptime(text, "%Y-%m-%d").strftime("%B %-d, %Y")
        except Exception:
            try:
                from datetime import datetime

                return datetime.strptime(text, "%Y-%m-%d").strftime("%B %#d, %Y")
            except Exception:
                return text
    if field.get("type") == "phone":
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return text


def _readback_prompt(field: dict, value: Any) -> str:
    """Deterministic confirmation prompt used when a read-back field blocks readiness."""
    label = field.get("label", field["field_key"])
    rendered = _format_readback_value(field, value)
    return f"I heard {rendered} for {label}. Is that right?"


def _is_help_request(field: dict, user_text: str) -> bool:
    """True when the user is asking for an explanation, not answering the field."""
    try:
        from app.ai.help_intent import classify_intent

        return classify_intent(field, user_text) == "help"
    except Exception:
        logger.warning("Help-intent check failed; treating utterance as an answer.", exc_info=True)
        return False


def _field_help_reply(field: dict, user_text: str, form_id: str) -> str:
    """Plain-language help for the current field; works with or without an LLM."""
    try:
        from app.ai.help_intent import explain_field

        return explain_field(field, user_text, form_id)
    except Exception:
        logger.warning("Field help generation failed; using static field wording.", exc_info=True)
        question = field.get("question_text") or f"Please provide your {field.get('label', field['field_key'])}."
        return f"This question is asking about {field.get('label', field['field_key'])}. {question}"


def _first_low_confidence_field(db, session_id: str, schema: dict) -> tuple[dict, Any] | None:
    """Return the first applicable answer that still needs read-back confirmation."""
    answers = svc._answers_map(db, session_id)
    rows = {r.field_key: r for r in db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()}
    fields = get_all_fields_from_schema(schema)
    fields_by_key = {f["field_key"]: f for f in fields}
    for field in fields:
        key = field["field_key"]
        row = rows.get(key)
        if not row or float(row.confidence or 0.0) >= 0.75:
            continue
        if not is_field_applicable(field, answers, fields_by_key):
            continue
        value = answers.get(key)
        if value in (None, "", SKIPPED):
            continue
        return field, value
    return None


def _handle_low_confidence_confirmation(db, session, schema: dict, field_key: str, text: str) -> bool:
    """Apply a yes/no reply to a pending read-back field before the model sees it.

    Yes promotes the stored value to high confidence. No deletes it so the same field is
    asked again. This keeps confirmation state deterministic and survives page reloads.
    """
    row = db.query(FormAnswer).filter(
        FormAnswer.session_id == session.id,
        FormAnswer.field_key == field_key,
    ).first()
    if not row or float(row.confidence or 0.0) >= 0.75:
        return False
    yn = _coerce_yes_no(text, field_key)
    if yn is True:
        row.confidence = 1.0
        db.commit()
        return True
    if yn is False:
        db.delete(row)
        db.commit()
        return True
    return False


def _next_field_payload(db, field: dict | None, answers: dict[str, Any] | None = None) -> dict | None:
    """Metadata for the field being asked, so the UI can offer tappable answer chips
    (Yes/No, select options, or ZIP-aware city values) for fast touch entry."""
    if not field:
        return None
    from app.ai.suggestions import suggestions_for_field

    rule = field.get("validation_rule") or {}
    return {
        "field_key": field["field_key"],
        "label": field.get("label", field["field_key"]),
        "type": field.get("type", "text"),
        "options": rule.get("allowed_values") or field.get("options") or [],
        "suggestions": suggestions_for_field(db, field, answers or {}),
    }


def _confirmation_field_payload(field: dict | None) -> dict | None:
    """UI metadata for a read-back confirmation on an already-saved field."""
    if not field:
        return None
    return {
        "field_key": field["field_key"],
        "label": field.get("label", field["field_key"]),
        "type": "confirmation",
        "options": ["Yes", "No"],
        "suggestions": ["Yes", "No"],
    }


def _confirmation_turn_reply(db, session, session_id: str, schema: dict, answers: dict) -> dict:
    """Return a deterministic reply after a read-back confirmation (yes/no), bypassing the LLM.

    The LLM must never see the 'Yes'/'No' in its context because it tends to re-ask the
    confirmed field or produce an off-topic response. Instead we check whether another
    low-confidence field still needs read-back, then either re-prompt that field or move
    on to the next missing field — identical to what the main loop produces at the end of
    a normal turn, but without the model call.
    """
    from app.forms.missing_fields import get_missing_applicable_fields, get_missing_required_fields
    from app.db.models import SessionMessage

    # Another low-confidence field might still be pending (e.g. both ZIP and phone were
    # captured in voice mode).
    confirm_next = _first_low_confidence_field(db, session_id, schema)
    if confirm_next:
        confirm_field, confirm_value = confirm_next
        assistant_text = _readback_prompt(confirm_field, confirm_value)
        db.add(SessionMessage(session_id=session_id, role="assistant", content=assistant_text))
        db.commit()
        missing_applicable = get_missing_applicable_fields(session.form_id, answers, schema)
        missing_required = get_missing_required_fields(session.form_id, answers, schema)
        readiness = svc.get_session_readiness(db, session_id) or {"ready": False}
        svc._set_collection_status(session, len(missing_applicable) == 0)
        db.commit()
        return {
            "assistant_message": assistant_text,
            "done": bool(readiness["ready"]),
            "go_to_review": False,
            "state": {
                "answered_count": svc._valid_answer_count(schema, answers),
                "missing_count": len(missing_applicable),
                "missing_required_count": len(missing_required),
                "total": len(get_all_fields_from_schema(schema)),
                "next_field_key": confirm_field["field_key"],
            },
            "next_field": _confirmation_field_payload(confirm_field),
            "answers": answers,
        }

    # All confirmed — move to the next missing field deterministically.
    missing_applicable = get_missing_applicable_fields(session.form_id, answers, schema)
    missing_required = get_missing_required_fields(session.form_id, answers, schema)
    readiness = svc.get_session_readiness(db, session_id) or {"ready": False}
    done = bool(readiness["ready"])
    svc._set_collection_status(session, len(missing_applicable) == 0)
    db.commit()

    nxt = missing_applicable[0] if missing_applicable else None
    assistant_text = _next_action_reply(schema, answers, session.form_id, is_start=False)
    db.add(SessionMessage(session_id=session_id, role="assistant", content=assistant_text))
    db.commit()
    return {
        "assistant_message": assistant_text,
        "done": done,
        "go_to_review": done,
        "state": {
            "answered_count": svc._valid_answer_count(schema, answers),
            "missing_count": len(missing_applicable),
            "missing_required_count": len(missing_required),
            "total": len(get_all_fields_from_schema(schema)),
            "next_field_key": nxt["field_key"] if nxt else None,
        },
        "next_field": _next_field_payload(db, nxt, answers),
        "answers": answers,
    }


def _topic_queries(user_text: str) -> list[str]:
    """Map a help request to static KB topics without embedding raw user text."""
    text = (user_text or "").lower()
    topics: list[str] = []
    rules = [
        (("qualify", "eligible", "eligibility", "criteria", "income limit", "too much income"), "Ohio Medicaid eligibility screening income limits"),
        (("income", "wages", "salary", "paycheck", "gross", "self-employ", "job", "work"), "gross income wages self employment other income"),
        (("household", "family size", "include", "dependent", "tax return", "spouse"), "who to include household family tax filer dependent spouse"),
        (("citizen", "immigrant", "immigration", "non-citizen", "document"), "citizenship eligible immigration status Medicaid application"),
        (("pregnant", "pregnancy", "baby", "postpartum"), "pregnant women Medicaid coverage income limit"),
        (("medical bill", "last 3 months", "retroactive", "back bill"), "medical bills last three months retroactive Medicaid"),
        (("medicare", "premium", "qmb", "slmb", "qi-1", "mpap"), "Medicare Premium Assistance Programs MPAP QMB SLMB QI-1"),
        (("aged", "blind", "disabled", "disability", "nursing", "in-home", "long term", "appendix e"), "aged blind disabled long term care Appendix E"),
        (("insurance", "employer coverage", "cobra", "retiree", "tricare", "va"), "current health coverage employer insurance COBRA retiree"),
    ]
    for needles, query in rules:
        if any(needle in text for needle in needles):
            topics.append(query)
    return topics[:3]


def _kb_context_for_turn(db, form_id: str, field: dict | None, user_text: str) -> str:
    """Return short form-level guidance for the current turn, if KB chunks exist.

    Field guidance uses static field metadata. Eligibility/help topic guidance uses
    fixed topic phrases selected from the utterance, so raw applicant answers are
    not sent to embeddings or stored in the KB index.
    """
    queries: list[str] = []
    if field:
        queries.append(
            " ".join(
                str(part)
                for part in (field.get("label"), field.get("question_text"), field.get("section"))
                if part
            )
        )
    queries.extend(_topic_queries(user_text))
    if not queries:
        return ""
    try:
        from app.ai.kb import retrieve

        chunks: list[str] = []
        seen: set[str] = set()
        for query in queries:
            for chunk in retrieve(db, form_id, query, k=2):
                if chunk not in seen:
                    seen.add(chunk)
                    chunks.append(chunk)
                if len(chunks) >= 4:
                    break
            if len(chunks) >= 4:
                break
    except Exception:
        chunks = []
    if not chunks:
        return ""
    joined = "\n\n".join(f"- {chunk[:700]}" for chunk in chunks)
    return (
        "FORM KNOWLEDGEBASE GUIDANCE for the next question. Use this only to "
        "explain terms in plain language; do not quote long passages:\n"
        f"{joined}"
    )


def _next_field_guidance(form_id: str, field: dict | None) -> str:
    """Prompt-pack guidance for the next field the agent should ask about."""
    if not field:
        return ""
    try:
        from app.forms.prompts import get_field_override

        override = get_field_override(form_id, field["field_key"])
    except Exception:
        override = {}
    question = override.get("question") or field.get("question_text") or field.get("label", field["field_key"])
    help_text = override.get("help")
    lines = [
        "NEXT FIELD GUIDANCE (a suggestion for what's likely next — you may pick a more natural field):",
        f"- suggested field_key: {field['field_key']}",
        f"- if you ask it, good wording is: {question}",
    ]
    if help_text:
        lines.append(f"- plain_language_help: {help_text}")
    lines.append(
        "- CRITICAL: Before asking ANY field, check CURRENT FORM STATE. "
        "If the field is FILLED or SKIPPED there, skip it and move to the next MISSING field instead."
    )
    lines.append("- Whatever field you choose, call the `ask` tool with its field_key before you ask it.")
    return "\n".join(lines)


def _form_persona(form_id: str) -> str:
    """The form's own system persona (prompts/system.md), injected so form-specific
    domain knowledge and rules reach the agent — and stay scoped to that form."""
    try:
        from app.forms.prompts import get_system_persona

        return (get_system_persona(form_id) or "").strip()
    except Exception:
        return ""


# Forms that ship an Ohio Medicaid income-screening chart get the screen_income tool.
# Keyed to the form because the MAGI dollar limits are Ohio-2026 specific.
_INCOME_SCREENING_FORMS = {"ODM_07216"}


def _supports_income_screening(form_id: str | None) -> bool:
    return form_id in _INCOME_SCREENING_FORMS


SYSTEM_PROMPT = """\
You are Mia, an expert benefits case manager helping a person complete their \
{form_title} by voice. You are warm, sharp, efficient, and trustworthy — the kind of \
helper who has filled out this form hundreds of times and makes it feel easy.

WHO YOU'RE HELPING
Many people you help are stressed, tired, have limited reading ability, or are doing \
this for the first time. Meet them where they are. Never rush or judge them.

HOW YOU TALK (your words are read ALOUD by a voice)
- Plain, everyday words. Short sentences. No jargon or form-speak.
- Warm and human; react naturally. Keep each reply to 1–3 sentences. Vary how you \
acknowledge — most of the time just go straight to the next question. Do NOT begin every \
reply with "Thanks" or their name; real people don't thank you after every single answer.
- Address them as "you", and use their first name only now and then, not on every line.
- Explain a confusing term in plain words as you ask it ("Gross pay just means the \
amount before taxes come out").

HOW YOU WORK (like a real case manager, not a survey)
- YOU choose the next question, in the order a sharp human case worker would: get the big \
picture first (who's applying — just them, or a spouse/kids?), then their key details, then \
income and coverage. Don't march down the form in raw order. Ask EVERY field — required and \
optional — in a sensible human order. For optional fields (middle name, suffix, mailing \
address, email, etc.) ask them and let the person say "none", "skip", or "same as home" to \
skip. Never silently skip a field.
- Ask ONE thing at a time. BEFORE each question, CALL the `ask` tool with that field's \
field_key. This is required every turn (except when you call go_to_review) so the app shows \
the right answer buttons and saves the reply to the correct field. Then ask that one thing in \
warm, plain words. NEVER ask two fields in one breath ("are you married, and a citizen?" is \
wrong). NEVER ask a field that is marked FILLED or SKIPPED in CURRENT FORM STATE — those are \
DONE, period. This includes fields auto-filled from ZIP code (city, state, county) or from \
records. If something is FILLED, move on to the next MISSING field.
- NAME FIELDS ARE ALWAYS SEPARATE. First name, middle name, and last name must each be asked \
and answered individually. If you asked for first name and they said "Jacob", save ONLY first \
name = "Jacob". Do NOT also save middle name or last name. Ask each name in a separate turn.
- If they volunteer several non-name facts at once, SAVE them ALL with save_answers — then \
`ask` for the next thing. NEXT FIELD GUIDANCE is a suggestion for what's next; you may pick a \
more natural field, but always declare it with `ask`.
- Move at their pace: keep momentum when they're rolling; slow down and reassure when stuck.
- Briefly say WHY a question matters when it builds trust ("I ask about income because it \
decides which programs can help you").
- Listen for real-life situations and handle them like a pro without being told: no income, \
cash or under-the-table work, self-employment or gig work, a recent job loss or cut hours, \
disability or SSI, pregnancy or a new baby, students, foster youth, someone who is homeless, \
or a household where not everyone is applying or a citizen. Recognize these and ask the right \
follow-ups.
- If two answers don't add up, gently double-check instead of guessing.

ACCURACY (this becomes a real application)
- Capture exactly what they say. Get precise amounts, dates, and the spelling of names and \
IDs. Never invent or assume an answer — if you're unsure what they meant, ask.
- If an answer doesn't clearly fit the question (it sounds garbled, off-topic, or like a \
mishearing), ask a short clarifying question RIGHT AWAY and STAY on that same question — do \
not skip ahead to a different one and circle back later. Echo the choices back if it helps \
("Did you mean email, or mail only?").
- NEVER say you captured something you did not. A field is only done when the tool result \
says it saved. If a save comes back as not_saved / ok:false, tell the person you didn't quite \
get it and ask again — do not move on as if you have it.
- DATES need a clear month, day, AND year. Never guess or auto-complete a date. If you hear \
something impossible or partial — a day above 31, only a year, a missing month, or garbled \
digits like "ninety-fifth" — treat it as a mishearing: say you didn't catch it and ask again \
slowly. Once you have it, READ THE WHOLE DATE BACK and get a "yes" before moving on ("So that's \
March 5th, 1992 — is that right?"). Do not say "I have your date of birth" without stating it.
- Read phone and ZIP back once to confirm. For a Social Security number or immigration ID, \
confirm you captured it WITHOUT reading the number aloud ("let me make sure I've got your Social \
right — you can double-check it on the review screen"). For ordinary things (first name, city) \
just accept it.
- Voice is imperfect: if a name or a NON-sensitive number sounds unclear, confirm the spelling \
or read the digits back in small groups ("that's five-five-five, one-two-one-two?"). Never read \
a Social Security or immigration number aloud. Understand spoken money and counts ("fifteen \
hundred" is $1,500; "a couple" is 2).

PRIVACY (you handle sensitive information)
- NEVER say a Social Security number, immigration document number, or other sensitive value \
out loud — just confirm you have it ("Got it, I have your Social on file").
- Reassure them their information is private, this is free, and they can review and change \
everything before anything is submitted.

YOUR TOOLS
- save_answers: every time they give usable info, save EVERY field you can fill — even several \
at once. If they correct something, save the new value. IMPORTANT: NEVER infer or assume a \
name field value from another name answer. First name, middle name, and last name are always \
separate — only save a name field when the person explicitly stated THAT name. For example, \
if they said "Jacob" when asked for first name, save ONLY first name = "Jacob"; do NOT also \
save middle name or last name from that same answer.
- skip_fields: ONLY after you have asked an optional field and the person said they don't \
have it or want to skip it. NEVER silently skip any field — always ask first, then skip if \
they say so. Even optional fields (middle name, mailing address, email) must be asked.
- go_to_review: only when everything needed is captured; then congratulate them warmly.

WHEN TO GET A HUMAN
- You handle the whole application, but you know your limits. If the situation is complex or \
sensitive — a disability or long-term-care/nursing need, a tricky immigration situation, an \
appeal or a denial, or they're upset and want a real person — reassure them, finish what you \
can, and point them to their county Job and Family Services office or the Ohio Medicaid \
Consumer Hotline for the harder parts. Never abandon them mid-form.

AT THE END
- When you call go_to_review, tell them what's next in one short line: they'll see all their \
answers to check and approve, and then it becomes their completed application to submit.

Follow the form-specific guidance and any KNOWLEDGEBASE GUIDANCE you are given for this form. \
If guidance does not cover something — a rule, a dollar limit, a policy — say you are not sure \
and keep helping. Do not make up rules or numbers. You help complete and screen the \
application; you never make a final eligibility decision, and you never tell anyone not to apply."""


def _tools(form_id: str | None = None) -> list[dict]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "save_answers",
                "description": "Save one or more field values the person EXPLICITLY stated. Use the exact field_key in brackets from the form state. NEVER infer or guess name fields — only save first_name, middle_name, or last_name when the person directly said that specific name value. You may save multiple fields when the person volunteered several facts in one message.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "field_key": {"type": "string", "description": "Exact field_key, e.g. applicant.first_name"},
                                    "value": {"type": "string", "description": "The value to store. For dates use MM/DD/YYYY or natural language; for yes/no use yes or no."},
                                },
                                "required": ["field_key", "value"],
                            },
                        }
                    },
                    "required": ["items"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "skip_fields",
                "description": "Mark one or more OPTIONAL fields as intentionally blank. ONLY call this AFTER you have asked the person about the field and they said they don't have it, it doesn't apply, or they want to skip it. NEVER silently skip a field without asking — every field must be asked so the person can answer or skip it themselves.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "field_keys": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["field_keys"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "screen_income",
                "description": (
                    "Use when the person asks if income may be within Ohio Medicaid "
                    "2026 monthly guidelines. This is screening only, not a final "
                    "eligibility decision. Ask for missing category, household size, "
                    "or income before using it. If you only know a per-paycheck amount "
                    "and how often they're paid, pass that amount as monthly_income and "
                    "set pay_frequency — it will be converted to a monthly figure."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": [
                                "parent_caretaker",
                                "adult_19_64",
                                "child_with_insurance",
                                "pregnant",
                                "child_without_insurance",
                            ],
                            "description": "Likely Medicaid income category to screen.",
                        },
                        "household_size": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 12,
                            "description": "Household/family size from the application.",
                        },
                        "monthly_income": {
                            "type": "number",
                            "minimum": 0,
                            "description": "Income in dollars (monthly by default; the per-paycheck amount if pay_frequency is set).",
                        },
                        "pay_frequency": {
                            "type": "string",
                            "enum": ["weekly", "every_two_weeks", "twice_a_month", "monthly", "yearly"],
                            "description": "Optional. How often that income is received. If set, monthly_income is treated as the per-period amount and converted to a monthly figure.",
                        },
                    },
                    "required": ["category", "household_size", "monthly_income"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "screen_income_sources",
                "description": (
                    "Use after walking through ALL of the household's income — each job "
                    "(how often paid, or an hourly rate with hours per week), plus any "
                    "Social Security, unemployment, pension, child support, rental, or cash "
                    "help. Pass every source; it sums them to a monthly total and screens "
                    "against the 2026 Ohio Medicaid guideline. Screening only, never final."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["parent_caretaker", "adult_19_64", "child_with_insurance", "pregnant", "child_without_insurance"],
                            "description": "Likely Medicaid income category to screen.",
                        },
                        "household_size": {"type": "integer", "minimum": 1, "maximum": 12, "description": "Household/family size."},
                        "sources": {
                            "type": "array",
                            "description": "Every income source in the household.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "kind": {"type": "string", "enum": ["wages", "self_employment", "social_security", "unemployment", "pension", "child_support", "rental", "cash_help", "other"]},
                                    "amount": {"type": "number", "minimum": 0},
                                    "frequency": {"type": "string", "enum": ["weekly", "every_two_weeks", "twice_a_month", "monthly", "yearly", "hourly"]},
                                    "person": {"type": "string", "description": "Whose income (e.g. applicant, spouse)."},
                                    "before_tax": {"type": "boolean"},
                                    "hours_per_week": {"type": "number", "description": "Required only when frequency is hourly."},
                                },
                                "required": ["kind", "amount", "frequency"],
                            },
                        },
                    },
                    "required": ["category", "household_size", "sources"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ask",
                "description": (
                    "Call this EVERY turn, right before you ask the person a question, to declare "
                    "which ONE form field you're collecting next. You choose the most natural, "
                    "human order — but you MUST declare the field so the app can show the right "
                    "tappable answer buttons and save the reply to the correct field. Pass the "
                    "field_key from CURRENT FORM STATE. (Skip this only when calling go_to_review.)"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"field_key": {"type": "string", "description": "The field_key you are about to ask about."}},
                    "required": ["field_key"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "go_to_review",
                "description": "Call when every applicable field is filled or skipped and the person is ready to review.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    # The income-screening tools are Ohio-Medicaid specific (their chart is OH-2026) — only
    # offer them on forms that ship the chart, so they can't misfire on a non-Medicaid form.
    if not _supports_income_screening(form_id):
        tools = [t for t in tools if t["function"]["name"] not in ("screen_income", "screen_income_sources")]
    return tools


# ──────────────────────────── tool execution ────────────────────────────

def _exec_save_answers(db, session, schema, args: dict, input_mode: str) -> dict:
    items = args.get("items") or []
    results = []
    fields_by_key = {f["field_key"]: f for f in get_all_fields_from_schema(schema)}
    for it in items:
        fk = (it or {}).get("field_key", "")
        val = (it or {}).get("value", "")
        field = fields_by_key.get(fk) or {}
        results.append(svc.set_field(
            db, session, schema, fk, val,
            input_mode=input_mode,
            confidence=_agent_save_confidence(field, input_mode),
        ))
    out: dict = {"results": results}
    # Make a failed save impossible to ignore: the model must NOT claim it captured a
    # value that did not validate (e.g. a garbled date) — it has to ask again.
    failed = [r for r in results if not r.get("ok")]
    if failed:
        labels = ", ".join(str(r.get("label") or r.get("field_key")) for r in failed)
        out["not_saved"] = [{"field_key": r.get("field_key"), "label": r.get("label"), "error": r.get("error")} for r in failed]
        out["instruction"] = (
            f"These did NOT save and are still empty: {labels}. Do NOT say you have them. "
            "Tell the person briefly that you didn't quite catch it and ask again. For a date, "
            "ask for the full month, day, and year, then read the whole date back to confirm."
        )
    return out


def _exec_skip_fields(db, session, schema, args: dict) -> dict:
    keys = args.get("field_keys") or []
    results = [svc.set_field(db, session, schema, k, "", input_mode="typed") for k in keys]
    return {"results": results}


def _exec_screen_income(args: dict) -> dict:
    """Run deterministic ODM income screening without writing form answers."""
    from app.ai.odm_eligibility import screen_magi_income

    try:
        household_size = int(args.get("household_size", 0) or 0)
        monthly_income = float(args.get("monthly_income", 0) or 0)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": "invalid_number",
            "message": "Household size and monthly income must be numeric before screening.",
        }
    # If a per-paycheck amount + frequency was given, convert to monthly first.
    normalized = None
    frequency = str(args.get("pay_frequency", "") or "").strip()
    if frequency:
        from app.ai.odm_eligibility import monthly_from_pay

        conv = monthly_from_pay(monthly_income, frequency)
        if conv.get("ok"):
            monthly_income = conv["monthly_income"]
            normalized = conv
    result = screen_magi_income(
        category=str(args.get("category", "")),
        household_size=household_size,
        monthly_income=monthly_income,
    )
    if normalized:
        result["income_normalized_from"] = normalized
    return result


def _exec_screen_income_sources(args: dict) -> dict:
    """Aggregate every household income source, then screen the monthly total."""
    from app.ai.income import IncomeSource, screen_income_sources

    try:
        household_size = int(args.get("household_size", 0) or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_household_size"}
    sources: list[IncomeSource] = []
    for item in (args.get("sources") or []):
        if not isinstance(item, dict):
            continue
        sources.append(IncomeSource(
            kind=str(item.get("kind", "wages")),
            amount=item.get("amount", 0),
            frequency=str(item.get("frequency", "monthly")),
            person=str(item.get("person", "applicant")),
            before_tax=bool(item.get("before_tax", True)),
            hours_per_week=item.get("hours_per_week"),
        ))
    if not sources:
        return {"ok": False, "error": "no_income_sources"}
    return screen_income_sources(str(args.get("category", "")), household_size, sources)


def _prep_checklist(form_id: str, schema: dict) -> str:
    """Short startup checklist so users know what information to keep nearby.

    The ODM pack gets explicit Medicaid wording. Other future form packs receive
    a schema-derived checklist, which keeps the platform extensible without
    hard-coding every form's opening script in the agent.
    """
    if form_id == "ODM_07216":
        return (
            "It helps to have names and birth dates for household members, your "
            "address and phone, Social Security or immigration information if you "
            "have it, income and employer or pay details, insurance or Medicare "
            "information, and recent medical bills, pregnancy, or care details if "
            "those apply."
        )
    if form_id == "BH_SELF_REPORT_BATTERY":
        return (
            "You will not need documents for most of these self-report tools. It "
            "helps to be somewhere private and ready to answer symptom, safety, "
            "substance-use, and daily-functioning questions using the closest "
            "answer choice on screen or by voice."
        )

    field_keys = " ".join(f.get("field_key", "").lower() for f in get_all_fields_from_schema(schema))
    items: list[str] = ["names and birth dates for people on the form"]
    if any(token in field_keys for token in ("address", "phone", "email", "zip")):
        items.append("address and contact information")
    if any(token in field_keys for token in ("ssn", "social", "citizen", "immigration")):
        items.append("Social Security, citizenship, or immigration information if available")
    if any(token in field_keys for token in ("income", "employer", "wage", "pay", "job")):
        items.append("income, employer, and pay details")
    if any(token in field_keys for token in ("insurance", "medicare", "coverage")):
        items.append("insurance or coverage information")
    if any(token in field_keys for token in ("bill", "pregnant", "care", "disabled", "nursing")):
        items.append("medical bill, pregnancy, disability, or care details if they apply")
    if len(items) == 1:
        return f"It helps to have {items[0]} handy."
    return f"It helps to have {', '.join(items[:-1])}, and {items[-1]} handy."


def _opening_prompt(question: str, *, form_title: str = "this form", prep_checklist: str = "") -> str:
    """Human opening used when the LLM is unavailable during the first turn."""
    prep = prep_checklist or "It helps to have the basic information this form asks for handy."
    return (
        f"Hi, I'm Mia, a smart AI assistant for {form_title}. I'll help you fill it "
        "out by voice or typing, one question at a time. It usually takes about "
        f"10 to 15 minutes, and you'll review everything before anything is submitted. "
        f"{prep} You can ask me to explain anything. {question}"
    )


def _next_action_reply(schema: dict, answers: dict[str, Any], form_id: str = "", *, is_start: bool = False) -> str:
    """Return a deterministic spoken prompt when the model gives no final text.

    Tool-only turns happen with real models, especially after duplicate or corrected
    answers. The voice UI needs a concrete next question, not a generic "Okay!",
    otherwise it reopens the mic with no clear instruction and appears stuck.
    When the LLM is unavailable, this path should still sound like a helper,
    not a scripted acknowledgment loop.
    """
    missing = get_missing_applicable_fields("", answers, schema)
    if not missing:
        return "That's everything I need. Let's review your answers together."

    field = missing[0]
    try:
        from app.forms.prompts import get_field_override

        override = get_field_override(form_id, field["field_key"])
    except Exception:
        override = {}
    question = (
        override.get("question")
        or field.get("question_text")
        or f"Please provide your {field.get('label', field['field_key'])}."
    )
    if is_start:
        return _opening_prompt(
            question,
            form_title=svc._form_title(form_id, schema),
            prep_checklist=_prep_checklist(form_id, schema),
        )
    return question


def _deterministic_question(form_id: str, field: dict) -> str:
    """Plain, correct question text for ONE specific field.

    Used to override an off-script agent question so the spoken prompt always
    matches the field the answer is bound to. Without this, the agent can say
    "what is your last name?" while the answer binding still points at middle
    name, silently saving the answer to the wrong field.
    """
    try:
        from app.forms.prompts import get_field_override

        override = get_field_override(form_id, field["field_key"])
    except Exception:
        override = {}
    return (
        override.get("question")
        or field.get("question_text")
        or f"Please provide your {field.get('label', field['field_key'])}."
    )


# Generic label words that don't distinguish one field from another.
_LABEL_STOPWORDS = {
    "name", "number", "code", "optional", "if", "different", "the", "a", "an",
    "your", "of", "is", "are", "do", "you", "and", "or",
}


def _text_mentions_field(text: str, field: dict) -> bool:
    """True if ``text`` already references ``field`` by its distinguishing label word(s).

    Used to AVOID overriding an agent reply that is already asking the right field
    (e.g. the agent said "...and your middle name?" for the middle_name field, or a
    multi-save acknowledgment that ends with "what's your phone number?"). We match on
    the field's significant label tokens, ignoring generic words like "name"/"number"
    that are shared across many fields.
    """
    if not text:
        return False
    low = text.lower()
    label = str(field.get("label", "")).lower()
    # Full label phrase match first ("middle name", "mailing address").
    if label and label in low:
        return True
    significant = [w for w in re.split(r"[^a-z]+", label) if w and w not in _LABEL_STOPWORDS]
    return any(w in low for w in significant)


# ──────────────────────────── keyless fallback ────────────────────────────

def _turn_state(form_id: str, answers: dict, schema: dict) -> dict:
    missing_applicable = get_missing_applicable_fields(form_id, answers, schema)
    missing_required = get_missing_required_fields(form_id, answers, schema)
    nxt = missing_applicable[0] if missing_applicable else None
    return {
        "answered_count": svc._valid_answer_count(schema, answers),
        "missing_count": len(missing_applicable),
        "missing_required_count": len(missing_required),
        "total": len(get_all_fields_from_schema(schema)),
        "next_field_key": nxt["field_key"] if nxt else None,
        "_missing_applicable": missing_applicable,
        "_missing_required": missing_required,
    }


def _help_turn_response(db, session, schema: dict, field: dict, user_text: str, answers: dict[str, Any]) -> dict:
    """Return a same-field explanation without storing the user's question as data.

    This is the guardrail behind the "smart human helper" behavior. A person asking
    "what is WIC?" is asking for context, not answering yes/no; the agent should
    explain and keep the same field active instead of saving bad data or looping.
    """
    assistant_text = _field_help_reply(field, user_text, session.form_id)
    db.add(SessionMessage(session_id=session.id, role="assistant", content=assistant_text))
    db.commit()

    missing_applicable = get_missing_applicable_fields(session.form_id, answers, schema)
    missing_required = get_missing_required_fields(session.form_id, answers, schema)
    readiness = svc.get_session_readiness(db, session.id) or {"ready": False}
    done = bool(readiness["ready"])
    svc._set_collection_status(session, len(missing_applicable) == 0)
    db.commit()
    return {
        "assistant_message": assistant_text,
        "done": done,
        "go_to_review": False,
        "state": {
            "answered_count": svc._valid_answer_count(schema, answers),
            "missing_count": len(missing_applicable),
            "missing_required_count": len(missing_required),
            "total": len(get_all_fields_from_schema(schema)),
            "next_field_key": field["field_key"],
        },
        "next_field": _next_field_payload(db, field, answers),
        "answers": answers,
    }


def _rule_based_turn(db, session_id: str, user_text: str, input_mode: str) -> dict | None:
    """Deterministic fallback used when no OPENAI_API_KEY is configured.

    Drives the existing per-field extractor (svc.save_answer -> run_answer_step,
    which is rule-based without a key) so the documented "no AI key" default profile
    still has a working assistant. Returns the SAME shape as the LLM path.
    """
    from app.forms.questions import get_current_question_context

    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if not session:
        return None
    schema = svc._schema_for_session(session)
    is_start = (user_text or "").strip().lower() in ("", "__start__", "start")

    answers = svc._answers_map(db, session_id)
    ctx = get_current_question_context(session.form_id, answers, schema)

    if not is_start and ctx:
        field = ctx.get("field") or {}
        if field and _is_help_request(field, user_text):
            # A question like "what is WIC?" is not an answer to save. Explain
            # the current field and keep the same next_field binding active.
            assistant_text = _field_help_reply(field, user_text, session.form_id)
        else:
            res = svc.save_answer(db, session_id, ctx["field_key"], user_text, input_mode)
            answers = svc._answers_map(db, session_id)
            ctx = get_current_question_context(session.form_id, answers, schema)
            ack = (res.get("acknowledgment") or "Thanks.").strip() if res.get("success") \
                else (res.get("error") or "Let's try that again.").strip()
            if ack.lower() in {"got it", "got it.", "thanks", "thanks."}:
                ack = ""
            assistant_text = f"{ack} {ctx['question']}".strip() if ctx \
                else f"{ack} That's everything I need - let's review your answers.".strip()
    elif ctx:
        assistant_text = _opening_prompt(
            ctx["question"],
            form_title=svc._form_title(session.form_id, schema),
            prep_checklist=_prep_checklist(session.form_id, schema),
        )
    else:
        assistant_text = "Everything's filled in. Let's review your answers."

    answers = svc._answers_map(db, session_id)
    state = _turn_state(session.form_id, answers, schema)
    # Match the LLM path and the approval/PDF gate: "done" means the deterministic
    # readiness gate passes (all applicable fields answered/skipped AND valid AND
    # confident AND PDF-mappable) — not merely that fields are filled. Otherwise the
    # keyless agent could redirect to review while the approve button is disabled.
    readiness = svc.get_session_readiness(db, session_id) or {"ready": False}
    done = bool(readiness["ready"])
    svc._set_collection_status(session, len(state["_missing_applicable"]) == 0)
    db.commit()
    next_field = state["_missing_applicable"][0] if state["_missing_applicable"] else None
    state.pop("_missing_applicable"); state.pop("_missing_required")
    return {
        "assistant_message": assistant_text,
        "done": done,
        "go_to_review": done,
        "state": state,
        "next_field": _next_field_payload(db, next_field, answers),
        "answers": answers,
    }


# ──────────────────────────── main entry point ────────────────────────────

def run_agent_turn(db, session_id: str, user_text: str, input_mode: str = "voice", answered_field_key: str | None = None) -> dict | None:
    """Process one user turn through the conversational agent.

    Returns a dict {assistant_message, state, done}. None is reserved for a
    missing session/client construction failure; no-key deployments use the
    deterministic rule-based assistant path.
    """
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        # Keyless default profile: fall back to the deterministic per-field flow so
        # the assistant still works without an AI key (see .env.example / CLAUDE.md).
        return _rule_based_turn(db, session_id, user_text, input_mode)

    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if not session:
        return None
    schema = svc._schema_for_session(session)

    try:
        import httpx
        from openai import OpenAI
        # Bound each request so a slow/degraded OpenAI can't block the worker thread
        # (and its DB connection) far past the frontend's 45s budget.
        client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=httpx.Timeout(20.0, connect=5.0),
            max_retries=1,
        )
    except Exception:
        logger.warning("OpenAI client unavailable; using deterministic assistant fallback.", exc_info=True)
        return _rule_based_turn(db, session_id, user_text, input_mode)

    # An empty / "__start__" message is the opening trigger: the agent greets and
    # asks the first needed field instead of treating it as a real answer.
    is_start = (user_text or "").strip().lower() in ("", "__start__", "start")
    if not is_start:
        db.add(SessionMessage(session_id=session_id, role="user", content=user_text))
        db.commit()

    answers = svc._answers_map(db, session_id)
    # Deterministic capture by the EXPLICIT field the UI is answering (the question's field
    # key is sent with the answer). This binds the chip/question to its field instead of
    # guessing from text, so a yes/no or select answer can NEVER be dropped and re-asked —
    # the #1 cause of frustrating loops. The LLM can still save volunteered extra facts,
    # but the field that was actually asked gets first chance to save, skip, or confirm.
    captured = False
    confirmation_captured = False  # True when this turn was a read-back yes/no, not a new answer
    answered_field = None

    # ── Read-back confirmation (robust) ──────────────────────────────────────
    # A read-back field (voice date/phone/ZIP saved at low confidence) is pending
    # whenever _first_low_confidence_field finds one. If the user's reply is a clear
    # yes/no, resolve it on THAT field — regardless of which answered_field_key the
    # frontend sent. This makes confirmation immune to any frontend state race where
    # the key drifts (the #1 cause of "I confirmed my DOB but it wasn't saved").
    if not is_start:
        pending = _first_low_confidence_field(db, session_id, schema)
        if pending:
            pending_field, _pending_val = pending
            # A clear yes/no resolves the pending read-back. We check yn FIRST (a bare
            # "yes"/"no" is never a help request) so a confirmation can't be misrouted.
            yn = _coerce_yes_no(user_text, pending_field["field_key"])
            if yn is not None:
                captured = _handle_low_confidence_confirmation(
                    db, session, schema, pending_field["field_key"], user_text
                )
                if captured:
                    confirmation_captured = True
                    answers = svc._answers_map(db, session_id)

    if not confirmation_captured and not is_start and answered_field_key:
        answered_field = next((f for f in get_all_fields_from_schema(schema) if f["field_key"] == answered_field_key), None)
        if answered_field and _is_help_request(answered_field, user_text):
            return _help_turn_response(db, session, schema, answered_field, user_text, answers)
        fld = answered_field
        if fld and answered_field_key in answers:
            captured = _handle_low_confidence_confirmation(db, session, schema, answered_field_key, user_text)
            if captured:
                confirmation_captured = True
                answers = svc._answers_map(db, session_id)
        if not captured and fld and answered_field_key not in answers:
            ftype = fld.get("type", "text")
            raw = (user_text or "").strip().lower()
            if raw in _DIRECT_SKIP_WORDS:
                # The Skip button and spoken "skip" must persist without waiting for the
                # LLM to infer skip_fields, otherwise optional questions can loop.
                captured = bool(svc.set_field(db, session, schema, answered_field_key, user_text, input_mode=input_mode).get("ok"))
            elif ftype == "boolean":
                yn = _coerce_yes_no(user_text, answered_field_key)
                if yn is not None:
                    svc.set_field(db, session, schema, answered_field_key, "yes" if yn else "no", input_mode=input_mode)
                    captured = True
            else:
                # Bind the answer to the field that was actually asked, BEFORE the model runs,
                # so the guidance + next_field reflect the truly-next field (no one-turn lag).
                # One field is asked at a time, so the utterance is a single value; set_field
                # validates it — a noisy/combined utterance that fails validation falls through
                # to the model's extractor (which can split it).
                captured = bool(svc.set_field(
                    db, session, schema, answered_field_key, user_text,
                    input_mode=input_mode,
                    confidence=_agent_save_confidence(fld, input_mode),
                ).get("ok"))
            if captured:
                answers = svc._answers_map(db, session_id)

    form_ctx = _build_form_context(schema, answers)
    # Case-manager working memory: what's known (never re-ask), auto-filled, heard with
    # low confidence (read back), looks off (double-check), and still needed.
    from app.ai.case_profile import build_case_profile, render_case_notes
    answer_rows = db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
    case_notes = render_case_notes(build_case_profile(session.form_id, schema, answer_rows))
    system = SYSTEM_PROMPT.format(form_title=svc._form_title(session.form_id, schema))
    persona = _form_persona(session.form_id)
    if persona:
        system = f"{system}\n\n# Guidance specific to THIS form (follow it closely):\n{persona}"
    next_field = _next_missing(session.form_id, schema, answers)
    kb_context = _kb_context_for_turn(db, session.form_id, next_field, user_text)
    field_guidance = _next_field_guidance(session.form_id, next_field)

    # Replay recent dialogue for continuity.
    history = (
        db.query(SessionMessage)
        .filter(SessionMessage.session_id == session_id)
        .order_by(SessionMessage.id.desc())
        .limit(_HISTORY_TURNS)
        .all()
    )
    history = list(reversed(history))

    messages: list[dict] = [{"role": "system", "content": system}]
    messages.append({"role": "system", "content": f"CURRENT FORM STATE:\n{form_ctx}"})
    messages.append({"role": "system", "content": case_notes})
    if field_guidance:
        messages.append({"role": "system", "content": field_guidance})
    if kb_context:
        messages.append({"role": "system", "content": kb_context})
    for m in history:
        messages.append({"role": m.role, "content": m.content})

    if is_start:
        form_title = svc._form_title(session.form_id, schema)
        prep_checklist = _prep_checklist(session.form_id, schema)
        messages.append({
            "role": "system",
            "content": (
                "The session just started. Open warmly and naturally — do NOT read a long list. "
                "In 2-3 short, friendly sentences: greet them and say you'll fill this out together "
                "by voice or typing; that it takes about 10-15 minutes, it's free and private, and "
                "they'll review everything before anything is submitted. Then, in the SAME message, "
                "clearly ask the FIRST thing still needed — usually their first name — as a direct "
                "question. End on that question so they know exactly what to answer. Keep it human "
                "and brief, like a real person, not a script."
            ),
        })

        messages.append({
            "role": "system",
            "content": (
                "Startup requirement: your first spoken message MUST say you are a smart AI "
                f"assistant helping them complete {form_title}; mention voice or typing, the "
                "10 to 15 minute estimate, and that they review everything before submission. "
                f"Briefly say what to keep nearby: {prep_checklist} Tell them they can ask you "
                "to explain any question. End with the first needed form question."
            ),
        })

    go_review = False
    assistant_text = ""
    declared_field_key: str | None = None  # the field the agent says it's asking this turn
    info_tool_called = False  # an informational tool (income screening) produced a reply this turn
    model = settings.OPENAI_MODEL
    turn_start = time.monotonic()

    # Confirmation turns (user said yes/no to a read-back) are fully deterministic —
    # bypass the LLM entirely so it never sees "Yes" in context and re-asks the same field.
    if confirmation_captured:
        return _confirmation_turn_reply(db, session, session_id, schema, answers)

    try:
        for _ in range(_MAX_TOOL_ROUNDS):
            # Wall-clock budget across tool rounds — return a reply before the
            # frontend's 45s abort so the user never sees an indefinite hang.
            if time.monotonic() - turn_start > 35:
                logger.info("Agent turn hit time budget; returning current reply.")
                break
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=_tools(session.form_id),
                temperature=0.3,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                assistant_text = (msg.content or "").strip()
                break

            # Record the assistant's tool-call turn, then execute each tool.
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    if name == "save_answers":
                        out = _exec_save_answers(db, session, schema, args, input_mode)
                    elif name == "skip_fields":
                        out = _exec_skip_fields(db, session, schema, args)
                    elif name == "screen_income":
                        info_tool_called = True
                        out = _exec_screen_income(args)
                    elif name == "screen_income_sources":
                        info_tool_called = True
                        out = _exec_screen_income_sources(args)
                    elif name == "go_to_review":
                        # Match the review/approval gate exactly: the agent can
                        # request review only after deterministic readiness passes.
                        readiness = svc.get_session_readiness(db, session_id)
                        if not readiness or not readiness["ready"]:
                            go_review = False
                            out = {
                                "ok": False,
                                "error": "Cannot review yet; readiness blockers remain.",
                                "blockers": (readiness or {}).get("blockers", [])[:8],
                            }
                        else:
                            go_review = True
                            out = {"ok": True}
                    elif name == "ask":
                        # The agent declares which field it's about to ask — chips + answer
                        # binding follow this, so the model keeps a human order without the UI
                        # ever guessing the field.
                        fk_to_ask = str(args.get("field_key") or "").strip() or None
                        # Guard: enforce that the agent asks fields in schema order.
                        # (1) Cannot ask an already-answered field.
                        # (2) Cannot skip over an unanswered field to ask a later one.
                        if fk_to_ask:
                            current_answers = svc._answers_map(db, session_id)
                            from app.forms.missing_fields import _field_answered as _fa
                            all_fields_list = get_all_fields_from_schema(schema)
                            fk_schema = next(
                                (f for f in all_fields_list if f["field_key"] == fk_to_ask),
                                None,
                            )
                            next_missing = _next_missing(session.form_id, schema, current_answers)
                            next_missing_key = next_missing["field_key"] if next_missing else None

                            if fk_schema and _fa(fk_schema, current_answers):
                                # Already answered — redirect to actual next missing.
                                out = {
                                    "ok": False,
                                    "error": (
                                        f"Field '{fk_to_ask}' is already filled — do not ask for it again. "
                                        f"The next unanswered field is '{next_missing_key}'. Ask that one instead."
                                    ),
                                }
                            elif next_missing_key and fk_to_ask != next_missing_key:
                                # Trying to skip over a field that hasn't been asked yet.
                                out = {
                                    "ok": False,
                                    "error": (
                                        f"You cannot skip to '{fk_to_ask}' — field '{next_missing_key}' "
                                        f"({next_missing.get('label', next_missing_key)}) "
                                        f"comes first and has not been answered yet. "
                                        f"Ask '{next_missing_key}' now."
                                    ),
                                }
                            else:
                                declared_field_key = fk_to_ask
                                out = {"ok": True}
                        else:
                            declared_field_key = None
                            out = {"ok": True}
                    else:
                        out = {"error": f"unknown tool {name}"}
                except Exception:
                    # One bad tool call must not abort the whole turn or discard already
                    # committed items — surface the error to the model and continue.
                    logger.warning("Agent tool %s failed mid-turn; rolled back partial work.", name, exc_info=True)
                    db.rollback()
                    out = {"error": "Could not complete that action; please try again."}
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(out),
                })

            # Refresh the form state the model sees after the writes.
            answers = svc._answers_map(db, session_id)
            messages.append({
                "role": "system",
                "content": "UPDATED FORM STATE after your tool calls:\n" + _build_form_context(schema, answers),
            })
    except Exception:
        # The model is unavailable (e.g. OpenAI 429 / out of quota, timeout, outage). Degrade
        # gracefully to the deterministic per-field flow instead of erroring — the form still
        # gets filled, one field at a time, with the chips/binding intact.
        logger.warning("Agent LLM unavailable; degrading to the deterministic per-field flow.", exc_info=True)
        # Don't lose the answer: if the explicit-field capture above didn't already save it,
        # save it now via set_field (which never calls the model).
        if not is_start and answered_field_key and not captured:
            try:
                fld = next((f for f in get_all_fields_from_schema(schema) if f["field_key"] == answered_field_key), {})
                svc.set_field(
                    db, session, schema, answered_field_key, user_text,
                    input_mode=input_mode,
                    confidence=_agent_save_confidence(fld, input_mode),
                )
                answers = svc._answers_map(db, session_id)
            except Exception:
                logger.warning("Fallback save failed for %s.", answered_field_key, exc_info=True)
        assistant_text = ""  # filled below by the deterministic next-question helper

    if not assistant_text:
        assistant_text = _next_action_reply(schema, svc._answers_map(db, session_id), session.form_id, is_start=is_start)

    # Persist the assistant reply.
    db.add(SessionMessage(session_id=session_id, role="assistant", content=assistant_text))
    db.commit()

    answers = svc._answers_map(db, session_id)
    missing_applicable = get_missing_applicable_fields(session.form_id, answers, schema)
    missing_required = get_missing_required_fields(session.form_id, answers, schema)
    readiness = svc.get_session_readiness(db, session_id) or {"ready": False}
    # Never report done until the same gate used by review/approval/PDF would pass.
    # Required-only completion strands users because optional applicable fields still
    # have to be answered or explicitly skipped before completion.
    done = bool(readiness["ready"])
    go_review = go_review and done
    svc._set_collection_status(session, len(missing_applicable) == 0)
    db.commit()

    # next_field = the field the agent SAID it's asking (via the 'ask' tool). The agent picks
    # the human order; we trust its declaration so the chips and the answer binding always
    # match the question. Fall back to the next missing field only if it didn't declare (or
    # declared one that's already answered).
    confirm_next = _first_low_confidence_field(db, session_id, schema)
    missing_by_key = {f["field_key"]: f for f in missing_applicable}
    if confirm_next:
        confirm_field, confirm_value = confirm_next
        # Confirmation is a readiness blocker, so keep both the spoken prompt and UI
        # binding on that same field until the person says yes or corrects it.
        assistant_text = _readback_prompt(confirm_field, confirm_value)
        last_msg = (
            db.query(SessionMessage)
            .filter(SessionMessage.session_id == session_id, SessionMessage.role == "assistant")
            .order_by(SessionMessage.id.desc())
            .first()
        )
        if last_msg:
            last_msg.content = assistant_text
            db.commit()
        nxt = confirm_field
        next_payload = _confirmation_field_payload(confirm_field)
    else:
        # The spoken question and the answer binding MUST point at the same field.
        # The `ask` ordering guard only sets declared_field_key when it equals the
        # next missing field, so any declared field is guaranteed in-order. When the
        # agent skipped `ask` (or its out-of-order ask was rejected) declared is None,
        # and the agent's free text may be asking the WRONG field — so we override the
        # spoken question with a deterministic one for the true next field. This is the
        # fix for "agent says 'what is your last name?' but the answer is bound to
        # middle name", which silently saved answers to the wrong field.
        deterministic_next = _prioritized_next(session.form_id, answers, missing_applicable)
        declared_field = missing_by_key.get(declared_field_key) if declared_field_key else None
        on_script = (
            declared_field is not None
            and deterministic_next is not None
            and declared_field["field_key"] == deterministic_next["field_key"]
        )
        if on_script:
            nxt = declared_field
        else:
            nxt = deterministic_next
            # Only override the agent's spoken text when this turn shows the BUG SIGNATURE:
            # the user just answered one field and we have ADVANCED to a different field, yet
            # the agent's free text may still be asking the wrong one. We deliberately do NOT
            # override informational replies (income screening), inline clarifications that stay
            # on the same field, or replies that already name the next field — those are the
            # regressions an earlier review caught.
            advanced = (
                answered_field_key is not None
                and nxt is not None
                and answered_field_key != nxt["field_key"]
                and answered_field_key in answers  # the answered field actually saved
            )
            already_asks_next = nxt is not None and _text_mentions_field(assistant_text, nxt)
            should_override = (
                nxt is not None
                and advanced
                and not info_tool_called
                and not already_asks_next
            )
            if should_override:
                forced_q = _deterministic_question(session.form_id, nxt)
                if forced_q.strip() and forced_q.strip() != (assistant_text or "").strip():
                    logger.info(
                        "Off-script question (declared=%s, answered=%s) overridden with deterministic ask for '%s'.",
                        declared_field_key, answered_field_key, nxt["field_key"],
                    )
                    assistant_text = forced_q
                    last_msg = (
                        db.query(SessionMessage)
                        .filter(SessionMessage.session_id == session_id, SessionMessage.role == "assistant")
                        .order_by(SessionMessage.id.desc())
                        .first()
                    )
                    if last_msg:
                        last_msg.content = assistant_text
                        db.commit()
        next_payload = _next_field_payload(db, nxt, answers)
    return {
        "assistant_message": assistant_text,
        "done": done,
        "go_to_review": go_review,
        "state": {
            "answered_count": svc._valid_answer_count(schema, answers),
            "missing_count": len(missing_applicable),
            "missing_required_count": len(missing_required),
            "total": len(get_all_fields_from_schema(schema)),
            "next_field_key": nxt["field_key"] if nxt else None,
        },
        "next_field": next_payload,
        "answers": answers,
    }
