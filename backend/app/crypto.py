import base64
import hashlib

from cryptography.fernet import Fernet

from . import config


def _derive_dev_key() -> bytes:
    """Deterministic fallback so dev/test environments work with zero extra
    setup. Production must set TOOL_ENCRYPTION_KEY explicitly (see .env.example)."""
    digest = hashlib.sha256(config.SESSION_SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    key = config.TOOL_ENCRYPTION_KEY.encode() if config.TOOL_ENCRYPTION_KEY else _derive_dev_key()
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
