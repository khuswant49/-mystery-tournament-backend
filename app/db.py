from sqlmodel import SQLModel, Session, create_engine

from app.config import DATABASE_URL

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)


def init_db():
    # V1 simplicity: no Alembic migrations, just create-if-missing on startup.
    # Fine for a single-event project with a small, stable schema.
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
