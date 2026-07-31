@echo off
REM ============================================================================
REM MeetAI Local Development Server — Run Script
REM Clears Docker environment variables and starts the API server.
REM ============================================================================

echo [MeetAI] Clearing Docker environment variables...

set QDRANT_URL=
set DATABASE_URL=
set DATABASE_URL_SYNC=
set AWS_ENDPOINT_URL=
set AWS_PUBLIC_ENDPOINT_URL=
set REDIS_URL=
set CELERY_BROKER_URL=
set CELERY_RESULT_BACKEND=
set OPENROUTER_EMBEDDING_MODEL=
set ANTHROPIC_BASE_URL=
set OPENROUTER_BASE_URL=
set OPENROUTER_LLM_MODEL=
set OPENROUTER_API_KEY=
set OPENROUTER_APP_NAME=
set OPENROUTER_APP_URL=

echo [MeetAI] Starting Uvicorn server...
cd /d "%~dp0backend"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

if %ERRORLEVEL% NEQ 0 (
    echo [MeetAI] Server exited with error code %ERRORLEVEL%
    pause
)
