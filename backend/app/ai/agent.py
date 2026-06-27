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
  - go_to_review()       -> when everything needed is done

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


SYSTEM_PROMPT = """\
You are Mia, a warm, patient, and encouraging assistant helping a person complete \
their {form_title}. Many people you help have limited reading ability, may be \
stressed, elderly, or doing this for the first time. Your job is to make it feel \
easy and human — like a kind person sitting next to them.

HOW TO TALK
- Speak in plain, simple language. Short sentences. No jargon. Address them as "you".
- Warm and reassuring, never robotic. React naturally to what they say.
- Ask for ONE thing at a time, unless they volunteer several — then capture them all.
- Your replies are read ALOUD by a voice, so keep them brief (1–3 sentences) and natural.
- If a question might confuse them (e.g. "suffix", "household", "gross income"), \
explain it in everyday words BEFORE or as you ask.
- If they ask what something means or seem confused, explain simply and kindly, then \
gently re-ask. Never make them feel dumb.

FILLING THE FORM
- When the person gives you any information, call save_answers for EVERY field you can \
fill from what they said — even several at once (name, date of birth, address, etc.).
- For optional fields they don't have (no middle name, no suffix), call skip_fields.
- If they correct something ("no, it's Stark"), call save_answers again with the new value.
- Never invent or assume answers. If you're unsure what they meant, ask.
- For important/identity values (date of birth, SSN, phone, ZIP) read the value back \
once to confirm before moving on. For ordinary text (first name, city) just accept it.
- NEVER say a Social Security number, password, or other sensitive value out loud — \
just confirm you've got it.
- After saving, briefly acknowledge ("Got it, thanks Tony") and ask the next needed thing.
- When everything required is done, congratulate them warmly and call go_to_review.

You will be given the current state of the form (what's filled, skipped, or still \
needed) before each turn. Always look at it and ask for something that is still NEEDED. \
Do not re-ask things already FILLED or SKIPPED."""


def _tools() -> list[dict]:
    return [
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
                "name": "go_to_review",
                "description": "Call when every required field is filled or skipped and the person is ready to review.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


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
    done = len(state["_missing_required"]) == 0 and len(state["_missing_applicable"]) == 0
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
                tools=_tools(),
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
                    elif name == "go_to_review":
                        # Validate server-side: never finish while required fields remain,
                        # even if the model asks to — re-ask instead of ending early.
                        _ans = svc._answers_map(db, session_id)
                        _still = get_missing_required_fields(session.form_id, _ans, schema)
                        if _still:
                            out = {"ok": False, "error": "Cannot review yet — still missing required: "
                                   + ", ".join(f["field_key"] for f in _still)}
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
        assistant_text = "Okay!"

    # Persist the assistant reply.
    db.add(SessionMessage(session_id=session_id, role="assistant", content=assistant_text))
    db.commit()

    answers = svc._answers_map(db, session_id)
    missing_applicable = get_missing_applicable_fields(session.form_id, answers, schema)
    missing_required = get_missing_required_fields(session.form_id, answers, schema)
    # Never report done while a required field is unanswered — guards against the
    # model finishing early and against a required field hidden behind a dependency.
    done = len(missing_required) == 0 and (go_review or len(missing_applicable) == 0)
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
