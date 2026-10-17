import logging
import warnings
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import Settings
from app.main import create_app


def test_admin_endpoint_rejects_a_missing_key(client: TestClient) -> None:
    response = client.get("/loans/overdue")

    assert response.status_code == 401
    assert response.json() == {"detail": "missing or invalid API key"}


def test_admin_endpoint_rejects_a_wrong_key(client: TestClient) -> None:
    response = client.get("/loans/overdue", headers={"X-API-Key": "not-the-key"})

    assert response.status_code == 401


def test_admin_endpoint_accepts_the_configured_key(
    client: TestClient, admin: dict[str, str]
) -> None:
    assert client.get("/loans/overdue", headers=admin).status_code == 200


def test_public_endpoints_need_no_key(client: TestClient) -> None:
    assert client.get("/books").status_code == 200
    assert client.get("/health").status_code == 200


def test_admin_endpoints_rejected_when_no_key_is_configured(
    tmp_path: Path, clock: FixedClock
) -> None:
    app = create_app(db_path=tmp_path / "test.db", clock=clock, settings=Settings())
    with TestClient(app) as unauth_client:
        # Without key header
        res1 = unauth_client.get("/reports/summary")
        assert res1.status_code == 401
        assert res1.json() == {"detail": "admin key is not configured"}

        # With empty key header
        res2 = unauth_client.get("/reports/summary", headers={"X-API-Key": ""})
        assert res2.status_code == 401
        assert res2.json() == {"detail": "admin key is not configured"}

        # With whitespace key header
        res3 = unauth_client.get("/reports/summary", headers={"X-API-Key": "   "})
        assert res3.status_code == 401
        assert res3.json() == {"detail": "admin key is not configured"}

        # With arbitrary key header
        res4 = unauth_client.get("/reports/summary", headers={"X-API-Key": "some-key"})
        assert res4.status_code == 401
        assert res4.json() == {"detail": "admin key is not configured"}

        # DELETE endpoint also rejected
        res5 = unauth_client.delete("/books/1")
        assert res5.status_code == 401
        assert res5.json() == {"detail": "admin key is not configured"}

        # Public endpoints still work
        assert unauth_client.get("/health").status_code == 200
        assert unauth_client.get("/books").status_code == 200


def test_admin_endpoints_rejected_when_key_is_whitespace(tmp_path: Path, clock: FixedClock) -> None:
    app = create_app(
        db_path=tmp_path / "test.db",
        clock=clock,
        settings=Settings(admin_api_key="   "),
    )
    with TestClient(app) as unauth_client:
        response = unauth_client.get("/loans/overdue")
        assert response.status_code == 401
        assert response.json() == {"detail": "admin key is not configured"}


def test_admin_endpoint_rejects_empty_or_whitespace_key(client: TestClient) -> None:
    res_empty = client.get("/loans/overdue", headers={"X-API-Key": ""})
    assert res_empty.status_code == 401
    assert res_empty.json() == {"detail": "missing or invalid API key"}

    res_ws = client.get("/loans/overdue", headers={"X-API-Key": "   "})
    assert res_ws.status_code == 401
    assert res_ws.json() == {"detail": "missing or invalid API key"}


def test_admin_endpoint_rejects_missing_header_when_configured_key_is_placeholder(
    tmp_path: Path, clock: FixedClock
) -> None:
    app = create_app(
        db_path=tmp_path / "test.db",
        clock=clock,
        settings=Settings(admin_api_key="XXXX"),
    )
    with TestClient(app) as unauth_client:
        response = unauth_client.get("/loans/overdue")
        assert response.status_code == 401
        assert response.json() == {"detail": "missing or invalid API key"}


def test_startup_warns_when_admin_key_not_configured(
    tmp_path: Path, clock: FixedClock, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING), pytest.warns(UserWarning, match="LIBRARY_ADMIN_KEY"):
        create_app(db_path=tmp_path / "test.db", clock=clock, settings=Settings())
    assert any("LIBRARY_ADMIN_KEY" in record.message for record in caplog.records)


def test_startup_does_not_warn_when_admin_key_configured(
    tmp_path: Path, clock: FixedClock, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING), warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        create_app(
            db_path=tmp_path / "test.db",
            clock=clock,
            settings=Settings(admin_api_key="secret-key"),
        )
    assert not any("LIBRARY_ADMIN_KEY" in record.message for record in caplog.records)
    assert not any("LIBRARY_ADMIN_KEY" in str(w.message) for w in recorded)
