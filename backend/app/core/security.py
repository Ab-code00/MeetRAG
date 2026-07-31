import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hash = PasswordHash.recommended()


@dataclass(frozen=True)
class TokenClaims:
    user_id: str
    tenant_id: str
    role: str
    token_type: str
    jti: str


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def create_access_token(*, user_id: str, tenant_id: str, role: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "tid": tenant_id,
        "role": role,
        "type": "access",
        "jti": secrets.token_urlsafe(16),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        "iss": settings.app_name,
        "aud": "meetai-api",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str, expected_type: str = "access") -> TokenClaims:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            audience="meetai-api",
            issuer=settings.app_name,
        )
    except jwt.PyJWTError as exc:
        raise ValueError("Invalid or expired token") from exc
    if payload.get("type") != expected_type:
        raise ValueError("Incorrect token type")
    return TokenClaims(
        user_id=str(payload["sub"]),
        tenant_id=str(payload["tid"]),
        role=str(payload["role"]),
        token_type=str(payload["type"]),
        jti=str(payload["jti"]),
    )


def new_refresh_token() -> tuple[str, bytes, datetime]:
    settings = get_settings()
    token = secrets.token_urlsafe(64)
    return (
        token,
        digest_token(token),
        datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
    )


def digest_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()

