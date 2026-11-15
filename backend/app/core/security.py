"""
Password hashing, JWT session tokens and one-time approval tokens.

Secrets never appear in logs. Approval tokens are stored only as SHA-256
digests; the raw value is returned to the user exactly once. The browser
worker receives an HMAC-signed proof, not the database record.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": expire,
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("typ") != "access":
        return None
    return payload.get("sub")


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_approval_token() -> tuple[str, str]:
    """Return (raw_token, sha256_digest). Only the digest is persisted."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def sign_approval_proof(application_id: str, token_hash: str, nonce: str, expires_at: datetime) -> str:
    """HMAC proof the browser worker can verify without any DB access."""
    message = f"{application_id}:{token_hash}:{nonce}:{int(expires_at.timestamp())}"
    secret = settings.APPROVAL_SIGNING_SECRET or settings.JWT_SECRET
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def build_approval_proof(
    application_id: str, raw_token: str, nonce: str, expires_at: datetime
) -> dict:
    token_hash = hash_token(raw_token)
    return {
        "application_id": application_id,
        "nonce": nonce,
        "expires_at": int(expires_at.timestamp()),
        "signature": sign_approval_proof(application_id, token_hash, nonce, expires_at),
    }


def verify_hmac(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Verify `sha256=<hex>` webhook signatures in constant time."""
    if not secret or not signature_header:
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, signature_header.strip())
