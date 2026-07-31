#!/bin/bash
# MeetAI Local Development Server — Run Script (bash/Git Bash)
# Clears Docker environment variables and starts the API server.

echo "[MeetAI] Clearing Docker environment variables..."

unset QDRANT_URL DATABASE_URL DATABASE_URL_SYNC
unset AWS_ENDPOINT_URL AWS_PUBLIC_ENDPOINT_URL
unset REDIS_URL CELERY_BROKER_URL CELERY_RESULT_BACKEND
unset OPENROUTER_EMBEDDING_MODEL ANTHROPIC_BASE_URL
unset OPENROUTER_BASE_URL OPENROUTER_LLM_MODEL OPENROUTER_API_KEY
unset OPENROUTER_APP_NAME OPENROUTER_APP_URL

echo "[MeetAI] Starting Uvicorn server..."
cd "$(dirname "$0")/backend"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
