"""Regression tests for Settings._clear_stale_docker_envars().

The env-clearing logic previously popped DATABASE_URL/DATABASE_URL_SYNC (and
QDRANT_URL, REDIS_URL, CELERY_*, AWS_*, OPENROUTER_*) from os.environ on every
get_settings() call — even inside containers (Render/Docker), where the process
environment IS the configuration. That made cloud deploys fall back to the
localhost defaults and fail to connect. These tests pin the fixed behavior:

- no .env file (container)  -> env vars are always honored
- .env present (dev host)   -> only stale docker-compose values are cleared
"""

import os

from app.core.config import Settings, get_settings


def test_no_dotenv_means_env_is_never_cleared(monkeypatch, tmp_path) -> None:
    """Container simulation: no .env file -> process environment is the config."""
    monkeypatch.chdir(tmp_path)  # empty temp dir, no .env
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql+asyncmy://avnadmin:pw@mysql-123.aivencloud.com:18605/defaultdb",
    )
    monkeypatch.setenv("QDRANT_URL", "https://xyz.cloud.qdrant.io:6333")

    Settings._clear_stale_docker_envars()

    assert os.environ["DATABASE_URL"] == (
        "mysql+asyncmy://avnadmin:pw@mysql-123.aivencloud.com:18605/defaultdb"
    )
    assert os.environ["QDRANT_URL"] == "https://xyz.cloud.qdrant.io:6333"


def test_dotenv_pops_only_stale_docker_markers(monkeypatch, tmp_path) -> None:
    """Dev-host simulation: .env present -> stale compose values cleared, real ones kept."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DATABASE_URL=mysql+asyncmy://root:devpw@localhost:3306/meetai\n")
    monkeypatch.setenv("DATABASE_URL", "mysql+asyncmy://meetai:password@mysql:3306/meetai")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("QDRANT_URL", "https://xyz.cloud.qdrant.io:6333")

    Settings._clear_stale_docker_envars()

    # Stale docker-compose hosts are removed so the .env file wins...
    assert "DATABASE_URL" not in os.environ
    assert "REDIS_URL" not in os.environ
    # ...but a real value is never cleared.
    assert os.environ["QDRANT_URL"] == "https://xyz.cloud.qdrant.io:6333"


def test_get_settings_honors_container_env(monkeypatch, tmp_path) -> None:
    """End-to-end: a container without .env resolves the injected DB URLs."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql+asyncmy://avnadmin:pw@mysql-123.aivencloud.com:18605/defaultdb",
    )
    monkeypatch.setenv(
        "DATABASE_URL_SYNC",
        "mysql+pymysql://avnadmin:pw@mysql-123.aivencloud.com:18605/defaultdb",
    )
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert "aivencloud.com" in settings.database_url
        assert "aivencloud.com" in settings.database_url_sync
    finally:
        get_settings.cache_clear()
