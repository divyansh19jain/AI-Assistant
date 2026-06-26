import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.core.security import sanitize_metadata


def log_event(
    db: Session,
    event_type: str,
    session_id: str | None = None,
    patient_external_id_hint: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Write an audit log entry. Import lazily to avoid circular imports."""
    from app.db.models import AuditLog

    safe_meta = sanitize_metadata(metadata or {})
    entry = AuditLog(
        event_type=event_type,
        session_id=session_id,
        patient_external_id_masked=patient_external_id_hint,
        metadata_json=json.dumps(safe_meta),
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()
