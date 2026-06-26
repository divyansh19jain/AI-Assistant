import json
import uuid
import logging
from typing import Any
from sqlalchemy.orm import Session as DBSession
from app.db.models import FormSession, FormAnswer
from app.db.session import get_db
from app.emr.schemas import EMRPatient
from app.forms.service import get_all_fields, load_form_schema
from app.forms.mapper import prefill_from_emr
from app.forms.missing_fields import get_missing_required_fields
from app.forms.questions import get_current_question_context
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

    if patient_id and not manual_mode:
        patient = get_patient_by_id(patient_id)
        if patient:
            from app.emr.factory import get_emr_adapter
            mock_mode = get_emr_adapter().is_mock
            prefilled = prefill_from_emr(patient, form_id)

    session = FormSession(
        id=session_id,
        form_id=form_id,
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

    # Auto-fill city/state/county from any ZIP fields that came in via EMR prefill.
    for field_key, data in prefilled.items():
        if field_key in _ZIP_AUTOFILL_MAP:
            _maybe_autofill_from_zip(db, session_id, form_id, field_key, data["value"])

    answers_map = {k: v["value"] for k, v in prefilled.items()}
    missing = get_missing_required_fields(form_id, answers_map)
    next_q = get_current_question_context(form_id, answers_map)

    return {
        "session_id": session_id,
        "form_id": form_id,
        "status": "active",
        "mock_mode": mock_mode,
        "prefilled_count": len(prefilled),
        "answered_count": len(prefilled),
        "missing_count": len(missing),
        "total_required": _count_required(form_id),
        "next_question": next_q,
        "prefilled_fields": _build_field_summaries(prefilled, form_id),
        "answers": answers_map,
    }


def get_session_state(db: DBSession, session_id: str) -> dict | None:
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if not session:
        return None

    answers = db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
    answers_map = {a.field_key: _deserialize(a.value_json) for a in answers}
    source_map = {a.field_key: a.source for a in answers}

    # Retroactively fill city/state/county from ZIP if the ZIP is present but
    # the derived fields are still missing (e.g. session created before this logic existed).
    for zip_key, (city_key, state_key, county_key) in _ZIP_AUTOFILL_MAP.items():
        zip_val = answers_map.get(zip_key)
        if zip_val and not all(answers_map.get(k) for k in (city_key, state_key, county_key)):
            _maybe_autofill_from_zip(db, session_id, session.form_id, zip_key, zip_val)
            # Reload answers after potential writes
            answers = db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
            answers_map = {a.field_key: _deserialize(a.value_json) for a in answers}
            source_map = {a.field_key: a.source for a in answers}

    missing = get_missing_required_fields(session.form_id, answers_map)
    next_q = get_current_question_context(session.form_id, answers_map)

    prefilled_fields = []
    for a in answers:
        field_meta = _get_field_meta(a.field_key, session.form_id)
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
        "status": session.status,
        "mock_mode": session.mock_mode,
        "prefilled_count": len([a for a in answers if a.source == "emr"]),
        "answered_count": len(answers_map),
        "missing_count": len(missing),
        "total_required": _count_required(session.form_id),
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

    answers = db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
    answers_map = {a.field_key: _deserialize(a.value_json) for a in answers}

    if confirmed:
        # The user already confirmed a previously-extracted value (smart-confirm
        # "yes"). Save raw_answer as the value directly, skipping the confidence
        # gate that would otherwise ask to confirm again.
        result = _build_confirmed_result(session.form_id, answers_map, field_key, raw_answer)
    else:
        result = run_answer_step(session.form_id, answers_map, field_key, raw_answer)

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
    zip_autofill_msg = _maybe_autofill_from_zip(db, session_id, session.form_id, field_key, extracted_value)

    # Warm, brief acknowledgment spoken before the next question.
    from app.ai.question_rewriter import acknowledge_answer
    field_meta = _get_field_meta(field_key, session.form_id)
    if field_meta:
        ack = acknowledge_answer(field_meta, extracted_value)
        if zip_autofill_msg:
            ack = (ack.rstrip(" ") + " " + zip_autofill_msg).strip()
        result["acknowledgment"] = ack

    # Rebuild next_question after potential auto-fills
    updated_answers = {a.field_key: _deserialize(a.value_json)
                       for a in db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()}
    result["next_question"] = get_current_question_context(session.form_id, updated_answers)
    result["missing_count"] = len(get_missing_required_fields(session.form_id, updated_answers))
    result["is_complete"] = result["missing_count"] == 0
    result["answers"] = updated_answers

    if result["is_complete"] and session.status != "completed":
        session.status = "completed"
        db.commit()
    elif not result["is_complete"] and session.status == "completed":
        session.status = "active"
        db.commit()

    return result


def _build_confirmed_result(
    form_id: str, answers_map: dict, field_key: str, value: str
) -> dict:
    """Build a success result for a user-confirmed value (smart-confirm 'yes')."""
    from app.forms.service import get_field
    from app.forms.validation import validate_answer, ValidationError

    field = get_field(field_key, form_id)
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
        "is_complete": len(get_missing_required_fields(form_id, new_answers)) == 0,
        "next_question": get_current_question_context(form_id, new_answers),
        "missing_count": len(get_missing_required_fields(form_id, new_answers)),
    }


def skip_field(db: DBSession, session_id: str, field_key: str) -> dict | None:
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if not session:
        return None

    # Only optional fields may be skipped
    field_meta = _get_field_meta(field_key, session.form_id)
    if field_meta and field_meta.get("required", False):
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

    answers_map[field_key] = sentinel
    missing = get_missing_required_fields(session.form_id, answers_map)
    next_q = get_current_question_context(session.form_id, answers_map)
    is_complete = len(missing) == 0

    if is_complete and session.status != "completed":
        session.status = "completed"
        db.commit()
    elif not is_complete and session.status == "completed":
        session.status = "active"
        db.commit()

    return {
        "success": True,
        "is_complete": is_complete,
        "missing_count": len(missing),
        "next_question": next_q,
        "answers": answers_map,
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

    # Find user-answered fields in the order they appear in the schema, then take
    # the last one — that is the field we want to un-answer.
    all_field_keys = [f["field_key"] for f in get_all_fields(session.form_id)]
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
    db.commit()

    return get_session_state(db, session_id)


def get_review_data(db: DBSession, session_id: str) -> dict | None:
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if not session:
        return None

    answers = db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all()
    answers_map = {a.field_key: _deserialize(a.value_json) for a in answers}
    source_map = {a.field_key: a.source for a in answers}

    all_fields = get_all_fields(session.form_id)
    schema = load_form_schema(session.form_id)
    section_titles = {s["section_key"]: s["section_title"] for s in schema["sections"]}

    SKIPPED = "__skipped__"
    sections: dict[str, list] = {}
    for field in all_fields:
        sec = field["section"]
        if sec not in sections:
            sections[sec] = []
        raw_value = answers_map.get(field["field_key"])
        is_skipped = raw_value == SKIPPED
        sections[sec].append({
            "field_key": field["field_key"],
            "label": field["label"],
            "value": None if is_skipped else raw_value,
            "source": "skipped" if is_skipped else source_map.get(field["field_key"], "missing"),
            "section": sec,
            "section_title": section_titles.get(sec, sec),
            "is_sensitive": field.get("sensitive", False),
            "is_required": field.get("required", False),
        })

    missing = get_missing_required_fields(session.form_id, answers_map)
    return {
        "session_id": session_id,
        "sections": sections,
        "missing_required": [f["field_key"] for f in missing],
        "is_complete": len(missing) == 0,
    }


def _build_field_summaries(prefilled: dict, form_id: str) -> list[dict]:
    result = []
    for field_key, data in prefilled.items():
        meta = _get_field_meta(field_key, form_id)
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


def _get_field_meta(field_key: str, form_id: str) -> dict | None:
    for field in get_all_fields(form_id):
        if field["field_key"] == field_key:
            return field
    return None


def _count_required(form_id: str) -> int:
    return len(get_all_fields(form_id))


def _deserialize(value_json: str | None) -> Any:
    if value_json is None:
        return None
    try:
        return json.loads(value_json)
    except Exception:
        return value_json


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
    to_fill = [
        (city_key,   info.get("city", "")),
        (state_key,  info.get("state", "")),
        (county_key, info.get("county", "")),
    ]

    filled_labels: list[str] = []
    for fk, val in to_fill:
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
