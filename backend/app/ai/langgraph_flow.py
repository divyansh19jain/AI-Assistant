"""
LangGraph-based AI assistant flow for the form completion session.

Nodes are implemented as plain Python functions (synchronous).  The LangGraph
StateGraph is compiled once at import time when langgraph is available; if the
import fails the synchronous orchestrator run_answer_step() is used directly.

OpenAI (via LangChain, see app.ai.llm) powers answer extraction, question
rephrasing, and the "help / explain" intent when OPENAI_API_KEY is set; every
step falls back gracefully to rule-based logic when it is not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.ai.answer_extractor import extract_answer, ExtractionResult
from app.ai.question_rewriter import rewrite_question
from app.forms.questions import get_current_question_context
from app.forms.missing_fields import get_missing_required_fields

logger = logging.getLogger(__name__)


@dataclass
class AssistantState:
    form_id: str
    answers: dict[str, Any] = field(default_factory=dict)
    current_field: dict | None = None
    current_question: str = ""
    last_raw_answer: str = ""
    last_extraction: ExtractionResult | None = None
    attempt: int = 1
    is_complete: bool = False
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def node_determine_next_question(state: AssistantState) -> AssistantState:
    """Select the next missing required field and build its question text."""
    ctx = get_current_question_context(state.form_id, state.answers)
    if ctx is None:
        state.is_complete = True
        state.current_field = None
        state.current_question = ""
    else:
        state.current_field = ctx["field"]
        state.current_question = rewrite_question(
            ctx["field"], state.answers, state.attempt
        )
        state.is_complete = False
    return state


def node_extract_answer(state: AssistantState) -> AssistantState:
    """Extract and validate the user's raw answer via rule-based + Claude."""
    if not state.current_field or not state.last_raw_answer:
        return state

    result = extract_answer(state.current_field, state.last_raw_answer)
    state.last_extraction = result

    if result.needs_clarification:
        state.current_question = result.clarification_question or state.current_question
        state.attempt += 1
        state.error_message = result.clarification_question
    else:
        # Commands and pending-confirmation values are NOT stored here.
        if (
            result.value is not None
            and not result.is_command
            and not result.needs_confirmation
        ):
            state.answers[state.current_field["field_key"]] = result.value
        state.attempt = 1
        state.error_message = None

    return state


# ---------------------------------------------------------------------------
# LangGraph compiled graph (optional — requires langgraph package)
# ---------------------------------------------------------------------------

_compiled_graph = None

def _build_graph():
    """Compile the LangGraph StateGraph.  Returns None on import error."""
    try:
        from langgraph.graph import StateGraph, END

        graph = StateGraph(AssistantState)
        graph.add_node("extract_answer", node_extract_answer)
        graph.add_node("determine_question", node_determine_next_question)
        # Single pass: process the submitted answer, then pick the next question.
        # If the answer needs clarification, stop and re-ask (don't advance).
        graph.set_entry_point("extract_answer")
        graph.add_conditional_edges(
            "extract_answer",
            lambda s: END if s.error_message else "determine_question",
        )
        graph.add_edge("determine_question", END)
        return graph.compile()
    except Exception:
        logger.debug("LangGraph StateGraph unavailable; using synchronous orchestrator.")
        return None


try:
    _compiled_graph = _build_graph()
except Exception:
    _compiled_graph = None


# ---------------------------------------------------------------------------
# Public entry point used by the session service
# ---------------------------------------------------------------------------

def run_answer_step(
    form_id: str,
    current_answers: dict,
    field_key: str,
    raw_answer: str,
) -> dict:
    """
    Process a single answer submission and return updated state.

    Tries the LangGraph compiled graph first; falls back to the plain
    synchronous orchestrator if the graph is unavailable.
    """
    from app.forms.service import get_field

    field = get_field(field_key, form_id)
    if not field:
        return {
            "success": False,
            "error": f"Unknown field: {field_key}",
            "answers": current_answers,
            "next_question": None,
        }

    # Help / explain intent: the user asked a question instead of answering.
    # Respond with an explanation and DO NOT store anything or advance.
    from app.ai.help_intent import classify_intent, explain_field

    if classify_intent(field, raw_answer) == "help":
        explanation = explain_field(field, raw_answer)
        next_ctx = get_current_question_context(form_id, current_answers)
        return {
            "success": False,
            # `error` is the message the frontend shows + speaks when not
            # advancing; reuse it so help answers render with zero frontend change.
            "error": explanation,
            "is_help": True,
            "assistant_message": explanation,
            "answers": current_answers,
            "extracted_value": None,
            "confidence": 0.0,
            "needs_clarification": True,
            "next_question": next_ctx,
            "missing_count": len(get_missing_required_fields(form_id, current_answers)),
        }

    state = AssistantState(
        form_id=form_id,
        answers=dict(current_answers),
        last_raw_answer=raw_answer,
        current_field=field,
        attempt=1,
    )

    if _compiled_graph is not None:
        try:
            result = _compiled_graph.invoke(state)
            # LangGraph may return a dict instead of AssistantState
            if isinstance(result, dict):
                state = AssistantState(**{k: v for k, v in result.items() if k in AssistantState.__dataclass_fields__})
            else:
                state = result
        except Exception:
            logger.warning("LangGraph invocation failed; falling back to synchronous orchestrator.", exc_info=True)
            state = _run_synchronous(state)
    else:
        state = _run_synchronous(state)

    if state.error_message:
        return {
            "success": False,
            "error": state.error_message,
            "answers": current_answers,
            "extracted_value": None,
            "confidence": 0.0,
            "needs_clarification": True,
            "next_question": state.current_question,
        }

    ext = state.last_extraction

    # UI/voice command word (e.g. "send") — ignore it, don't advance, stay on
    # the same field silently.
    if ext and ext.is_command:
        return {
            "success": False,
            "error": None,
            "is_command": True,
            "answers": current_answers,
            "extracted_value": None,
            "confidence": 0.0,
            "needs_clarification": False,
            "next_question": get_current_question_context(form_id, current_answers),
        }

    # Smart-confirm: plausible but low-confidence — ask the user to confirm
    # before saving. Carry the pending value so the frontend can resubmit it.
    if ext and ext.needs_confirmation:
        return {
            "success": False,
            "error": ext.clarification_question,
            "needs_confirmation": True,
            "pending_value": ext.value,
            "answers": current_answers,
            "extracted_value": ext.value,
            "confidence": ext.confidence,
            "needs_clarification": False,
            "next_question": get_current_question_context(form_id, current_answers),
        }

    next_ctx = get_current_question_context(form_id, state.answers)

    return {
        "success": True,
        "error": None,
        "answers": state.answers,
        "extracted_value": state.last_extraction.value if state.last_extraction else None,
        "confidence": state.last_extraction.confidence if state.last_extraction else 1.0,
        "needs_clarification": False,
        "is_complete": state.is_complete,
        "next_question": next_ctx,
        "missing_count": len(get_missing_required_fields(form_id, state.answers)),
    }


def _run_synchronous(state: AssistantState) -> AssistantState:
    """Plain sequential orchestrator — no LangGraph dependency."""
    state = node_extract_answer(state)
    if not state.error_message:
        state = node_determine_next_question(state)
    return state
