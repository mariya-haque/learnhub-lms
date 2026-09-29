from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import get_settings

settings = get_settings()

db_url = settings.database_url

if db_url.startswith("sqlite"):
    # SQLite hands a connection to one thread by default; FastAPI's threadpool
    # moves sync endpoints between threads, so that check has to be relaxed.
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
else:
    # Ensure psycopg3 is used rather than the missing psycopg2 driver.
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(db_url, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
