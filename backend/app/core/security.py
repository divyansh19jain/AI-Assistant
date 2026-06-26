import re


def mask_name(name: str) -> str:
    """Return first char + asterisks for the rest."""
    if not name:
        return ""
    return name[0] + "*" * (len(name) - 1)


def mask_dob(dob: str) -> str:
    """Mask DOB as ****-**-DD."""
    if not dob:
        return ""
    parts = dob.split("-")
    if len(parts) == 3:
        return f"****-**-{parts[2]}"
    return "****-**-**"


def mask_phone(phone: str) -> str:
    """Return last 4 digits only."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "***-***-****"


def mask_ssn(ssn: str) -> str:
    """Return ***-**-XXXX."""
    if not ssn:
        return ""
    digits = re.sub(r"\D", "", ssn)
    return f"***-**-{digits[-4:]}" if len(digits) >= 4 else "***-**-****"


def sanitize_metadata(data: dict) -> dict:
    """Remove sensitive keys before storing in audit log."""
    sensitive_keys = {"ssn", "dob", "full_dob", "address", "email", "phone", "password"}
    return {k: "***" if k.lower() in sensitive_keys else v for k, v in data.items()}
