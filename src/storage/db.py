from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.storage.models import Base

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def get_engine(db_path: str | None = None):
    if db_path is None:
        db_path = str(DATA_DIR / "polymarket.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


def get_session(engine) -> Session:
    return Session(engine)
