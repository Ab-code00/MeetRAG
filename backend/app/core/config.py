import os
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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
    # Pipeline execution: auto (inline in development, Celery in production) |
    # inline | celery. Inline runs the whole pipeline synchronously inside the
    # request — required on free hosting where no broker/worker is available.
    pipeline_mode: str = "auto"
    # CORS origins for credentialed cross-origin requests (comma-separated in
    # env). "*" is fine for local development; production must list the exact
    # frontend origin(s) because credentialed requests can't use wildcards.
    # NoDecode: pydantic-settings would otherwise try to JSON-decode the list
    # env value and crash on a plain comma-separated string.
    cors_origins: Annotated[list[str], NoDecode] = ["*"]

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
    # API keys must never be hardcoded defaults — set DEEPGRAM_API_KEY in .env
    # only. (A previous real key committed here was leaked; rotate it.)
    deepgram_api_key: str = ""
    deepgram_stt_model: str = "nova-3"
    # auto | groq | deepgram — auto prefers Deepgram when DEEPGRAM_API_KEY is set
    transcription_provider: str = "auto"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_llm_model: str = "openai/gpt-5.6-luna"
    # Hard cap on total output tokens (answer + any chain-of-thought) so a
    # slow/queueing provider can't run to the context limit and stall chats.
    openrouter_llm_max_tokens: int = 2048
    openrouter_embedding_model: str = "openai/text-embedding-3-small"
    openrouter_app_url: str = ""
    openrouter_app_name: str = "MeetAI"

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "meeting_chunks"
    embedding_dimension: int = 1536

    cleaning_version: str = "clean-v1"
    chunking_version: str = "speaker-context-v2"
    answer_prompt_version: str = "grounded-v1"
    # Answer-generation prompt bounds: feed at most this many evidence chunks
    # and truncate each block to this many characters so the prompt (and thus
    # first-token latency) stays small.
    answer_evidence_limit: int = 5
    answer_evidence_max_chars: int = 2000
    # Multi-turn chat context: the last N question/answer exchanges from the
    # session are sent to the LLM so follow-ups like "was this his answer?"
    # have referents. Each prior message is truncated to this many characters.
    chat_history_turns: int = 5
    chat_history_max_chars: int = 1500
    chunk_target_tokens: int = 700
    chunk_max_tokens: int = 900
    # Two-level chunking (see chunking_strategy.md): context chunks group
    # several consecutive speaker turns; overlap carries whole turns forward.
    chunk_min_turns: int = 4
    chunk_max_turns: int = 10
    chunk_overlap_turns: int = 2
    retrieval_top_k: int = 8
    retrieval_score_threshold: float = 0.10
    # Hybrid retrieval: dense top-N + BM25 sparse top-N candidates fused via RRF.
    retrieval_hybrid_candidates: int = 40

    @property
    def stt_provider(self) -> str:
        """Resolve the active STT provider (groq or deepgram)."""
        if self.transcription_provider != "auto":
            return self.transcription_provider
        return "deepgram" if self.deepgram_api_key else "groq"

    @property
    def stt_model(self) -> str:
        """Resolve the active STT model for the resolved provider."""
        return self.deepgram_stt_model if self.stt_provider == "deepgram" else self.groq_stt_model

    @field_validator("transcription_provider")
    @classmethod
    def validate_transcription_provider(cls, value: object) -> str:
        if value not in ("auto", "groq", "deepgram"):
            raise ValueError("TRANSCRIPTION_PROVIDER must be one of: auto, groq, deepgram")
        return str(value)

    @field_validator("pipeline_mode")
    @classmethod
    def validate_pipeline_mode(cls, value: object) -> str:
        if value not in ("auto", "inline", "celery"):
            raise ValueError("PIPELINE_MODE must be one of: auto, inline, celery")
        return str(value)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

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
