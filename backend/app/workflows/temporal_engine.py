"""Temporal client bridge used by the FastAPI approval route."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

from app.core.config import get_settings


async def execute_completion_workflow(session_id: str) -> dict:
    """Start the Temporal completion workflow and wait for its result.

    The review UI currently expects approval to return task status immediately.
    Waiting here preserves that API contract while Temporal provides durable
    orchestration, retries, and visibility behind the scenes.
    """
    from temporalio.client import Client
    from app.workflows.temporal_definitions import FormCompletionWorkflow

    settings = get_settings()
    client = await Client.connect(settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE)
    handle = await client.start_workflow(
        FormCompletionWorkflow.run,
        session_id,
        id=f"form-completion-{session_id}-{uuid.uuid4().hex[:8]}",
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        execution_timeout=timedelta(seconds=settings.TEMPORAL_WORKFLOW_TIMEOUT_SECONDS),
    )
    return await handle.result()


def execute_completion_workflow_sync(session_id: str) -> dict:
    """Synchronous wrapper for FastAPI's current sync workflow route."""
    return asyncio.run(execute_completion_workflow(session_id))
