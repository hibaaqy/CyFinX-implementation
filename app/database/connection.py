"""Database connection configuration for CyFinX."""

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
DB_DIR = ROOT / "data" / "database"

# Colab can mount the operational database from Google Drive and set this
# environment variable without changing the source code.
_configured_db_path = os.getenv("CYFINX_OPERATIONAL_DB")
if _configured_db_path:
    OPERATIONAL_DB_PATH = Path(_configured_db_path).expanduser()
    if not OPERATIONAL_DB_PATH.is_absolute():
        OPERATIONAL_DB_PATH = ROOT / OPERATIONAL_DB_PATH
else:
    OPERATIONAL_DB_PATH = DB_DIR / "cyfinx_operational_v1.db"

DB_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{OPERATIONAL_DB_PATH.as_posix()}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def enable_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)
