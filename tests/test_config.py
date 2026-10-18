import os
from unittest.mock import patch

import pytest

from app.config import Settings, _env_int


def test_settings_from_env_parses_all_variables() -> None:
    env = {
        "LIBRARY_DB": "custom.db",
        "LIBRARY_ADMIN_KEY": "secret",
        "LIBRARY_LOAN_DAYS": "7",
        "LIBRARY_MAX_ACTIVE_LOANS": "3",
        "LIBRARY_MAX_RENEWALS": "1",
        "LIBRARY_FINE_BLOCK_CENTS": "200",
        "LIBRARY_FINE_GRACE_DAYS": "1",
        "LIBRARY_FINE_DAILY_CENTS": "10",
        "LIBRARY_FINE_CAP_CENTS": "500",
    }
    settings = Settings.from_env(env)

    assert str(settings.db_path) == "custom.db"
    assert settings.admin_api_key == "secret"
    assert settings.loan_days == 7
    assert settings.max_active_loans == 3
    assert settings.max_renewals == 1
    assert settings.fine_block_cents == 200
    assert settings.fines.grace_days == 1
    assert settings.fines.daily_cents == 10
    assert settings.fines.cap_cents == 500


def test_env_int_returns_default_when_empty() -> None:
    assert _env_int({"VAR": "   "}, "VAR", 42, minimum=1) == 42
    assert _env_int({}, "VAR", 42, minimum=1) == 42


def test_env_int_raises_value_error_on_invalid_format() -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        _env_int({"VAR": "abc"}, "VAR", 42, minimum=1)


def test_env_int_raises_value_error_on_below_minimum() -> None:
    with pytest.raises(ValueError, match="must be at least 2"):
        _env_int({"VAR": "1"}, "VAR", 42, minimum=2)


def test_settings_from_env_defaults_to_os_environ() -> None:
    with patch.dict(os.environ, {"LIBRARY_MAX_RENEWALS": "9"}):
        settings = Settings.from_env()
        assert settings.max_renewals == 9


def test_env_int_minimum_values_are_enforced() -> None:
    with pytest.raises(ValueError):
        _env_int({"VAR": "0"}, "VAR", 42, minimum=1)


def test_env_int_minimum_values_are_allowed() -> None:
    settings = Settings.from_env({"LIBRARY_LOAN_DAYS": "1", "LIBRARY_MAX_ACTIVE_LOANS": "1"})
    assert settings.loan_days == 1
    assert settings.max_active_loans == 1
