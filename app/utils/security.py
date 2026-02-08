"""Security utilities — password hashing (bcrypt) and token encryption (Fernet)."""

import os
import secrets

from cryptography.fernet import Fernet
from passlib.context import CryptContext

# ---------------------------------------------------------------------------
# Password hashing (bcrypt)
# ---------------------------------------------------------------------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt.

    Args:
        plain: The plaintext password.

    Returns:
        Bcrypt hash string.
    """
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.

    Args:
        plain: The plaintext password to check.
        hashed: The stored bcrypt hash.

    Returns:
        True if the password matches.
    """
    return pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# Fernet encryption for secrets (NPM token, relay secrets, etc.)
# ---------------------------------------------------------------------------
def _get_fernet() -> Fernet:
    """Derive a Fernet key from the application SECRET_KEY.

    The SECRET_KEY from the environment is used as the basis. We pad/truncate
    it to produce a valid 32-byte URL-safe-base64 key that Fernet requires.
    """
    import base64
    import hashlib

    secret = os.environ.get("SECRET_KEY", "change-me-in-production")
    # Derive a stable 32-byte key via SHA-256
    key_bytes = hashlib.sha256(secret.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value with Fernet.

    Args:
        plaintext: Value to encrypt.

    Returns:
        Encrypted string (base64-encoded Fernet token).
    """
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted string.

    Args:
        ciphertext: Encrypted value.

    Returns:
        Original plaintext string.
    """
    f = _get_fernet()
    return f.decrypt(ciphertext.encode()).decode()


def generate_relay_secret() -> str:
    """Generate a cryptographically secure relay secret.

    Returns:
        A 32-character hex string.
    """
    return secrets.token_hex(16)


def generate_datastore_encryption_key() -> str:
    """Generate a base64-encoded 32-byte key for NetBird DataStoreEncryptionKey.

    NetBird management (Go) expects standard base64 decoding to exactly 32 bytes.

    Returns:
        A standard base64-encoded string representing 32 random bytes.
    """
    import base64

    return base64.b64encode(secrets.token_bytes(32)).decode()
