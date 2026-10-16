import pytest
from fastapi.testclient import TestClient

from tests.support import Library


def test_register_member(client: TestClient) -> None:
    response = client.post("/members", json={"name": "Ada Lovelace", "email": "ada@example.org"})

    assert response.status_code == 201
    member = response.json()
    assert member["name"] == "Ada Lovelace"
    assert member["email"] == "ada@example.org"
    assert member["active"] is True
    assert member["created_at"] == "2026-03-02T10:00:00Z"


def test_registered_email_cannot_be_reused(client: TestClient, library: Library) -> None:
    library.member(email="ada@example.org")

    response = client.post("/members", json={"name": "Someone Else", "email": "ada@example.org"})

    assert response.status_code == 409
    assert response.json() == {"detail": "ada@example.org is already registered"}


@pytest.mark.parametrize(
    "email", ["not-an-email", "ada@localhost", "ada@@example.org", "ada lovelace@example.org"]
)
def test_malformed_email_is_rejected(client: TestClient, email: str) -> None:
    response = client.post("/members", json={"name": "Ada", "email": email})

    assert response.status_code == 422


def test_blank_name_is_rejected(client: TestClient) -> None:
    response = client.post("/members", json={"name": "   ", "email": "ada@example.org"})

    assert response.status_code == 422


def test_get_member(client: TestClient, library: Library) -> None:
    member = library.member(name="Grace Hopper")

    response = client.get(f"/members/{member['id']}")

    assert response.status_code == 200
    assert response.json() == member


def test_missing_member_is_404(client: TestClient) -> None:
    assert client.get("/members/42").status_code == 404


def test_update_member_name(client: TestClient, library: Library) -> None:
    member = library.member(name="Grace")

    response = client.patch(f"/members/{member['id']}", json={"name": "Grace Hopper"})

    assert response.status_code == 200
    assert response.json()["name"] == "Grace Hopper"
    assert response.json()["email"] == member["email"]


def test_email_change_to_a_taken_address_is_rejected(client: TestClient, library: Library) -> None:
    library.member(email="ada@example.org")
    grace = library.member(email="grace@example.org")

    response = client.patch(f"/members/{grace['id']}", json={"email": "ada@example.org"})

    assert response.status_code == 409


def test_member_can_resubmit_their_own_email(client: TestClient, library: Library) -> None:
    member = library.member(email="ada@example.org")

    response = client.patch(f"/members/{member['id']}", json={"email": "ada@example.org"})

    assert response.status_code == 200


def test_deactivate_member(client: TestClient, admin: dict[str, str], library: Library) -> None:
    member = library.member()

    response = client.post(f"/members/{member['id']}/deactivate", headers=admin)

    assert response.status_code == 200
    assert response.json()["active"] is False


def test_deactivation_needs_the_admin_key(client: TestClient, library: Library) -> None:
    member = library.member()

    response = client.post(f"/members/{member['id']}/deactivate")

    assert response.status_code == 401
    assert client.get(f"/members/{member['id']}").json()["active"] is True
