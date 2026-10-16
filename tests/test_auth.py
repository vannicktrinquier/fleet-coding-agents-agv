from fastapi.testclient import TestClient


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
