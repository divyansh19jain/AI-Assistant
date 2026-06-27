r"""Temporal worker process for approved form completion.

Run locally:

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.workflows.temporal_worker
```

In Docker Compose this runs as the `temporal-worker` service.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.base import SessionLocal
from app.db.session import create_tables
from app.workflows.engine import run_status_dict, run_workflow
from app.workflows.temporal_definitions import FormCompletionWorkflow

logger = logging.getLogger(__name__)


@activity.defn(name="run_completion_workflow")
def run_completion_workflow_activity(session_id: str) -> dict:
    """Execute the existing sync completion engine inside a worker thread."""
    db = SessionLocal()
    try:
        run = run_workflow(db, session_id)
        return run_status_dict(db, run)
    finally:
        db.close()


async def main() -> None:
    setup_logging()
    create_tables()
    settings = get_settings()
    client = await Client.connect(settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE)
    activity_executor = ThreadPoolExecutor(max_workers=settings.TEMPORAL_ACTIVITY_WORKERS)
    worker = Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[FormCompletionWorkflow],
        activities=[run_completion_workflow_activity],
        activity_executor=activity_executor,
    )
    logger.info(
        "Temporal worker started: address=%s namespace=%s task_queue=%s activity_workers=%s",
        settings.TEMPORAL_ADDRESS,
        settings.TEMPORAL_NAMESPACE,
        settings.TEMPORAL_TASK_QUEUE,
        settings.TEMPORAL_ACTIVITY_WORKERS,
    )
    try:
        await worker.run()
    finally:
        activity_executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    asyncio.run(main())
