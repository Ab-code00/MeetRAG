from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models import User
from app.models.enums import UserRole

# Simple Bearer token auth for Swagger UI Authorize button
# Just paste: eyJhbGciOi... (your access_token)
bearer_scheme = HTTPBearer(auto_error=False)
DbSession = Annotated[AsyncSession, Depends(get_db)]


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    tenant_id: str
    role: UserRole


async def get_auth_context(
    request: Request, db: DbSession,
    _http_credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthContext:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    # Try Swagger UI Authorize button first, then raw header
    token = _http_credentials.credentials if _http_credentials else None
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ")
    if not token:
        raise unauthorized
    try:
        claims = decode_token(token)
        role = UserRole(claims.role)
    except (ValueError, KeyError):
        raise unauthorized from None
    user = await db.scalar(
        select(User).where(
            User.id == claims.user_id,
            User.tenant_id == claims.tenant_id,
            User.is_active.is_(True),
        )
    )
    if user is None:
        raise unauthorized
    return AuthContext(user_id=user.id, tenant_id=user.tenant_id, role=role)


Auth = Annotated[AuthContext, Depends(get_auth_context)]


def require_roles(
    *roles: UserRole,
) -> Callable[[AuthContext], Coroutine[Any, Any, AuthContext]]:
    async def dependency(auth: Auth) -> AuthContext:
        if auth.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return auth

    return dependency


def correlation_id(request: Request) -> str:
    return str(request.state.correlation_id)
