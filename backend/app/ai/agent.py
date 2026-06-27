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

Falls back gracefully: if no OPENAI_API_KEY is configured, run_agent_turn returns
None so the caller can use the legacy per-field flow.

🔒 PHI: the patient's words are never logged. Sensitive field VALUES are never sent
back into the model context or spoken — only the fact that they're filled.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.core.config import get_settings
from app.db.models import FormSession, SessionMessage
from app.forms.service import get_all_fields_from_schema
from app.forms.missing_fields import (
    get_missing_applicable_fields,
    get_missing_required_fields,
    is_field_applicable,
)
from app.sessions import service as svc

logger = logging.getLogger(__name__)

SKIPPED = "__skipped__"
_MAX_TOOL_ROUNDS = 6           # safety cap on tool-call/▸model ping-pong per turn
_HISTORY_TURNS = 24            # how many prior user/assistant messages to replay


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
    return "filled", val


def _build_form_context(schema: dict, answers: dict[str, Any]) -> str:
    """A compact, section-grouped snapshot of the form for the system prompt."""
    section_titles = {s["section_key"]: s.get("section_title", s["section_key"]) for s in schema.get("sections", [])}
    lines: list[str] = []
    current_section = None
    for field in get_all_fields_from_schema(schema):
        if not is_field_applicable(field, answers):
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


def _next_missing(schema: dict, answers: dict[str, Any]) -> dict | None:
    missing = get_missing_applicable_fields("", answers, schema)
    return missing[0] if missing else None


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
        "NEXT FIELD GUIDANCE:",
        f"- field_key: {field['field_key']}",
        f"- question_to_ask: {question}",
    ]
    if help_text:
        lines.append(f"- plain_language_help: {help_text}")
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
- Warm and human; react naturally to what they say. Keep each reply to 1–3 sentences.
- Address them as "you", and use their first name once you know it.
- Explain a confusing term in plain words as you ask it ("Gross pay just means the \
amount before taxes come out").

HOW YOU WORK (like a real case manager, not a survey)
- Have a natural conversation. If they give several facts in one breath, capture them ALL.
- Always read CURRENT FORM STATE and ask only for what is still NEEDED. Never re-ask \
something already FILLED or SKIPPED.
- When NEXT FIELD GUIDANCE is provided, use its exact question wording and plain-language help.
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
- Read date of birth, SSN, phone, and ZIP back once to confirm before moving on. For ordinary \
things (first name, city) just accept it.

PRIVACY (you handle sensitive information)
- NEVER say a Social Security number, immigration document number, or other sensitive value \
out loud — just confirm you have it ("Got it, I have your Social on file").
- Reassure them their information is private, this is free, and they can review and change \
everything before anything is submitted.

YOUR TOOLS
- save_answers: every time they give usable info, save EVERY field you can fill — even several \
at once. If they correct something, save the new value.
- skip_fields: for optional things they don't have ("no middle name").
- go_to_review: only when everything needed is captured; then congratulate them warmly.

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
                "description": "Save one or more field values the person provided. Use the exact field_key in brackets from the form state. You may pass several at once.",
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
                "description": "Mark one or more OPTIONAL fields as intentionally blank (the person has none / it doesn't apply).",
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
                "name": "go_to_review",
                "description": "Call when every applicable field is filled or skipped and the person is ready to review.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    # screen_income is Ohio-Medicaid specific (its chart is OH-2026) — only offer it on
    # forms that ship the chart, so it can't misfire on a non-Medicaid form.
    if not _supports_income_screening(form_id):
        tools = [t for t in tools if t["function"]["name"] != "screen_income"]
    return tools


# ──────────────────────────── tool execution ────────────────────────────

def _exec_save_answers(db, session, schema, args: dict, input_mode: str) -> dict:
    items = args.get("items") or []
    results = []
    for it in items:
        fk = (it or {}).get("field_key", "")
        val = (it or {}).get("value", "")
        results.append(svc.set_field(db, session, schema, fk, val, input_mode=input_mode))
    return {"results": results}


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


def _next_action_reply(schema: dict, answers: dict[str, Any], form_id: str = "") -> str:
    """Return a deterministic spoken prompt when the model gives no final text.

    Tool-only turns happen with real models, especially after duplicate or corrected
    answers. The voice UI needs a concrete next question, not a generic "Okay!",
    otherwise it reopens the mic with no clear instruction and appears stuck.
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
    return f"Got it. {question}"


# ──────────────────────────── keyless fallback ────────────────────────────

def _turn_state(form_id: str, answers: dict, schema: dict) -> dict:
    missing_applicable = get_missing_applicable_fields(form_id, answers, schema)
    missing_required = get_missing_required_fields(form_id, answers, schema)
    nxt = missing_applicable[0] if missing_applicable else None
    return {
        "answered_count": len([k for k, v in answers.items() if v not in (None, "")]),
        "missing_count": len(missing_applicable),
        "missing_required_count": len(missing_required),
        "total": len(get_all_fields_from_schema(schema)),
        "next_field_key": nxt["field_key"] if nxt else None,
        "_missing_applicable": missing_applicable,
        "_missing_required": missing_required,
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
        res = svc.save_answer(db, session_id, ctx["field_key"], user_text, input_mode)
        answers = svc._answers_map(db, session_id)
        ctx = get_current_question_context(session.form_id, answers, schema)
        ack = (res.get("acknowledgment") or "Thanks.").strip() if res.get("success") \
            else (res.get("error") or "Let's try that again.").strip()
        assistant_text = f"{ack} {ctx['question']}".strip() if ctx \
            else f"{ack} That's everything I need — let's review your answers.".strip()
    elif ctx:
        assistant_text = f"Hi, I'll help you fill this out together. {ctx['question']}"
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
    state.pop("_missing_applicable"); state.pop("_missing_required")
    return {
        "assistant_message": assistant_text,
        "done": done,
        "go_to_review": done,
        "state": state,
        "answers": answers,
    }


# ──────────────────────────── main entry point ────────────────────────────

def run_agent_turn(db, session_id: str, user_text: str, input_mode: str = "voice") -> dict | None:
    """Process one user turn through the conversational agent.

    Returns a dict {assistant_message, state, done} or None if the agent is
    unavailable (no API key) so the caller can fall back to the legacy flow.
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
        logger.warning("OpenAI client unavailable; agent disabled.", exc_info=True)
        return None

    # An empty / "__start__" message is the opening trigger: the agent greets and
    # asks the first needed field instead of treating it as a real answer.
    is_start = (user_text or "").strip().lower() in ("", "__start__", "start")
    if not is_start:
        db.add(SessionMessage(session_id=session_id, role="user", content=user_text))
        db.commit()

    answers = svc._answers_map(db, session_id)
    form_ctx = _build_form_context(schema, answers)
    system = SYSTEM_PROMPT.format(form_title=svc._form_title(session.form_id, schema))
    persona = _form_persona(session.form_id)
    if persona:
        system = f"{system}\n\n# Guidance specific to THIS form (follow it closely):\n{persona}"
    next_field = _next_missing(schema, answers)
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
    if field_guidance:
        messages.append({"role": "system", "content": field_guidance})
    if kb_context:
        messages.append({"role": "system", "content": kb_context})
    for m in history:
        messages.append({"role": m.role, "content": m.content})

    if is_start:
        messages.append({
            "role": "system",
            "content": (
                "The session just started. Greet the person warmly in ONE short sentence, "
                "say you'll help them fill this out together, then ask for the FIRST thing "
                "that is still NEEDED. Keep it brief, friendly, and easy to understand."
            ),
        })

    go_review = False
    assistant_text = ""
    model = settings.OPENAI_MODEL
    turn_start = time.monotonic()

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
                        out = _exec_screen_income(args)
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
        logger.warning("Agent turn failed; returning a safe fallback message.", exc_info=True)
        assistant_text = "Sorry, I had a little trouble there. Could you say that again?"

    if not assistant_text:
        assistant_text = _next_action_reply(schema, svc._answers_map(db, session_id), session.form_id)

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

    nxt = missing_applicable[0] if missing_applicable else None
    return {
        "assistant_message": assistant_text,
        "done": done,
        "go_to_review": go_review,
        "state": {
            "answered_count": len([k for k, v in answers.items() if v not in (None, "")]),
            "missing_count": len(missing_applicable),
            "missing_required_count": len(missing_required),
            "total": len(get_all_fields_from_schema(schema)),
            "next_field_key": nxt["field_key"] if nxt else None,
        },
        "answers": answers,
    }
