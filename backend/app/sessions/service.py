import json
import uuid
import logging
from typing import Any
from sqlalchemy.orm import Session as DBSession
from app.db.models import Form, FormSession, FormAnswer
from app.db.session import get_db
from app.emr.schemas import EMRPatient
from app.forms.service import (
    get_all_fields,
    get_all_fields_from_schema,
    get_field_from_schema,
    load_form_schema,
)
from app.forms import cache as form_cache
from app.forms.mapper import prefill_from_emr
from app.forms.missing_fields import (
    get_missing_applicable_fields,
    get_missing_required_fields,
    is_field_applicable,
)
from app.forms.questions import get_current_question_context
from app.forms.readiness import build_session_readiness
from app.ai.langgraph_flow import run_answer_step
from app.patients.service import get_patient_by_id

logger = logging.getLogger(__name__)


def create_session(
    db: DBSession,
    form_id: str,
    patient_id: str | None,
    manual_mode: bool,
) -> dict:
    session_id = str(uuid.uuid4())
    prefilled: dict[str, Any] = {}
    mock_mode = False
    patient: EMRPatient | None = None
    schema = _load_published_schema(db, form_id)

    if patient_id and not manual_mode:
        patient = get_patient_by_id(patient_id)
        if patient:
            from app.emr.factory import get_emr_adapter
            mock_mode = get_emr_adapter().is_mock
            prefilled = prefill_from_emr(patient, form_id, schema=schema)

    session = FormSession(
        id=session_id,
        form_id=form_id,
        schema_json=json.dumps(schema),
        patient_external_id=patient_id,
        status="active",
        mock_mode=mock_mode,
    )
    db.add(session)

    for field_key, data in prefilled.items():
        answer = FormAnswer(
            session_id=session_id,
            field_key=field_key,
            value_json=data["value_json"],
            raw_answer=str(data["value"]),
            source=data["source"],
            confidence=data["confidence"],
        )
        db.add(answer)

    db.commit()
    _apply_answer_carry_forward(db, session, schema)

    # Auto-fill city/state/county from any ZIP fields that came in via EMR prefill.
    for field_key, data in prefilled.items():
        if field_key in _ZIP_AUTOFILL_MAP:
            _maybe_autofill_from_zip(db, session_id, form_id, field_key, data["value"], schema=schema)

    answers_map = _answers_map(db, session_id)
    missing = get_missing_applicable_fields(form_id, answers_map, schema)
    next_q = get_current_question_context(form_id, answers_map, schema)
    if not missing:
        session.status = "ready_for_review"
        db.commit()

    return {
        "session_id": session_id,
        "form_id": form_id,
        "form_title": _form_title(form_id, schema),
        "status": "active",
        "mock_mode": mock_mode,
        "prefilled_count": len(prefilled),
        "answered_count": len(answers_map),
        "missing_count": len(missing),
        "total_required": _count_required(form_id, schema),
        "next_question": next_q,
        "prefilled_fields": _build_field_summaries(prefilled, form_id, schema),
        "answers": answers_map,
    }


def get_session_state(db: DBSession, session_id: str) -> dict | None:
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if not session:
        return None

    schema = _schema_for_session(session)
    answers = db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
    answers_map = {a.field_key: _deserialize(a.value_json) for a in answers}
    source_map = {a.field_key: a.source for a in answers}

    # Retroactively fill city/state/county from ZIP if the ZIP is present but
    # the derived fields are still missing (e.g. session created before this logic existed).
    for zip_key, (city_key, state_key, county_key) in _ZIP_AUTOFILL_MAP.items():
        zip_val = answers_map.get(zip_key)
        if zip_val and not all(answers_map.get(k) for k in (city_key, state_key, county_key)):
            _maybe_autofill_from_zip(db, session_id, session.form_id, zip_key, zip_val, schema=schema)
            # Reload answers after potential writes
            answers = db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
            answers_map = {a.field_key: _deserialize(a.value_json) for a in answers}
            source_map = {a.field_key: a.source for a in answers}

    missing = get_missing_applicable_fields(session.form_id, answers_map, schema)
    next_q = get_current_question_context(session.form_id, answers_map, schema)

    prefilled_fields = []
    for a in answers:
        field_meta = _get_field_meta(a.field_key, session.form_id, schema)
        if field_meta:
            prefilled_fields.append({
                "field_key": a.field_key,
                "label": field_meta["label"],
                "value": _deserialize(a.value_json),
                "source": a.source,
                "section": field_meta["section"],
                "is_sensitive": field_meta.get("sensitive", False),
            })

    return {
        "session_id": session_id,
        "form_id": session.form_id,
        "form_title": _form_title(session.form_id, schema),
        "status": session.status,
        "mock_mode": session.mock_mode,
        "prefilled_count": len([a for a in answers if a.source == "emr"]),
        "answered_count": len(answers_map),
        "missing_count": len(missing),
        "total_required": _count_required(session.form_id, schema),
        "next_question": next_q,
        "prefilled_fields": prefilled_fields,
        "answers": answers_map,
    }


def save_answer(
    db: DBSession,
    session_id: str,
    field_key: str,
    raw_answer: str,
    input_mode: str,
    confirmed: bool = False,
) -> dict:
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if not session:
        return {"success": False, "error": "Session not found"}

    schema = _schema_for_session(session)
    answers = db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
    answers_map = {a.field_key: _deserialize(a.value_json) for a in answers}

    if confirmed:
        # The user already confirmed a previously-extracted value (smart-confirm
        # "yes"). Save raw_answer as the value directly, skipping the confidence
        # gate that would otherwise ask to confirm again.
        result = _build_confirmed_result(session.form_id, answers_map, field_key, raw_answer, schema)
    else:
        result = run_answer_step(session.form_id, answers_map, field_key, raw_answer, schema)

    if not result["success"]:
        return result

    extracted_value = result["extracted_value"]
    # An optional field answered with "I don't have X" extracts to None — store
    # the skip sentinel so the review page treats it the same as an explicit skip.
    store_value = "__skipped__" if extracted_value is None else extracted_value
    source = "skipped" if extracted_value is None else ("voice" if input_mode == "voice" else "user")

    existing = db.query(FormAnswer).filter(
        FormAnswer.session_id == session_id,
        FormAnswer.field_key == field_key,
    ).first()

    if existing:
        existing.value_json = json.dumps(store_value)
        existing.raw_answer = raw_answer
        existing.source = source
        existing.confidence = result.get("confidence", 1.0)
    else:
        answer = FormAnswer(
            session_id=session_id,
            field_key=field_key,
            value_json=json.dumps(store_value),
            raw_answer=raw_answer,
            source=source,
            confidence=result.get("confidence", 1.0),
        )
        db.add(answer)

    db.commit()

    # ── ZIP auto-fill: when a ZIP field is saved, look up city/state/county
    # and save them automatically so those questions are never asked.
    carry_forward_msg = _apply_answer_carry_forward(db, session, schema)
    _invalidate_stale_answers(db, session, schema)  # revise model if a gate changed
    zip_autofill_msg = _maybe_autofill_from_zip(
        db, session_id, session.form_id, field_key, extracted_value, schema=schema
    )

    # Warm, brief acknowledgment spoken before the next question.
    from app.ai.question_rewriter import acknowledge_answer
    field_meta = _get_field_meta(field_key, session.form_id, schema)
    if field_meta:
        ack = acknowledge_answer(field_meta, extracted_value)
        if carry_forward_msg:
            ack = (ack.rstrip(" ") + " " + carry_forward_msg).strip()
        if zip_autofill_msg:
            ack = (ack.rstrip(" ") + " " + zip_autofill_msg).strip()
        result["acknowledgment"] = ack

    # Rebuild next_question after potential auto-fills
    updated_answers = {a.field_key: _deserialize(a.value_json)
                       for a in db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()}
    result["next_question"] = get_current_question_context(session.form_id, updated_answers, schema)
    result["missing_count"] = len(get_missing_applicable_fields(session.form_id, updated_answers, schema))
    result["is_complete"] = result["missing_count"] == 0
    result["answers"] = updated_answers

    _set_collection_status(session, result["is_complete"])
    db.commit()

    return result


def _build_confirmed_result(
    form_id: str, answers_map: dict, field_key: str, value: str, schema: dict | None = None
) -> dict:
    """Build a success result for a user-confirmed value (smart-confirm 'yes')."""
    from app.forms.service import get_field
    from app.forms.validation import validate_answer, ValidationError

    field = get_field_from_schema(field_key, schema) if schema is not None else get_field(field_key, form_id)
    if not field:
        return {"success": False, "error": f"Unknown field: {field_key}"}

    coerced: Any = value
    field_type = field.get("type", "text")
    if field_type not in ("text", "textarea"):
        try:
            coerced = validate_answer(field, str(value))
        except ValidationError as exc:
            return {"success": False, "error": f"{exc} {field.get('question_text', '')}".strip()}

    new_answers = {**answers_map, field_key: coerced}
    return {
        "success": True,
        "error": None,
        "answers": new_answers,
        "extracted_value": coerced,
        "confidence": 1.0,
        "needs_clarification": False,
        "is_complete": len(get_missing_applicable_fields(form_id, new_answers, schema)) == 0,
        "next_question": get_current_question_context(form_id, new_answers, schema),
        "missing_count": len(get_missing_applicable_fields(form_id, new_answers, schema)),
    }


def skip_field(db: DBSession, session_id: str, field_key: str) -> dict | None:
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if not session:
        return None

    schema = _schema_for_session(session)
    # Only optional fields may be skipped
    field_meta = _get_field_meta(field_key, session.form_id, schema)
    if field_meta is None:
        return {"success": False, "error": f"Unknown field: {field_key}"}
    if field_meta.get("required", False):
        return {"success": False, "error": "Required fields cannot be skipped."}

    answers = db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
    answers_map = {a.field_key: _deserialize(a.value_json) for a in answers}

    # Record skip with a sentinel so this field is not re-asked
    existing = db.query(FormAnswer).filter(
        FormAnswer.session_id == session_id,
        FormAnswer.field_key == field_key,
    ).first()

    sentinel = "__skipped__"
    if existing:
        existing.value_json = json.dumps(sentinel)
        existing.raw_answer = "skipped"
        existing.source = "skipped"
        existing.confidence = 0.0
    else:
        db.add(FormAnswer(
            session_id=session_id,
            field_key=field_key,
            value_json=json.dumps(sentinel),
            raw_answer="skipped",
            source="skipped",
            confidence=0.0,
        ))
    db.commit()
    _apply_answer_carry_forward(db, session, schema)
    _invalidate_stale_answers(db, session, schema)  # revise model if a skipped gate changed

    answers_map = _answers_map(db, session_id)
    missing = get_missing_applicable_fields(session.form_id, answers_map, schema)
    next_q = get_current_question_context(session.form_id, answers_map, schema)
    is_complete = len(missing) == 0

    _set_collection_status(session, is_complete)
    db.commit()

    return {
        "success": True,
        "is_complete": is_complete,
        "missing_count": len(missing),
        "next_question": next_q,
        "answers": answers_map,
    }


_SKIP_TOKENS = {
    "", "skip", "skipped", "skip it", "skip this", "none", "n/a", "na", "no answer",
    "leave blank", "blank", "not applicable", "__skipped__",
}

# "My mailing address is the same as home" — there is no separate mailing address. Handled
# in set_field so the dependent mailing fields gate off instead of being asked one by one.
_MAILING_SAME_TOKENS = {
    "same", "same as home", "same as above", "same as my home", "same address",
    "same as where i live", "no different", "it's the same", "its the same", "same as home address",
}


def set_field(
    db: DBSession,
    session: FormSession,
    schema: dict,
    field_key: str,
    value: Any,
    input_mode: str = "voice",
    confidence: float = 1.0,
) -> dict:
    """Validate and persist a single field value the agent already extracted.

    Unlike :func:`save_answer`, this does NOT run the per-field extraction LLM —
    the conversational agent has already decided the value, so we only validate
    (so stored values stay well-formed) and persist. An empty / "skip" value on an
    OPTIONAL field stores the skip sentinel; on a required field it's an error the
    agent is told to re-ask for. Returns a per-field result dict.
    """
    from app.forms.validation import validate_answer, ValidationError

    field = get_field_from_schema(field_key, schema)
    if not field:
        return {"ok": False, "field_key": field_key, "error": f"Unknown field: {field_key}"}

    label = field.get("label", field_key)
    required = field.get("required", False)
    raw_str = str(value).strip() if value is not None else ""
    is_skip = raw_str.lower() in _SKIP_TOKENS
    # "Same as home" for a mailing address means there is NO separate mailing address —
    # treat it as a skip so the dependent mailing fields (apt/city/state/ZIP/county) gate
    # off and the assistant stops asking them one at a time.
    if field_key.endswith(".mailing_address") and raw_str.lower() in _MAILING_SAME_TOKENS:
        is_skip = True

    if is_skip:
        if required:
            return {"ok": False, "field_key": field_key, "label": label,
                    "error": f"'{label}' is required and cannot be left blank — please ask for it."}
        store_value: Any = "__skipped__"
        source, raw_answer, coerced = "skipped", "skipped", None
    else:
        try:
            coerced = validate_answer(field, raw_str)
        except ValidationError as exc:
            return {"ok": False, "field_key": field_key, "label": label, "error": str(exc)}
        store_value = coerced
        source = "voice" if input_mode == "voice" else "user"
        raw_answer = raw_str

    existing = db.query(FormAnswer).filter(
        FormAnswer.session_id == session.id,
        FormAnswer.field_key == field_key,
    ).first()
    if existing:
        existing.value_json = json.dumps(store_value)
        existing.raw_answer = raw_answer
        existing.source = source
        existing.confidence = confidence
    else:
        db.add(FormAnswer(
            session_id=session.id, field_key=field_key,
            value_json=json.dumps(store_value), raw_answer=raw_answer,
            source=source, confidence=confidence,
        ))
    db.commit()
    carry_forward_msg = _apply_answer_carry_forward(db, session, schema)
    _invalidate_stale_answers(db, session, schema)  # revise model if a gate changed

    auto_msg = ""
    if coerced is not None:
        try:
            auto_msg = _maybe_autofill_from_zip(db, session.id, session.form_id, field_key, coerced, schema=schema)
        except Exception:
            # The primary field is already committed; a failing ZIP lookup must not
            # abort the save — discard only the half-done autofill writes.
            logger.warning("ZIP autofill failed for %s; primary field already saved.", field_key, exc_info=True)
            db.rollback()
            auto_msg = ""

    is_sensitive = field.get("sensitive", False)
    return {
        "ok": True,
        "field_key": field_key,
        "label": label,
        # 🔒 Never hand a sensitive value (SSN/DOB/phone) back to the agent/LLM — the
        # model only needs to know the field is filled, not its value.
        "stored": "***" if (is_sensitive and store_value != "__skipped__")
                  else ("skipped" if store_value == "__skipped__" else store_value),
        "sensitive": is_sensitive,
        "auto_filled": " ".join(m for m in (carry_forward_msg, auto_msg) if m),
    }


def go_back(db: DBSession, session_id: str) -> dict | None:
    """
    Undo the most recently user-answered field so it becomes the current question again.
    EMR-prefilled, ZIP-autofilled, and skipped answers are not touched — only the last
    field the user explicitly answered (source in voice/user) is deleted.
    Returns the updated session state, or None if the session doesn't exist.
    """
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if not session:
        return None

    schema = _schema_for_session(session)
    # Find user-answered fields in the order they appear in the schema, then take
    # the last one — that is the field we want to un-answer.
    all_field_keys = [f["field_key"] for f in get_all_fields_from_schema(schema)]
    user_answers = (
        db.query(FormAnswer)
        .filter(
            FormAnswer.session_id == session_id,
            FormAnswer.source.in_(["voice", "user"]),
        )
        .all()
    )
    if not user_answers:
        # Nothing the user answered — return current state unchanged
        return get_session_state(db, session_id)

    # Sort by schema position so we always remove the last one in form order
    answered_keys = {a.field_key for a in user_answers}
    ordered = [k for k in all_field_keys if k in answered_keys]
    if not ordered:
        return get_session_state(db, session_id)

    last_key = ordered[-1]
    db.query(FormAnswer).filter(
        FormAnswer.session_id == session_id,
        FormAnswer.field_key == last_key,
    ).delete()
    session.status = "active"
    session.completed_at = None
    db.commit()

    return get_session_state(db, session_id)


def get_review_data(db: DBSession, session_id: str) -> dict | None:
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if not session:
        return None

    schema = _schema_for_session(session)
    answers = db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
    answers_map = {a.field_key: _deserialize(a.value_json) for a in answers}
    source_map = {a.field_key: a.source for a in answers}
    confidence_map = {a.field_key: float(a.confidence or 0.0) for a in answers}

    all_fields = get_all_fields_from_schema(schema)
    fields_by_key = {f["field_key"]: f for f in all_fields}
    section_titles = {s["section_key"]: s["section_title"] for s in schema["sections"]}

    SKIPPED = "__skipped__"
    sections: dict[str, list] = {}
    for field in all_fields:
        # Conditional branches that are inactive for the current answers should not
        # appear as review-time gaps. Approval uses the same applicability rule, so
        # future forms with dependencies keep the UI and API aligned.
        if not is_field_applicable(field, answers_map, fields_by_key):
            continue
        sec = field["section"]
        if sec not in sections:
            sections[sec] = []
        raw_value = answers_map.get(field["field_key"])
        is_skipped = raw_value == SKIPPED
        sections[sec].append({
            "field_key": field["field_key"],
            "label": field["label"],
            "field_type": field.get("type", "text"),
            "options": _field_options(field),
            "value": None if is_skipped else raw_value,
            "source": "skipped" if is_skipped else source_map.get(field["field_key"], "missing"),
            "section": sec,
            "section_title": section_titles.get(sec, sec),
            "is_sensitive": field.get("sensitive", False),
            "is_required": field.get("required", False),
            "confidence": confidence_map.get(field["field_key"]),
        })

    missing_required = get_missing_required_fields(session.form_id, answers_map, schema)
    missing_applicable = get_missing_applicable_fields(session.form_id, answers_map, schema)
    readiness = build_session_readiness(session.form_id, schema, answers)
    return {
        "session_id": session_id,
        "form_id": session.form_id,
        "form_title": _form_title(session.form_id, schema),
        "sections": sections,
        "missing_required": [f["field_key"] for f in missing_required],
        "missing_applicable": [f["field_key"] for f in missing_applicable],
        "is_complete": readiness["ready"],
        "readiness": readiness,
    }


def get_session_readiness(db: DBSession, session_id: str) -> dict | None:
    """Build the same completion gate used by review, approval, and workflows."""
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if not session:
        return None
    schema = _schema_for_session(session)
    answers = db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
    return build_session_readiness(session.form_id, schema, answers)


def _build_field_summaries(prefilled: dict, form_id: str, schema: dict | None = None) -> list[dict]:
    result = []
    for field_key, data in prefilled.items():
        meta = _get_field_meta(field_key, form_id, schema)
        if meta:
            result.append({
                "field_key": field_key,
                "label": meta["label"],
                "value": data["value"],
                "source": data["source"],
                "section": meta["section"],
                "is_sensitive": meta.get("sensitive", False),
            })
    return result


def _get_field_meta(field_key: str, form_id: str, schema: dict | None = None) -> dict | None:
    if schema is not None:
        return get_field_from_schema(field_key, schema)
    for field in get_all_fields(form_id):
        if field["field_key"] == field_key:
            return field
    return None


def _count_required(form_id: str, schema: dict | None = None) -> int:
    # Historical API name: the frontend uses this as the progress denominator for
    # all schema fields, not just the subset marked required.
    return len(get_all_fields_from_schema(schema) if schema is not None else get_all_fields(form_id))


def _form_title(form_id: str, schema: dict) -> str:
    return str(schema.get("form_title") or schema.get("title") or form_id)


def _schema_for_session(session: FormSession) -> dict:
    """Return the frozen schema for a session, falling back for legacy rows."""
    if session.schema_json:
        try:
            return json.loads(session.schema_json)
        except Exception:
            logger.warning("Invalid schema_json on session %s; falling back to live schema.", session.id)
    return load_form_schema(session.form_id)


def _load_published_schema(db: DBSession, form_id: str) -> dict:
    """Load a schema the patient flow is allowed to start.

    Once a DB row exists, its status is authoritative. This prevents a direct API
    call from starting draft/unpublished forms, including ids that also have a
    bundled seed pack on disk. If no DB row exists, the active pack fallback keeps
    fresh unseeded dev/test databases usable.
    """
    from app.forms.registry import UnknownFormError

    row = db.query(Form).filter(Form.form_id == form_id).first()
    if row is not None:
        if row.status != "published":
            raise UnknownFormError(f"Form {form_id!r} is not published.")
        schema = json.loads(row.schema_json)
        form_cache.set_schema(form_id, schema)
        return schema
    return load_form_schema(form_id)


def _set_collection_status(session: FormSession, is_complete: bool) -> None:
    """Keep answer collection separate from completion side effects.

    ``ready_for_review`` means every applicable field is answered/skipped. Only the
    approval/workflow route may set ``completed`` because completion can generate
    files or submit to an external website.
    """
    if is_complete:
        if session.status != "ready_for_review":
            session.status = "ready_for_review"
            session.completed_at = None
    elif session.status != "active":
        session.status = "active"
        session.completed_at = None


def _field_options(field: dict) -> list[Any] | None:
    options = field.get("options")
    if isinstance(options, list):
        return options
    rule = field.get("validation_rule") or {}
    allowed = rule.get("allowed_values")
    return allowed if isinstance(allowed, list) else None


def _answers_map(db: DBSession, session_id: str) -> dict[str, Any]:
    return {
        a.field_key: _deserialize(a.value_json)
        for a in db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
    }


def _deserialize(value_json: str | None) -> Any:
    if value_json is None:
        return None
    try:
        return json.loads(value_json)
    except Exception:
        return value_json


_ODM_PERSON1_CARRY_FORWARD: tuple[tuple[str, str], ...] = (
    ("applicant.first_name", "person1.first_name"),
    ("applicant.middle_name", "person1.middle_name"),
    ("applicant.last_name", "person1.last_name"),
    ("applicant.suffix", "person1.suffix"),
)


def _apply_answer_carry_forward(db: DBSession, session: FormSession, schema: dict) -> str:
    """Copy known applicant facts into duplicate ODM Person 1 fields.

    ODM-07216 asks for the applicant's name early, then later asks for "Person 1"
    information. In the self-service flow Person 1 is the applicant unless the
    user explicitly overwrites it later. Keeping this deterministic prevents the
    voice agent from frustrating users by re-asking for the same first/last name.
    """
    if session.form_id != "ODM_07216":
        return ""

    field_keys = {f["field_key"] for f in get_all_fields_from_schema(schema)}
    answers = {
        row.field_key: row
        for row in db.query(FormAnswer).filter(FormAnswer.session_id == session.id).all()
    }
    changed: list[str] = []

    for source_key, target_key in _ODM_PERSON1_CARRY_FORWARD:
        if source_key not in field_keys or target_key not in field_keys:
            continue
        source = answers.get(source_key)
        if not source or _stored_value_is_empty(source.value_json):
            continue
        if _upsert_carry_forward_answer(db, session.id, target_key, _deserialize(source.value_json), answers):
            changed.append(target_key)

    has_applicant_name = all(
        key in answers and not _stored_value_is_missing(answers[key].value_json)
        for key in ("applicant.first_name", "applicant.last_name")
    )
    if has_applicant_name and "person1.relationship_to_applicant" in field_keys:
        if _upsert_carry_forward_answer(db, session.id, "person1.relationship_to_applicant", "Self", answers):
            changed.append("person1.relationship_to_applicant")

    if changed:
        db.commit()
        return "I also used that for Person 1 so I won't ask for it again."
    return ""


def _invalidate_stale_answers(db: DBSession, session: FormSession, schema: dict) -> list[str]:
    """Correction-aware cleanup: revise the model when a gating answer changes.

    When the person corrects an answer that gates other questions — sex, citizenship,
    household size, "same as mailing address", whether anyone else is applying, etc. —
    any answer that is no longer applicable is removed, so a stale value can't linger or
    silently reappear if the branch is re-opened. Fields that become applicable again are
    naturally re-asked by the missing-field logic.

    This is driven entirely by the schema's ``depends_on`` (the same authority used for
    missing-field detection), so it stays correct and inclusive as the form evolves —
    no hardcoded business rules. Returns the list of field keys that were cleared.
    """
    fields = get_all_fields_from_schema(schema)
    known_keys = {f["field_key"] for f in fields}
    by_key = {f["field_key"]: f for f in fields}
    answers = _answers_map(db, session.id)
    applicable_keys = {f["field_key"] for f in fields if is_field_applicable(f, answers, by_key)}

    cleared: list[str] = []
    for row in db.query(FormAnswer).filter(FormAnswer.session_id == session.id).all():
        fk = row.field_key
        if fk not in known_keys or fk in applicable_keys:
            continue
        # Only clear on a REAL conflict: the gating field is answered and its condition no
        # longer holds. If the gate isn't answered yet (e.g. a home address saved before
        # "are you homeless?"), keep the value — it may become applicable, don't re-ask it.
        # If an unanswered gate is itself inactive, this row is an orphan descendant.
        dep = (by_key.get(fk) or {}).get("depends_on")
        gate_key = dep.get("field_key") if isinstance(dep, dict) else None
        if gate_key and gate_key not in answers:
            gate_field = by_key.get(gate_key)
            if gate_field is None or is_field_applicable(gate_field, answers, by_key):
                continue
        db.delete(row)
        cleared.append(fk)
    if cleared:
        db.commit()
        # 🔒 audit metadata only — the field keys, never the cleared values (PHI).
        logger.info("Correction-aware cleanup cleared %d now-inapplicable answer(s).", len(cleared))
    _apply_pregnancy_skips(db, session, schema)
    return cleared


def _apply_pregnancy_skips(db: DBSession, session: FormSession, schema: dict) -> None:
    """Deterministically skip the pregnancy question for a male applicant — and re-open
    it if their sex is later corrected. Only ever touches an auto-skipped (source=
    "inference") row, never a real user/agent answer, so a correction is never lost.

    ODM only. Skipping ``person{N}.pregnant`` also removes the follow-ups (due date,
    babies expected, recently-pregnant) since those depend on ``pregnant`` being true.
    """
    if session.form_id != "ODM_07216":
        return
    # Every pregnancy-related field, grouped by person (covers "pregnant now", "last 3
    # months", "last 12 months", due date, babies expected — any field key with "pregnan").
    preg_by_person: dict[str, list[str]] = {}
    for f in get_all_fields_from_schema(schema):
        key = f["field_key"]
        if "pregnan" not in key.lower() or f.get("required"):
            continue  # never auto-skip a required field
        for person in ("person1", "person2"):
            if key.startswith(person + "."):
                preg_by_person.setdefault(person, []).append(key)
    if not preg_by_person:
        return

    rows = {
        r.field_key: r
        for r in db.query(FormAnswer).filter(FormAnswer.session_id == session.id).all()
    }
    changed = False
    for person, preg_keys in preg_by_person.items():
        sex_row = rows.get(f"{person}.sex")
        is_male = sex_row is not None and str(_deserialize(sex_row.value_json) or "").strip().lower() == "male"
        for key in preg_keys:
            existing = rows.get(key)
            if is_male:
                if existing is None:
                    db.add(FormAnswer(
                        session_id=session.id, field_key=key,
                        value_json=json.dumps("__skipped__"), raw_answer="skipped",
                        source="inference", confidence=1.0,
                    ))
                    changed = True
            elif existing is not None and existing.source == "inference":
                # Sex is no longer male — re-open the question we auto-skipped.
                db.delete(existing)
                changed = True
    if changed:
        db.commit()


def _upsert_carry_forward_answer(
    db: DBSession,
    session_id: str,
    field_key: str,
    value: Any,
    current_rows: dict[str, FormAnswer],
) -> bool:
    """Insert/update a derived answer without overwriting user-entered values."""
    existing = current_rows.get(field_key)
    if existing and existing.source != "carry_forward":
        return False

    raw_answer = "skipped" if value == "__skipped__" else str(value)
    value_json = json.dumps(value)
    if existing:
        if existing.value_json == value_json:
            return False
        existing.value_json = value_json
        existing.raw_answer = raw_answer
        existing.source = "carry_forward"
        existing.confidence = 1.0
    else:
        existing = FormAnswer(
            session_id=session_id,
            field_key=field_key,
            value_json=value_json,
            raw_answer=raw_answer,
            source="carry_forward",
            confidence=1.0,
        )
        db.add(existing)
        current_rows[field_key] = existing
    return True


def _stored_value_is_missing(value_json: str | None) -> bool:
    value = _deserialize(value_json)
    return value is None or value == "" or value == "__skipped__"


def _stored_value_is_empty(value_json: str | None) -> bool:
    value = _deserialize(value_json)
    return value is None or value == ""


# Maps zip field_key -> (city field_key, state field_key, county field_key)
_ZIP_AUTOFILL_MAP: dict[str, tuple[str, str, str]] = {
    "applicant.zip":      ("applicant.city",      "applicant.state",      "applicant.county"),
    "applicant.mailing_zip": ("applicant.mailing_city", "applicant.mailing_state", "applicant.mailing_county"),
}


def _maybe_autofill_from_zip(
    db: DBSession,
    session_id: str,
    form_id: str,
    field_key: str,
    zip_value: Any,
    schema: dict | None = None,
) -> str:
    """
    If field_key is a ZIP field and ZIPcodeAPI is configured, look up the ZIP
    and bulk-save city, state, and county so those questions are skipped.
    Returns a short human-readable message describing what was auto-filled,
    or an empty string if nothing was filled.
    """
    if field_key not in _ZIP_AUTOFILL_MAP:
        return ""
    if not zip_value or str(zip_value).strip() in ("__skipped__", "", "null", "None"):
        return ""

    from app.services.zipcode import lookup_zip
    info = lookup_zip(str(zip_value).strip())
    if not info:
        return ""

    city_key, state_key, county_key = _ZIP_AUTOFILL_MAP[field_key]
    field_keys = {
        f["field_key"]
        for f in (get_all_fields_from_schema(schema) if schema is not None else get_all_fields(form_id))
    }
    to_fill = [
        (city_key,   info.get("city", "")),
        (state_key,  info.get("state", "")),
        (county_key, info.get("county", "")),
    ]

    filled_labels: list[str] = []
    for fk, val in to_fill:
        if fk not in field_keys:
            continue
        if not val:
            continue
        existing = db.query(FormAnswer).filter(
            FormAnswer.session_id == session_id,
            FormAnswer.field_key == fk,
        ).first()
        if existing:
            # Only overwrite if it hasn't been answered by the user already
            if existing.source in ("emr", "zip", "skipped") or existing.value_json in ('null', '""', '"__skipped__"'):
                existing.value_json = json.dumps(val)
                existing.raw_answer = val
                existing.source = "zip"
                existing.confidence = 1.0
                filled_labels.append(val)
        else:
            db.add(FormAnswer(
                session_id=session_id,
                field_key=fk,
                value_json=json.dumps(val),
                raw_answer=val,
                source="zip",
                confidence=1.0,
            ))
            filled_labels.append(val)

    db.commit()

    if filled_labels:
        return f"I've automatically filled in {', '.join(filled_labels)} from your ZIP code."
    return ""
