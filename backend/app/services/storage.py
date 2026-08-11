from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import boto3
from botocore.client import Config

from app.core.config import get_settings

LOCAL_STORAGE_ROOT = Path("local_storage") / "recordings"
_MAX_FILENAME_CHARS = 100


def safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip(".-")
    return cleaned[:_MAX_FILENAME_CHARS].strip(".-") or "recording"


def recording_object_key(tenant_id: str, meeting_id: str, recording_id: str, filename: str) -> str:
    return f"tenants/{tenant_id}/meetings/{meeting_id}/{recording_id}/{safe_filename(filename)}"


# ── Local filesystem helpers (development fallback) ──

def get_local_path(object_key: str) -> Path:
    """Return the local filesystem path for a storage object key.

    Local development uses a flattened ``{recording_id}/{filename}`` layout
    keyed on the unique recording UUID, keeping paths well under the Windows
    MAX_PATH (260-char) limit that the legacy deep ``tenants/.../meetings/...``
    nesting could exceed with long filenames.
    """
    parts = object_key.split("/")
    if len(parts) >= 2 and parts[-1]:
        return LOCAL_STORAGE_ROOT / parts[-2] / parts[-1]
    return _legacy_local_path(object_key)


def _legacy_local_path(object_key: str) -> Path:
    """Legacy deep path used for recordings saved before the flattened layout."""
    return LOCAL_STORAGE_ROOT / object_key


def _resolve_local_path(object_key: str) -> Path:
    """Resolve a recording file, preferring the flattened path over the legacy one."""
    path = get_local_path(object_key)
    if path.exists():
        return path
    legacy = _legacy_local_path(object_key)
    if legacy.exists():
        return legacy
    raise FileNotFoundError(f"Local recording not found: {object_key}")


def save_file_locally(object_key: str, content: bytes) -> Path:
    """Save file content to local disk under the given object key."""
    path = get_local_path(object_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def head_local_file(object_key: str) -> dict[str, Any]:
    """Return metadata for a locally stored file (mimics S3 head_object)."""
    path = _resolve_local_path(object_key)
    return {
        "ContentLength": path.stat().st_size,
        "ContentType": "",
    }


def _storage_available() -> bool:
    """Check whether S3 credentials / endpoint are configured."""
    settings = get_settings()
    return bool(settings.aws_endpoint_url or (settings.aws_access_key_id and settings.aws_secret_access_key))


# ── S3 client (production) ──

def _client(endpoint_url: str | None) -> Any:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


@lru_cache
def internal_s3_client() -> Any:
    return _client(get_settings().aws_endpoint_url)


@lru_cache
def public_s3_client() -> Any:
    settings = get_settings()
    return _client(settings.aws_public_endpoint_url or settings.aws_endpoint_url)


# ── Unified API ──

def create_upload_url(*, object_key: str, content_type: str, expires_seconds: int = 900) -> str:
    """Generate a presigned S3 upload URL, or raise if S3 is not configured."""
    if not _storage_available():
        raise RuntimeError(
            "S3 is not configured. Use the /upload endpoint to upload files directly "
            "when running in development mode."
        )
    settings = get_settings()
    params: dict[str, Any] = {
        "Bucket": settings.aws_s3_bucket,
        "Key": object_key,
        "ContentType": content_type,
    }
    if not settings.aws_endpoint_url:
        # Native AWS S3 only: request SSE-S3 (x-amz-server-side-encryption).
        # S3-compatible providers (Cloudflare R2, Backblaze B2, LocalStack)
        # encrypt at rest themselves and may reject the SSE header on
        # presigned PUTs.
        params["ServerSideEncryption"] = "AES256"
    return cast(
        str,
        public_s3_client().generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=expires_seconds,
        ),
    )


def head_recording(object_key: str) -> dict[str, Any]:
    """Check if a recording exists. Falls back to local filesystem if S3 is not configured."""
    if not _storage_available():
        return head_local_file(object_key)
    return cast(
        dict[str, Any],
        internal_s3_client().head_object(
            Bucket=get_settings().aws_s3_bucket,
            Key=object_key,
        ),
    )


def download_recording(object_key: str, destination: str) -> None:
    """Download a recording to a local path. Falls back to local filesystem if S3 is not configured."""
    if not _storage_available():
        import shutil
        shutil.copy2(str(_resolve_local_path(object_key)), destination)
        return
    internal_s3_client().download_file(get_settings().aws_s3_bucket, object_key, destination)
