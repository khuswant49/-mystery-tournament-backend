import os
import tempfile

os.environ.setdefault("ADMIN_PIN", "test-pin")
os.environ.setdefault("COOKIE_SECRET", "test-secret")

import pytest
from fastapi.testclient import TestClient
from sqlmodel import create_engine

import app.db as db_module
from app.main import _seed_cars, app as fastapi_app


@pytest.fixture()
def client():
    """Fresh SQLite-backed DB per test, so tests never see each other's rounds."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    db_module.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    db_module.init_db()
    _seed_cars()

    with TestClient(fastapi_app) as test_client:
        yield test_client

    # Windows keeps the sqlite file locked until every pooled connection is
    # closed -- dispose() first or os.remove() raises PermissionError.
    db_module.engine.dispose()
    os.remove(path)
