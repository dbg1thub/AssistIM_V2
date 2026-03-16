"""Password hashing helpers."""

from __future__ import annotations

import base64
import hashlib
import os

try:
    import bcrypt  # type: ignore
except ImportError:  # pragma: no cover
    bcrypt = None


def hash_password(password: str) -> str:
    """Hash a password using bcrypt, with a PBKDF2 fallback."""
    if bcrypt is not None:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return "pbkdf2$" + base64.b64encode(salt + derived).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password hash."""
    if password_hash.startswith("pbkdf2$"):
        raw = base64.b64decode(password_hash.split("$", 1)[1].encode("ascii"))
        salt, expected = raw[:16], raw[16:]
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return derived == expected

    if bcrypt is None:
        return False

    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
