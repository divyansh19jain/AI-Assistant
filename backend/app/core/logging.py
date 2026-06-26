import logging
import sys

_SENSITIVE_PATTERNS = ["ssn", "password", "dob", "date_of_birth"]


class SensitiveFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage()).lower()
        for pattern in _SENSITIVE_PATTERNS:
            if pattern in msg:
                record.msg = "[REDACTED - sensitive field detected in log]"
                record.args = ()
                break
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(SensitiveFilter())
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[handler],
    )
