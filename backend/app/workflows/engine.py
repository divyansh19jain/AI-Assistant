"""
Workflow engine: runs a form's completion tasks after human approval.

Supported task types are deliberately small and real:
  - generate_pdf: create the session PDF or summary PDF.
  - web_submit: submit the approved answers through the configured web driver.

Unknown task types fail the run. They are never skipped, because a skipped
completion step can look like a successful submission to users and auditors.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.db.models import Form, FormSession, WorkflowRun, WorkflowTaskRun
from app.forms.missing_fields import get_applicable_answers
from app.sessions.service import _schema_for_session

logger = logging.getLogger(__name__)


def _default_tasks(output_targets: list[str]) -> list[dict]:
    tasks: list[dict] = []
    if "pdf" in output_targets:
        tasks.append({"type": "generate_pdf"})
    if "web" in output_targets:
        tasks.append({"type": "web_submit"})
    return tasks or [{"type": "generate_pdf"}]


def get_workflow_def(db, form_id: str) -> dict:
    """Return {"tasks":[...], "approval":{...}} for a form."""
    form = db.query(Form).filter(Form.form_id == form_id).first()
    if form and form.workflow_json:
        try:
            wf = json.loads(form.workflow_json)
            if isinstance(wf.get("tasks"), list):
                return wf
        except Exception:
            logger.warning("Bad workflow_json for %s; using default.", form_id)
    targets = form.output_targets.split(",") if form and form.output_targets else ["pdf"]
    return {"tasks": _default_tasks(targets), "approval": {"required": True}}


def _task_generate_pdf(db, session, config: dict) -> dict:
    from app.pdf.pdf_service import generate_session_pdf

    result = generate_session_pdf(db, session.id)
    if not result:
        raise RuntimeError("PDF generation returned no result")
    return result


def _session_answers(db, session: FormSession, *, include_skipped: bool = True) -> dict:
    """Load active-branch answers for a session."""
    from app.db.models import FormAnswer

    out: dict = {}
    for row in db.query(FormAnswer).filter(FormAnswer.session_id == session.id).all():
        try:
            out[row.field_key] = json.loads(row.value_json) if row.value_json else None
        except Exception:
            out[row.field_key] = row.value_json
    return get_applicable_answers(_schema_for_session(session), out, include_skipped=include_skipped)


def _form_web_recipe(db, form_id: str) -> dict:
    """Return the bundled pack web-submission recipe, when the form has one."""
    try:
        from app.forms import registry

        pack = registry.get_pack(form_id)
        web = (pack.config.get("web") if isinstance(pack.config, dict) else None) or {}
        return web if isinstance(web, dict) else {}
    except Exception:
        return {}


def _task_web_submit(db, session, config: dict) -> dict:
    """Submit answers to an external portal after approval."""
    from app.workflows.web_submit import submit_web

    recipe = config.get("recipe") or _form_web_recipe(db, session.form_id)
    answers = _session_answers(db, session, include_skipped=False)
    evidence = submit_web(recipe, answers)
    if evidence.get("error"):
        raise RuntimeError(f"web submit failed: {evidence['error']}")
    return evidence


TASK_HANDLERS = {
    "generate_pdf": _task_generate_pdf,
    "web_submit": _task_web_submit,
}


def run_workflow(db, session_id: str) -> WorkflowRun:
    """Execute a session's form workflow and stop at the first failure."""
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if session is None:
        raise ValueError(f"session {session_id} not found")

    wf = get_workflow_def(db, session.form_id)
    run = WorkflowRun(session_id=session_id, form_id=session.form_id, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    tasks = wf.get("tasks", [])
    if not isinstance(tasks, list) or not tasks:
        run.status = "failed"
        run.error = "workflow has no tasks"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        return run

    failed = False
    for i, task in enumerate(tasks):
        ttype = task.get("type", "")
        tr = WorkflowTaskRun(workflow_run_id=run.id, ordinal=i, task_type=ttype, status="pending")
        db.add(tr)
        db.commit()
        db.refresh(tr)

        handler = TASK_HANDLERS.get(ttype)
        if handler is None:
            tr.status = "failed"
            tr.error = f"unsupported workflow task type {ttype!r}"
            db.commit()
            failed = True
            break

        try:
            out = handler(db, session, task.get("config") or {})
            tr.status = "completed"
            tr.output_json = json.dumps(out)
            db.commit()
        except Exception as exc:
            tr.status = "failed"
            tr.error = str(exc)
            db.commit()
            failed = True
            logger.warning("Workflow task %s failed for session %s.", ttype, session_id, exc_info=True)
            break

    run.status = "failed" if failed else "completed"
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run


def get_latest_run(db, session_id: str) -> WorkflowRun | None:
    return (
        db.query(WorkflowRun)
        .filter(WorkflowRun.session_id == session_id)
        .order_by(WorkflowRun.id.desc())
        .first()
    )


def run_status_dict(db, run: WorkflowRun) -> dict:
    """Serialize a run and its task outputs for the API."""
    tasks = (
        db.query(WorkflowTaskRun)
        .filter(WorkflowTaskRun.workflow_run_id == run.id)
        .order_by(WorkflowTaskRun.ordinal)
        .all()
    )
    return {
        "run_id": run.id,
        "status": run.status,
        "error": run.error,
        "tasks": [
            {
                "type": t.task_type,
                "status": t.status,
                "output": _parse_task_output(t.output_json),
                "error": t.error,
            }
            for t in tasks
        ],
    }


def _parse_task_output(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return {"raw": raw}
