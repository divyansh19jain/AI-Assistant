"""Temporal workflow definitions for form completion.

The workflow itself stays deterministic and tiny: it delegates real side effects
(PDF generation, web submission, DB writes) to an Activity. This keeps Temporal
responsible for durable state/retry while preserving the existing workflow task
handlers and audit tables.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class FormCompletionWorkflow:
    """Durable completion workflow started after the user approves a session."""

    @workflow.run
    async def run(self, session_id: str) -> dict:
        return await workflow.execute_activity(
            "run_completion_workflow",
            session_id,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
