import logging
from app.emr.factory import get_emr_adapter
from app.emr.schemas import MaskedPatient

logger = logging.getLogger(__name__)


def search_patients(first_name: str, last_name: str, dob: str) -> tuple[list[MaskedPatient], bool]:
    """
    Search EMR for matching patients.
    Returns (matches, is_mock).
    """
    adapter = get_emr_adapter()
    try:
        matches = adapter.search_patients(first_name, last_name, dob)
        return matches, adapter.is_mock
    except Exception as exc:
        logger.error("Patient search failed: %s", exc)
        return [], adapter.is_mock


def get_patient_by_id(external_patient_id: str):
    """Retrieve full patient record from EMR."""
    adapter = get_emr_adapter()
    return adapter.get_patient(external_patient_id)
