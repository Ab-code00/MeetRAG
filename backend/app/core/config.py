import os
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Environment variables from docker-compose that leak into the local shell.
# These override the .env file (pydantic-settings gives env vars priority),
# but their values (e.g. QDRANT_URL=http://qdrant:6333) point to containers
# that don't exist locally.  Explicitly clear them before loading settings.
_DOCKER_ENV_KEYS: frozenset[str] = frozenset({
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "DATABASE_URL",
    "DATABASE_URL_SYNC",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "AWS_ENDPOINT_URL",
    "AWS_PUBLIC_ENDPOINT_URL",
    "OPENROUTER_EMBEDDING_MODEL",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_LLM_MODEL",
    "ANTHROPIC_BASE_URL",
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    @classmethod
    def _clear_stale_docker_envars(cls) -> None:
        """
        Remove docker-compose environment variables that leaked into the
        developer's shell, so that the local ``.env`` file takes effect.

        pydantic-settings gives OS environment variables priority over
        ``.env``, but when a developer has run ``docker compose up`` or
        ``conda env config vars`` the container addresses persist in the
        shell and break local development.
        """
        for key in _DOCKER_ENV_KEYS:
            os.environ.pop(key, None)

    app_env: str = "development"
    app_name: str = "MeetAI"
    app_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    log_level: str = "INFO"
    secret_key: str = Field(default="development-only-change-me", min_length=16)
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    refresh_cookie_name: str = "meetai_refresh"
    cookie_domain: str | None = None
    allow_public_signup: bool = True

    database_url: str = "mysql+asyncmy://meetai:password@localhost:3306/meetai"
    database_url_sync: str = "mysql+pymysql://meetai:password@localhost:3306/meetai"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"  # noqa: S105 - LocalStack-only default
    aws_region: str = "us-east-1"
    aws_s3_bucket: str = "meetai-recordings"
    aws_endpoint_url: str | None = "http://localhost:4566"
    aws_public_endpoint_url: str | None = "http://localhost:4566"

    groq_api_key: str = ""
    groq_stt_model: str = "whisper-large-v3"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_llm_model: str = "OpenAI: gpt-oss-120b"
    openrouter_embedding_model: str = "openai/text-embedding-3-small"
    openrouter_app_url: str = ""
    openrouter_app_name: str = "MeetAI"

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "meeting_chunks"
    embedding_dimension: int = 1536

    cleaning_version: str = "clean-v1"
    chunking_version: str = "speaker-semantic-v1"
    answer_prompt_version: str = "grounded-v1"
    chunk_target_tokens: int = 700
    chunk_max_tokens: int = 900
    chunk_overlap_ratio: float = 0.15
    retrieval_top_k: int = 8
    retrieval_score_threshold: float = 0.10

    @field_validator("aws_endpoint_url", "aws_public_endpoint_url", "cookie_domain", mode="before")
    @classmethod
    def blank_endpoint_is_none(cls, value: object) -> object:
        return None if value == "" else value

    def validate_production(self) -> None:
        if self.app_env == "production" and self.secret_key == "development-only-change-me":  # noqa: S105
            raise RuntimeError("SECRET_KEY must be configured in production")


@lru_cache
def get_settings() -> Settings:
    Settings._clear_stale_docker_envars()
    settings = Settings()
    settings.validate_production()
    return settings
