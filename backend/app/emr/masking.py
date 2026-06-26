"""
PHI masking at the EMR **search** boundary.

🔒 Patient search results leave the backend toward the client, so they MUST be
masked (docs/ai/SECURITY-AND-PHI.md §2). This helper builds a :class:`MaskedPatient`
with name/DOB/phone passed through the ``mask_*`` helpers in
:mod:`app.core.security`, and every EMR adapter's ``search_patients`` uses it so the
masking can't be forgotten per-adapter.

Contrast with ``adapter.get_patient()``, which returns the **full** unmasked
``EMRPatient`` — that path is **server-side only** (used for form prefill) and is
never serialized to an HTTP response.
"""

from app.core.security import mask_dob, mask_name, mask_phone
from app.emr.schemas import MaskedPatient


def build_masked_patient(
    *,
    external_patient_id: str,
    first_name: str | None,
    last_name: str | None,
    dob: str | None,
    phone: str | None,
    is_mock: bool,
) -> MaskedPatient:
    """Return a :class:`MaskedPatient` with PHI masked for client display.

    Masking is partial by design (``T***``, ``****-**-15``, ``***-***-1234``) so a
    user can still recognize their own record in the patient-match step without the
    backend exposing full PHI. ``external_patient_id`` is an opaque identifier (not
    PHI) and is left intact so the chosen record can be fetched server-side.
    """
    return MaskedPatient(
        external_patient_id=external_patient_id,
        first_name=mask_name(first_name or ""),
        last_name=mask_name(last_name or ""),
        dob=mask_dob(dob or ""),
        phone=mask_phone(phone) if phone else None,
        is_mock=is_mock,
    )
