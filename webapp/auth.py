"""Password hashing helpers. Login/session state itself lives in
nicegui's app.storage.user (see main.py); this module only deals with
turning passwords into hashes and back.
"""

import secrets
import string

import bcrypt


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))


def generate_temp_password(length: int = 12) -> str:
    """Used when an admin/teacher creates an account -- the account holder
    changes it after first login."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
