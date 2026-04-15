import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.storage.models import Base


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session
