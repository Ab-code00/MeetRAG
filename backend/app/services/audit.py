from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def add_audit_log(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    correlation_id: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            correlation_id=correlation_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details_json=details,
            created_at=datetime.now(UTC),
        )
    )

