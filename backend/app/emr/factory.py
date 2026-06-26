"""Return the correct EMR adapter based on settings."""

import logging
from app.core.config import get_settings
from app.emr.adapter import BaseEMRAdapter

logger = logging.getLogger(__name__)


def get_emr_adapter() -> BaseEMRAdapter:
    settings = get_settings()

    if settings.USE_MOCK_EMR or not settings.EMR_DATABASE_URL:
        from app.emr.mock_adapter import MockEMRAdapter
        logger.info("EMR mode: MOCK")
        return MockEMRAdapter()

    try:
        from app.emr.talbot_adapter import TalbotEMRAdapter
        adapter = TalbotEMRAdapter()
        logger.info("EMR mode: Talbot (real)")
        return adapter
    except Exception as exc:
        from app.emr.mock_adapter import MockEMRAdapter
        logger.warning("Talbot EMR adapter failed to initialize (%s) — falling back to mock", exc)
        return MockEMRAdapter()
