"""External clinical assessment result API.

This router is intentionally separate from the patient-facing session routes.
EMRs can pull a completed behavioral-health self-report summary with an API key
without receiving the broader admin surface.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.clinical.scoring import CLINICAL_BATTERY_FORM_ID, score_clinical_battery
from app.core.config import get_settings
from app.db.models import FormAnswer, FormSession
from app.db.session import get_db
from app.forms.missing_fields import is_field_applicable
from app.forms.service import get_all_fields_from_schema
from app.forms.validation import ValidationError, validate_answer
from app.sessions import service as session_service

router = APIRouter(prefix="/api/clinical", tags=["clinical-results"])


def _allowed_keys() -> set[str]:
    raw = get_settings().CLINICAL_RESULTS_API_KEYS
    return {part.strip() for part in raw.split(",") if part.strip()}


def _verify_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Authorize EMR pulls with either X-API-Key or Authorization: Bearer <key>."""
    allowed = _allowed_keys()
    if not allowed:
        raise HTTPException(status_code=503, detail="Clinical results API is not configured.")
    bearer = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    supplied = x_api_key or bearer
    if not supplied or supplied not in allowed:
        raise HTTPException(status_code=401, detail="Invalid clinical results API key.")


def _deserialize(value_json: str | None) -> Any:
    if value_json is None:
        return None
    try:
        return json.loads(value_json)
    except Exception:
        return value_json


def _answer_map(rows: list[FormAnswer]) -> dict[str, Any]:
    return {row.field_key: _deserialize(row.value_json) for row in rows}


def _selected_tool_keys(answers: dict[str, Any]) -> list[str]:
    return sorted(
        key.split(".", 1)[1]
        for key, value in answers.items()
        if key.startswith("selected.") and value is True
    )


def _assessment_answers(schema: dict, answers: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Group applicable answered fields by assessment section for EMR ingestion."""
    fields = get_all_fields_from_schema(schema)
    fields_by_key = {field["field_key"]: field for field in fields}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        key = field["field_key"]
        section = field.get("section", "")
        if section in {"client", "selected"}:
            continue
        if key not in answers or not is_field_applicable(field, answers, fields_by_key):
            continue
        if not _answer_valid(field, answers.get(key)):
            continue
        grouped.setdefault(section, []).append({
            "field_key": key,
            "label": field.get("label", key),
            "question_text": field.get("question_text"),
            "value": answers.get(key),
        })
    return grouped


def _answer_valid(field: dict, value: Any) -> bool:
    if value in (None, "", "__skipped__"):
        return False
    try:
        validate_answer(field, value)
    except ValidationError:
        return False
    return True


def _safe_client_value(schema: dict, answers: dict[str, Any], field_key: str) -> Any:
    field = next((f for f in get_all_fields_from_schema(schema) if f["field_key"] == field_key), None)
    value = answers.get(field_key)
    if not field or not _answer_valid(field, value):
        return None
    return value


def _clinical_payload(session: FormSession, schema: dict, rows: list[FormAnswer]) -> dict[str, Any]:
    answers = _answer_map(rows)
    scores = score_clinical_battery(session.form_id, answers)
    assessment_data = _assessment_answers(schema, answers)
    scores_by_key = {score.get("tool_key"): score for score in scores}
    assessments = [
        {
            "tool_key": tool_key,
            "assessment_name": scores_by_key.get(tool_key, {}).get("title", tool_key),
            "score": scores_by_key.get(tool_key),
            "data": assessment_data.get(tool_key, []),
        }
        for tool_key in _selected_tool_keys(answers)
    ]
    return {
        "session_id": session.id,
        "form_id": session.form_id,
        "form_title": session_service._form_title(session.form_id, schema),
        "patient_external_id": session.patient_external_id,
        "status": session.status,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "client": {
            "first_name": _safe_client_value(schema, answers, "client.first_name"),
            "last_name": _safe_client_value(schema, answers, "client.last_name"),
            "dob": _safe_client_value(schema, answers, "client.dob"),
        },
        "selected_assessments": _selected_tool_keys(answers),
        "assessments": assessments,
        "scores": scores,
        "assessment_data": assessment_data,
    }


@router.get("/results/{session_id}")
def get_clinical_result(
    session_id: str,
    _: Annotated[None, Depends(_verify_api_key)],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return one clinical self-report session for EMR pull-by-session-id."""
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if session is None or session.form_id != CLINICAL_BATTERY_FORM_ID:
        raise HTTPException(status_code=404, detail="Clinical assessment session not found.")
    schema = session_service._schema_for_session(session)
    rows = db.query(FormAnswer).filter(FormAnswer.session_id == session.id).all()
    return _clinical_payload(session, schema, rows)


@router.get("/results")
def list_clinical_results(
    _: Annotated[None, Depends(_verify_api_key)],
    db: Session = Depends(get_db),
    patient_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, list[dict[str, Any]]]:
    """Return recent clinical sessions, optionally filtered by EMR patient id."""
    query = db.query(FormSession).filter(FormSession.form_id == CLINICAL_BATTERY_FORM_ID)
    if patient_id:
        query = query.filter(FormSession.patient_external_id == patient_id)
    sessions = query.order_by(FormSession.created_at.desc()).limit(limit).all()
    results: list[dict[str, Any]] = []
    for session in sessions:
        schema = session_service._schema_for_session(session)
        rows = db.query(FormAnswer).filter(FormAnswer.session_id == session.id).all()
        results.append(_clinical_payload(session, schema, rows))
    return {"results": results}
