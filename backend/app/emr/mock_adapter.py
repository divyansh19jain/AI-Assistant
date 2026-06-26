from app.emr.adapter import BaseEMRAdapter
from app.emr.masking import build_masked_patient
from app.emr.schemas import EMRPatient, EMRAddress, MaskedPatient

MOCK_PATIENTS: list[EMRPatient] = [
    EMRPatient(
        external_patient_id="mock-001",
        first_name="Test",
        middle_name="A",
        last_name="Patient",
        dob="1990-01-15",
        sex="Female",
        phone="6145551234",
        email="test.patient@example.com",
        address=EMRAddress(
            line1="123 Main Street",
            line2="Apt 4B",
            city="Columbus",
            state="OH",
            zip="43215",
            county="Franklin",
        ),
        insurance=[],
        employment=[],
        income=[],
    ),
    EMRPatient(
        external_patient_id="mock-002",
        first_name="Jane",
        middle_name=None,
        last_name="Doe",
        dob="1985-06-20",
        sex="Female",
        phone="6145559876",
        email="jane.doe@example.com",
        address=EMRAddress(
            line1="456 Oak Avenue",
            city="Cleveland",
            state="OH",
            zip="44101",
            county="Cuyahoga",
        ),
        insurance=[],
        employment=[],
        income=[],
    ),
]


class MockEMRAdapter(BaseEMRAdapter):
    @property
    def is_mock(self) -> bool:
        return True

    def search_patients(self, first_name: str, last_name: str, dob: str) -> list[MaskedPatient]:
        results = []
        for p in MOCK_PATIENTS:
            fn_match = p.first_name.lower().startswith(first_name.lower())
            ln_match = p.last_name.lower().startswith(last_name.lower())
            dob_match = (not dob) or (p.dob == dob)
            if fn_match and ln_match and dob_match:
                # 🔒 Mask PHI at the search boundary (see app/emr/masking.py).
                results.append(
                    build_masked_patient(
                        external_patient_id=p.external_patient_id,
                        first_name=p.first_name,
                        last_name=p.last_name,
                        dob=p.dob,
                        phone=p.phone,
                        is_mock=True,
                    )
                )
        return results

    def get_patient(self, external_patient_id: str) -> EMRPatient | None:
        for p in MOCK_PATIENTS:
            if p.external_patient_id == external_patient_id:
                return p
        return None
