# logging_utils.py
# Structured logging with JSON output, correlation IDs, and secret redaction.
import re
import json
import time
import logging
import contextvars
import uuid

# Correlation ID for tracing requests through the system
correlation_id_var = contextvars.ContextVar('correlation_id', default='')

# High-entropy pattern for detecting potential secrets
_SECRET_PATTERN = re.compile(r'[A-Za-z0-9+/=]{24,}')
_KEY_PATTERN = re.compile(r'(apiKey|secret|password|token|key|credential)\s*[=:]\s*\S+', re.IGNORECASE)


def set_correlation_id(uid: int = 0, op: str = '') -> str:
    """Set correlation ID for the current async context. Returns the ID."""
    cid = f"{uid}:{op}:{uuid.uuid4().hex[:8]}"
    correlation_id_var.set(cid)
    return cid


def get_correlation_id() -> str:
    return correlation_id_var.get()


def redact(text: str) -> str:
    """Remove potential secrets from log text."""
    if not text:
        return text
    # Redact key=value patterns
    text = _KEY_PATTERN.sub(lambda m: m.group().split('=')[0] + '=[REDACTED]' if '=' in m.group()
                            else m.group().split(':')[0] + ':[REDACTED]', text)
    # Redact high-entropy strings (but not common words)
    def _check_entropy(m):
        s = m.group()
        # Skip common non-secret patterns
        if s in ('AUTOINCREMENT', 'DEFAULT', 'PRIMARY', 'INTEGER', 'RETURNING'):
            return s
        if len(set(s)) < 8:  # low character diversity = probably not a secret
            return s
        return f'[REDACTED:{len(s)}chars]'
    text = _SECRET_PATTERN.sub(_check_entropy, text)
    return text


class StructuredFormatter(logging.Formatter):
    """JSON-line log formatter with correlation_id and redaction."""

    def format(self, record):
        log_entry = {
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(record.created)),
            'level': record.levelname,
            'module': record.module,
            'func': record.funcName,
            'message': redact(record.getMessage()),
        }
        cid = correlation_id_var.get()
        if cid:
            log_entry['cid'] = cid
        if record.exc_info and record.exc_info[0]:
            log_entry['exception'] = redact(self.formatException(record.exc_info))
        return json.dumps(log_entry, default=str)


class SafeFormatter(logging.Formatter):
    """Human-readable formatter with redaction (for development)."""

    def __init__(self):
        super().__init__('%(asctime)s %(levelname)-8s %(name)s: %(message)s')

    def format(self, record):
        record.msg = redact(str(record.msg))
        return super().format(record)


def configure_logging(structured: bool = False, level: str = 'INFO'):
    """
    Configure root logger.
    structured=True: JSON lines (production)
    structured=False: human-readable with redaction (development)
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler()
    if structured:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(SafeFormatter())

    root.addHandler(handler)

    # Suppress noisy libraries
    for lib in ('httpx', 'httpcore', 'urllib3', 'ccxt', 'telegram.ext'):
        logging.getLogger(lib).setLevel(logging.WARNING)
