from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

sync_engine = create_engine(
    get_settings().database_url_sync, pool_pre_ping=True, pool_recycle=1800
)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False, autoflush=False)

