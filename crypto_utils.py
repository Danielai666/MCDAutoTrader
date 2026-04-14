# crypto_utils.py
# Credential encryption with envelope encryption (AEAD).
# V1: Simple Fernet (backward compat for existing data)
# V2: Per-record DataKey encrypted by MasterKey using AESGCM (production)
import os
import logging
from config import SETTINGS

log = logging.getLogger(__name__)

# -------------------------------------------------------------------
# V1: Legacy Fernet (backward compat)
# -------------------------------------------------------------------
_fernet = None

def _get_fernet():
    global _fernet
    if _fernet is None:
        key = SETTINGS.CREDENTIAL_ENCRYPTION_KEY
        if not key:
            raise ValueError("CREDENTIAL_ENCRYPTION_KEY not set")
        from cryptography.fernet import Fernet
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_credential_v1(plaintext: str) -> str:
    """V1 Fernet encryption. Returns base64-encoded ciphertext."""
    if not plaintext:
        return ''
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_credential_v1(ciphertext: str) -> str:
    """V1 Fernet decryption."""
    if not ciphertext:
        return ''
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except Exception as e:
        log.error("V1 credential decryption failed: %s", e)
        return ''


# -------------------------------------------------------------------
# V2: Envelope encryption (AEAD) — production
# Each credential gets its own random DataKey.
# DataKey encrypts the secret (AESGCM).
# MasterKey encrypts the DataKey (AESGCM).
# -------------------------------------------------------------------

def _get_master_key(version: int = None) -> bytes:
    """Get the master key for the given version from env vars."""
    if version and version > 1:
        key_var = f'ENCRYPTION_MASTER_KEY_V{version}'
        key = os.getenv(key_var, '')
        if key:
            return _normalize_key(key)
    # Default: use CREDENTIAL_ENCRYPTION_KEY (V1 master key)
    key = SETTINGS.CREDENTIAL_ENCRYPTION_KEY
    if not key:
        raise ValueError("No encryption master key configured")
    return _normalize_key(key)


def _normalize_key(key_str: str) -> bytes:
    """Ensure key is exactly 32 bytes for AESGCM-256."""
    import hashlib
    raw = key_str.encode() if isinstance(key_str, str) else key_str
    # Use SHA-256 to derive a consistent 32-byte key
    return hashlib.sha256(raw).digest()


def envelope_encrypt(plaintext: str) -> tuple:
    """
    Envelope encryption (V2):
    1. Generate random 32-byte DataKey
    2. Encrypt plaintext with DataKey (AESGCM)
    3. Encrypt DataKey with MasterKey (AESGCM)
    Returns: (encrypted_data_b64, encrypted_datakey_b64, version=2)
    """
    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not plaintext:
        return '', '', 2

    # Generate random data key
    data_key = AESGCM.generate_key(bit_length=256)
    data_nonce = os.urandom(12)

    # Encrypt plaintext with data key
    aesgcm_data = AESGCM(data_key)
    encrypted_data = aesgcm_data.encrypt(data_nonce, plaintext.encode(), None)
    # Pack nonce + ciphertext
    encrypted_data_packed = data_nonce + encrypted_data
    encrypted_data_b64 = base64.b64encode(encrypted_data_packed).decode()

    # Encrypt data key with master key
    master_key = _get_master_key()
    master_nonce = os.urandom(12)
    aesgcm_master = AESGCM(master_key)
    encrypted_dk = aesgcm_master.encrypt(master_nonce, data_key, None)
    encrypted_dk_packed = master_nonce + encrypted_dk
    encrypted_dk_b64 = base64.b64encode(encrypted_dk_packed).decode()

    return encrypted_data_b64, encrypted_dk_b64, 2


def envelope_decrypt(encrypted_data_b64: str, encrypted_dk_b64: str, version: int = 2) -> str:
    """
    Decrypt using envelope encryption.
    V1: falls back to Fernet (encrypted_data_b64 is the Fernet token, encrypted_dk_b64 is ignored)
    V2: AESGCM envelope decryption
    """
    if not encrypted_data_b64:
        return ''

    if version == 1:
        return decrypt_credential_v1(encrypted_data_b64)

    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        # Decrypt data key with master key
        master_key = _get_master_key(version)
        dk_packed = base64.b64decode(encrypted_dk_b64)
        master_nonce = dk_packed[:12]
        dk_ciphertext = dk_packed[12:]
        aesgcm_master = AESGCM(master_key)
        data_key = aesgcm_master.decrypt(master_nonce, dk_ciphertext, None)

        # Decrypt data with data key
        data_packed = base64.b64decode(encrypted_data_b64)
        data_nonce = data_packed[:12]
        data_ciphertext = data_packed[12:]
        aesgcm_data = AESGCM(data_key)
        plaintext = aesgcm_data.decrypt(data_nonce, data_ciphertext, None)

        return plaintext.decode()
    except Exception as e:
        log.error("V2 envelope decryption failed: %s", e)
        return ''


# -------------------------------------------------------------------
# Convenience wrappers (auto-detect version)
# -------------------------------------------------------------------
def encrypt_credential(plaintext: str) -> str:
    """Encrypt using best available method. Returns V1 Fernet for backward compat."""
    return encrypt_credential_v1(plaintext)


def decrypt_credential(ciphertext: str) -> str:
    """Decrypt V1 Fernet credential."""
    return decrypt_credential_v1(ciphertext)


def encrypt_exchange_keys(api_key: str, api_secret: str) -> dict:
    """
    Encrypt exchange credentials using envelope encryption (V2).
    Returns dict ready for storage: {api_key_enc, api_secret_enc, data_key_enc, encryption_version}
    """
    key_enc, dk_enc_1, ver = envelope_encrypt(api_key)
    # Use same data key for both key and secret (generate once, encrypt both)
    # Actually, for simplicity each gets its own envelope
    secret_enc, dk_enc_2, _ = envelope_encrypt(api_secret)
    # Store both data keys concatenated (key:secret format)
    dk_combined = f"{dk_enc_1}|{dk_enc_2}"
    return {
        'api_key_enc': key_enc,
        'api_secret_enc': secret_enc,
        'data_key_enc': dk_combined,
        'encryption_version': ver,
    }


def decrypt_exchange_keys(api_key_enc: str, api_secret_enc: str,
                          data_key_enc: str, encryption_version: int) -> tuple:
    """
    Decrypt exchange credentials.
    Returns (api_key, api_secret) as plaintext strings.
    """
    if encryption_version == 1:
        return decrypt_credential_v1(api_key_enc), decrypt_credential_v1(api_secret_enc)

    # V2: split data key
    parts = (data_key_enc or '').split('|')
    dk_key = parts[0] if len(parts) > 0 else ''
    dk_secret = parts[1] if len(parts) > 1 else dk_key

    api_key = envelope_decrypt(api_key_enc, dk_key, encryption_version)
    api_secret = envelope_decrypt(api_secret_enc, dk_secret, encryption_version)
    return api_key, api_secret


# -------------------------------------------------------------------
# Utilities
# -------------------------------------------------------------------
def mask_secret(value: str, visible: int = 4) -> str:
    """Mask a secret for display: show last N chars only."""
    if not value or len(value) <= visible:
        return '****'
    return '*' * (len(value) - visible) + value[-visible:]


def is_encryption_configured() -> bool:
    """Check if credential encryption key is set."""
    return bool(SETTINGS.CREDENTIAL_ENCRYPTION_KEY)
