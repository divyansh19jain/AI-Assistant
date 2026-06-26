"""
Workflow engine — runs a form's completion tasks after human approval.

A form's **workflow** is an ordered list of **tasks** (steps) that run once the user
approves their answers: ``generate_pdf``, ``notify``, ``store_evidence``, and (Phase G)
``web_submit``. Task handlers share one signature — ``handler(db, session, config) ->
dict`` — mirroring the EMR-adapter/skill pattern, so new task types are easy to add.

Every run is recorded (:class:`WorkflowRun` + :class:`WorkflowTaskRun`) with each
task's status and output/evidence, so the patient (and an admin) can see exactly what
happened. Execution stops at the first failed task.

The definition is read from ``forms.workflow_json`` (edited in the builder), falling
back to one derived from the form's ``output_targets`` (``pdf`` -> a generate_pdf task).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.db.models import Form, FormSession, WorkflowRun, WorkflowTaskRun

logger = logging.getLogger(__name__)


def _default_tasks(output_targets: list[str]) -> list[dict]:
    tasks: list[dict] = []
    if "pdf" in output_targets:
        tasks.append({"type": "generate_pdf"})
    if "web" in output_targets:
        tasks.append({"type": "web_submit"})
    return tasks or [{"type": "generate_pdf"}]


def get_workflow_def(db, form_id: str) -> dict:
    """Return ``{"tasks":[...], "approval":{...}}`` for a form (explicit or derived)."""
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


# ── task handlers: handler(db, session, config) -> output dict ────────────────
def _task_generate_pdf(db, session, config: dict) -> dict:
    from app.pdf.pdf_service import generate_session_pdf

    result = generate_session_pdf(db, session.id)
    if not result:
        raise RuntimeError("PDF generation returned no result")
    return result  # {session_id, download_url, file_name, is_fallback}


def _task_notify(db, session, config: dict) -> dict:
    # Stub: real delivery (email/SMS) would go here. Log identifiers only (no PHI).
    logger.info("Workflow notify task ran for session %s.", session.id)
    return {"notified": True, "channel": config.get("channel", "log")}


def _task_store_evidence(db, session, config: dict) -> dict:
    # Stub: real evidence capture (to the BlobStore) is fleshed out with web_submit (Phase G).
    return {"stored": True}


def _session_answers(db, session_id: str) -> dict:
    """Load a session's answers as ``{field_key: value}``."""
    from app.db.models import FormAnswer

    out: dict = {}
    for row in db.query(FormAnswer).filter(FormAnswer.session_id == session_id).all():
        try:
            out[row.field_key] = json.loads(row.value_json) if row.value_json else None
        except Exception:
            out[row.field_key] = row.value_json
    return out


def _form_web_recipe(db, form_id: str) -> dict:
    """The web-submission recipe for a form (from its pack ``workflow.yaml`` ``web:`` block)."""
    try:
        from app.forms import registry

        pack = registry.get_pack(form_id)
        web = (pack.config.get("web") if isinstance(pack.config, dict) else None) or {}
        return web if isinstance(web, dict) else {}
    except Exception:
        return {}


def _task_web_submit(db, session, config: dict) -> dict:
    """🔒 PHI EGRESS — submit answers to an external portal (gated; see web_submit.py).

    Uses the safe dry-run mock driver unless WEB_SUBMIT_DRIVER=browserless is configured.
    """
    from app.workflows.web_submit import submit_web

    recipe = config.get("recipe") or _form_web_recipe(db, session.form_id)
    answers = _session_answers(db, session.id)
    evidence = submit_web(recipe, answers)
    if evidence.get("error"):
        raise RuntimeError(f"web submit failed: {evidence['error']}")
    return evidence


TASK_HANDLERS = {
    "generate_pdf": _task_generate_pdf,
    "notify": _task_notify,
    "store_evidence": _task_store_evidence,
    "web_submit": _task_web_submit,
}


def run_workflow(db, session_id: str) -> WorkflowRun:
    """Execute a session's form workflow, recording each task. Stops at first failure."""
    session = db.query(FormSession).filter(FormSession.id == session_id).first()
    if session is None:
        raise ValueError(f"session {session_id} not found")

    wf = get_workflow_def(db, session.form_id)
    run = WorkflowRun(session_id=session_id, form_id=session.form_id, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    failed = False
    for i, task in enumerate(wf.get("tasks", [])):
        ttype = task.get("type", "")
        tr = WorkflowTaskRun(workflow_run_id=run.id, ordinal=i, task_type=ttype, status="pending")
        db.add(tr)
        db.commit()
        db.refresh(tr)

        handler = TASK_HANDLERS.get(ttype)
        if handler is None:
            tr.status = "skipped"
            tr.error = f"no handler for task type {ttype!r}"
            db.commit()
            continue
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
    """Serialize a run + its tasks (with outputs) for the API."""
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
                "output": json.loads(t.output_json) if t.output_json else None,
                "error": t.error,
            }
            for t in tasks
        ],
    }
