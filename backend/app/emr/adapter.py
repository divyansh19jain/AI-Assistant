from abc import ABC, abstractmethod
from app.emr.schemas import EMRPatient, MaskedPatient


class BaseEMRAdapter(ABC):
    """Abstract EMR adapter — swap implementations without changing callers."""

    @abstractmethod
    def search_patients(
        self, first_name: str, last_name: str, dob: str
    ) -> list[MaskedPatient]:
        """Return masked patient matches for the given search criteria."""
        ...

    @abstractmethod
    def get_patient(self, external_patient_id: str) -> EMRPatient | None:
        """Return full normalized patient record by ID."""
        ...

    @property
    @abstractmethod
    def is_mock(self) -> bool:
        ...
