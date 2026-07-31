from fastapi import APIRouter

from app.api.routes import admin, auth, meetings, search

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(meetings.router)
api_router.include_router(search.router)
api_router.include_router(admin.router)

