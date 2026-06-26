"""
Talbot EMR adapter for talbotdev PostgreSQL database.
Uses the real 'Patient' table schema discovered via introspection.
"""

import logging
from sqlalchemy import create_engine, text
from app.core.config import get_settings
from app.emr.adapter import BaseEMRAdapter
from app.emr.masking import build_masked_patient
from app.emr.schemas import EMRPatient, EMRAddress, MaskedPatient

logger = logging.getLogger(__name__)


class TalbotEMRAdapter(BaseEMRAdapter):
    """Read-only adapter for the Talbot EMR database."""

    def __init__(self) -> None:
        settings = get_settings()
        self._engine = create_engine(
            settings.EMR_DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
        )

    @property
    def is_mock(self) -> bool:
        return False

    def search_patients(self, first_name: str, last_name: str, dob: str) -> list[MaskedPatient]:
        try:
            with self._engine.connect() as conn:
                query = text("""
                    SELECT
                        "Id"::text          AS external_patient_id,
                        "FirstName"         AS first_name,
                        "MI"                AS middle_name,
                        "LastName"          AS last_name,
                        "DOB"::text         AS dob,
                        "GenderId"          AS gender_id,
                        "PhoneNumber"       AS phone,
                        "MobilePhoneNumber" AS mobile_phone,
                        "Email"             AS email
                    FROM "Patient"
                    WHERE "IsDeleted" = false
                      AND LOWER("FirstName") LIKE LOWER(:fn)
                      AND LOWER("LastName")  LIKE LOWER(:ln)
                      AND (:dob = '' OR "DOB"::text = :dob)
                    ORDER BY "Id" ASC
                    LIMIT 10
                """)
                rows = conn.execute(
                    query,
                    {"fn": f"{first_name}%", "ln": f"{last_name}%", "dob": dob},
                ).fetchall()

                results = []
                for row in rows:
                    d = row._asdict()
                    phone = d.get("mobile_phone") or d.get("phone") or ""
                    # 🔒 Mask PHI at the search boundary (see app/emr/masking.py).
                    results.append(
                        build_masked_patient(
                            external_patient_id=str(d["external_patient_id"]),
                            first_name=d.get("first_name"),
                            last_name=d.get("last_name"),
                            dob=str(d.get("dob") or ""),
                            phone=phone or None,
                            is_mock=False,
                        )
                    )
                return results

        except Exception as exc:
            logger.warning("EMR search failed: %s — falling back to empty results", exc)
            return []

    def get_patient(self, external_patient_id: str) -> EMRPatient | None:
        try:
            with self._engine.connect() as conn:
                query = text("""
                    SELECT
                        "Id"::text          AS external_patient_id,
                        "FirstName"         AS first_name,
                        "MI"                AS middle_name,
                        "LastName"          AS last_name,
                        "DOB"::text         AS dob,
                        "GenderId"          AS gender_id,
                        "PhoneNumber"       AS phone,
                        "MobilePhoneNumber" AS mobile_phone,
                        "Email"             AS email,
                        "SSN"               AS ssn,
                        "Address1"          AS address_line1,
                        "Address2"          AS address_line2,
                        "City"              AS city,
                        "State"             AS state,
                        "ZipCode"           AS zip,
                        "County"            AS county,
                        "MaritalStatus"     AS marital_status,
                        "Language"          AS language,
                        "Ethnicity"         AS ethnicity,
                        "IsPregnant"        AS is_pregnant,
                        "Suffix"            AS suffix
                    FROM "Patient"
                    WHERE "Id"::text = :pid
                      AND "IsDeleted" = false
                    LIMIT 1
                """)
                row = conn.execute(query, {"pid": external_patient_id}).fetchone()
                if not row:
                    return None

                d = row._asdict()
                phone = d.get("mobile_phone") or d.get("phone") or ""

                # Map GenderId: 1=Male, 2=Female, others=Other
                gender_map = {1: "Male", 2: "Female"}
                sex = gender_map.get(d.get("gender_id"), "Other")

                return EMRPatient(
                    external_patient_id=str(d["external_patient_id"]),
                    first_name=d.get("first_name") or "",
                    middle_name=d.get("middle_name"),
                    last_name=d.get("last_name") or "",
                    dob=d.get("dob"),
                    sex=sex,
                    ssn=d.get("ssn"),
                    phone=phone,
                    email=d.get("email"),
                    marital_status=d.get("marital_status"),
                    language=d.get("language"),
                    suffix=d.get("suffix"),
                    address=EMRAddress(
                        line1=d.get("address_line1"),
                        line2=d.get("address_line2"),
                        city=d.get("city"),
                        state=d.get("state"),
                        zip=d.get("zip"),
                        county=d.get("county"),
                    ),
                    insurance=[],
                    employment=[],
                    income=[],
                )
        except Exception as exc:
            logger.warning("EMR get_patient failed: %s", exc)
            return None
