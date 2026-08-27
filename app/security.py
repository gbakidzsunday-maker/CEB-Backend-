import hashlib
from datetime import datetime, timedelta
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash
from jose import jwt, JWTError

from app.config import settings

_ph = PasswordHasher()


# ---------- Password hashing (Argon2, per Section 3.2) ----------

def hash_password(plain_password: str) -> str:
    return _ph.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, plain_password)
    except (VerifyMismatchError, InvalidHash):
        return False


# ---------- JWT session tokens ----------

def create_access_token(subject: str, role: str, expires_minutes: Optional[int] = None) -> str:
    expire = datetime.utcnow() + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc


# ---------- Checksums (tamper-evidence layer, Section 3.5.3) ----------

def compute_checksum(*fields) -> str:
    """
    Deterministic SHA-256 checksum over a record's meaningful fields.
    Recomputing this later and comparing against the stored value
    reveals unauthorised modification of a Response/Result/SecurityLog row.
    """
    payload = "|".join(str(f) for f in fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
