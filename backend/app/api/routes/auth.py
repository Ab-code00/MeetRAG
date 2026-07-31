from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import Auth, DbSession, correlation_id
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    digest_token,
    hash_password,
    new_refresh_token,
    verify_password,
)
from app.models import RefreshToken, Tenant, User
from app.models.enums import UserRole
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.audit import add_audit_log

router = APIRouter(prefix="/auth", tags=["authentication"])


def _issue_tokens(user: User, *, expose_refresh: bool) -> tuple[TokenResponse, RefreshToken, str]:
    settings = get_settings()
    raw_refresh, refresh_hash, refresh_expiry = new_refresh_token()
    access = create_access_token(
        user_id=user.id, tenant_id=user.tenant_id, role=user.role.value
    )
    return (
        TokenResponse(
            access_token=access,
            refresh_token=raw_refresh if expose_refresh else None,
            expires_in=settings.access_token_ttl_minutes * 60,
        ),
        RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=refresh_expiry,
            created_at=datetime.now(UTC),
        ),
        raw_refresh,
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        domain=settings.cookie_domain,
        path="/api/v1/auth",
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, request: Request, response: Response, db: DbSession
) -> TokenResponse:
    if not get_settings().allow_public_signup:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Public signup is disabled")
    tenant = Tenant(name=payload.organization_name, slug=payload.organization_slug)
    db.add(tenant)
    await db.flush()
    user = User(
        tenant_id=tenant.id,
        email=str(payload.email),
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=UserRole.OWNER,
    )
    db.add(user)
    await db.flush()
    token_response, refresh, raw_refresh = _issue_tokens(
        user, expose_refresh=payload.client_type == "extension"
    )
    db.add(refresh)
    add_audit_log(
        db,
        tenant_id=tenant.id,
        user_id=user.id,
        action="AUTH_REGISTER",
        resource_type="user",
        resource_id=user.id,
        correlation_id=correlation_id(request),
        ip_address=request.client.host if request.client else None,
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Organization or user already exists") from None
    if payload.client_type == "web":
        _set_refresh_cookie(response, raw_refresh)
    return token_response


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: DbSession
) -> TokenResponse:
    user = await db.scalar(
        select(User)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(
            Tenant.slug == payload.organization_slug,
            Tenant.is_active.is_(True),
            User.email == str(payload.email).lower(),
            User.is_active.is_(True),
        )
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user.last_login_at = datetime.now(UTC)
    token_response, refresh, raw_refresh = _issue_tokens(
        user, expose_refresh=payload.client_type == "extension"
    )
    db.add(refresh)
    add_audit_log(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="AUTH_LOGIN",
        resource_type="user",
        resource_id=user.id,
        correlation_id=correlation_id(request),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    if payload.client_type == "web":
        _set_refresh_cookie(response, raw_refresh)
    return token_response


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest, request: Request, response: Response, db: DbSession
) -> TokenResponse:
    now = datetime.now(UTC)
    raw_token = payload.refresh_token or request.cookies.get(get_settings().refresh_cookie_name)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token required")
    stored = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == digest_token(raw_token),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
    )
    if stored is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user = await db.scalar(
        select(User).where(User.id == stored.user_id, User.is_active.is_(True))
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive")
    stored.revoked_at = now
    token_response, replacement, raw_refresh = _issue_tokens(
        user, expose_refresh=payload.refresh_token is not None
    )
    db.add(replacement)
    await db.commit()
    if payload.refresh_token is None:
        _set_refresh_cookie(response, raw_refresh)
    return token_response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest, request: Request, response: Response, auth: Auth, db: DbSession
) -> Response:
    raw_token = payload.refresh_token or request.cookies.get(get_settings().refresh_cookie_name)
    stored = None
    if raw_token:
        stored = await db.scalar(
            select(RefreshToken)
            .join(User, User.id == RefreshToken.user_id)
            .where(
                RefreshToken.token_hash == digest_token(raw_token),
                User.id == auth.user_id,
                User.tenant_id == auth.tenant_id,
                RefreshToken.revoked_at.is_(None),
            )
        )
    if stored:
        stored.revoked_at = datetime.now(UTC)
        await db.commit()
    response.delete_cookie(
        key=get_settings().refresh_cookie_name,
        domain=get_settings().cookie_domain,
        path="/api/v1/auth",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserResponse)
async def me(auth: Auth, db: DbSession) -> User:
    user = await db.scalar(
        select(User).where(User.id == auth.user_id, User.tenant_id == auth.tenant_id)
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user
