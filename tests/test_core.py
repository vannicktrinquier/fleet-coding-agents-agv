from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__, db
from app.clock import FixedClock, SystemClock
from app.config import FinePolicy, Settings


def test_fixed_clock_moves_only_when_told() -> None:
    clock = FixedClock(datetime(2026, 3, 2, 23, 30, tzinfo=UTC))

    assert clock.today().isoformat() == "2026-03-02"
    clock.advance(hours=1)
    assert clock.now() == datetime(2026, 3, 3, 0, 30, tzinfo=UTC)
    assert clock.today().isoformat() == "2026-03-03"


def test_fixed_clock_normalizes_to_utc() -> None:
    jakarta = timezone(timedelta(hours=7))

    clock = FixedClock(datetime(2026, 3, 2, 6, 0, tzinfo=jakarta))

    assert clock.now() == datetime(2026, 3, 1, 23, 0, tzinfo=UTC)
    assert clock.today().isoformat() == "2026-03-01"


def test_fixed_clock_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(datetime(2026, 3, 2))


def test_fixed_clock_cannot_go_backwards() -> None:
    clock = FixedClock(datetime(2026, 3, 2, tzinfo=UTC))

    with pytest.raises(ValueError, match="backwards"):
        clock.advance(days=-1)


def test_system_clock_is_utc() -> None:
    assert SystemClock().now().tzinfo is UTC


def test_settings_from_environment(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {
            "LIBRARY_DB": str(tmp_path / "lib.db"),
            "LIBRARY_ADMIN_KEY": "  s3cret  ",
            "LIBRARY_LOAN_DAYS": "21",
            "LIBRARY_FINE_CAP_CENTS": "500",
        }
    )

    assert settings.db_path == tmp_path / "lib.db"
    assert settings.admin_api_key == "s3cret"
    assert settings.loan_days == 21
    assert settings.fines == FinePolicy(grace_days=3, daily_cents=25, cap_cents=500)


def test_settings_defaults() -> None:
    assert Settings.from_env({}) == Settings()


@pytest.mark.parametrize(
    ("name", "value"), [("LIBRARY_LOAN_DAYS", "two weeks"), ("LIBRARY_LOAN_DAYS", "0")]
)
def test_settings_reject_bad_numbers(name: str, value: str) -> None:
    with pytest.raises(ValueError, match=name):
        Settings.from_env({name: value})


def test_migrations_apply_once(tmp_path: Path) -> None:
    path = tmp_path / "library.db"
    moment = datetime(2026, 3, 2, tzinfo=UTC)

    assert db.migrate(path, moment) == ["001_init"]
    assert db.migrate(path, moment) == []
    assert db.schema_version(path) == "001_init"


def test_schema_version_of_an_empty_database(tmp_path: Path) -> None:
    assert db.schema_version(tmp_path / "empty.db") is None


def test_timestamps_are_stored_in_utc_to_the_second() -> None:
    moment = datetime(2026, 3, 2, 17, 30, 15, 999999, tzinfo=timezone(timedelta(hours=7)))

    assert db.timestamp(moment) == "2026-03-02T10:30:15+00:00"


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "schema": "001_init"}
