# crypto_utils.py
# Credential encryption/decryption for per-user exchange API keys
import logging
from config import SETTINGS

log = logging.getLogger(__name__)

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is None:
        key = SETTINGS.CREDENTIAL_ENCRYPTION_KEY
        if not key:
            raise ValueError(
                "CREDENTIAL_ENCRYPTION_KEY not set. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        from cryptography.fernet import Fernet
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_credential(plaintext: str) -> str:
    """Encrypt a credential string. Returns base64-encoded ciphertext."""
    if not plaintext:
        return ''
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_credential(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext. Returns plaintext string."""
    if not ciphertext:
        return ''
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except Exception as e:
        log.error("Credential decryption failed: %s", e)
        return ''


def mask_secret(value: str, visible: int = 4) -> str:
    """Mask a secret for display: show last N chars only."""
    if not value or len(value) <= visible:
        return '****'
    return '*' * (len(value) - visible) + value[-visible:]


def is_encryption_configured() -> bool:
    """Check if credential encryption key is set."""
    return bool(SETTINGS.CREDENTIAL_ENCRYPTION_KEY)
