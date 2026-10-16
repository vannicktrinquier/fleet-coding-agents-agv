"""Shared fixtures: a fresh SQLite file, a fixed clock and an API client per test."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import Settings
from app.main import create_app
from tests.support import Library

ADMIN_KEY = "test-admin-key"
START = datetime(2026, 3, 2, 10, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START)


@pytest.fixture
def settings() -> Settings:
    return Settings(admin_api_key=ADMIN_KEY)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "library.db"


@pytest.fixture
def app(db_path: Path, clock: FixedClock, settings: Settings) -> FastAPI:
    return create_app(db_path=db_path, clock=clock, settings=settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin() -> dict[str, str]:
    return {"X-API-Key": ADMIN_KEY}


@pytest.fixture
def library(client: TestClient, admin: dict[str, str]) -> Library:
    return Library(client, admin)
