from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.clock import FixedClock
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


def test_registered_email_cannot_be_reused_case_insensitively(
    client: TestClient, library: Library
) -> None:
    library.member(email="jane.doe@example.org")

    response = client.post("/members", json={"name": "Jane Doe", "email": "Jane.Doe@Example.org"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Jane.Doe@Example.org is already registered"}


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


def test_email_change_to_a_taken_address_case_insensitively_is_rejected(
    client: TestClient, library: Library
) -> None:
    library.member(email="ada@example.org")
    grace = library.member(email="grace@example.org")

    response = client.patch(f"/members/{grace['id']}", json={"email": "Ada@Example.ORG"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Ada@Example.ORG is already registered"}


def test_member_can_resubmit_their_own_email(client: TestClient, library: Library) -> None:
    member = library.member(email="ada@example.org")

    response = client.patch(f"/members/{member['id']}", json={"email": "ada@example.org"})

    assert response.status_code == 200


def test_member_can_resubmit_their_own_email_with_different_casing(
    client: TestClient, library: Library
) -> None:
    member = library.member(email="ada@example.org")

    response = client.patch(f"/members/{member['id']}", json={"email": "Ada@Example.ORG"})

    assert response.status_code == 200
    assert response.json()["email"] == "Ada@Example.ORG"


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


def test_member_loans_returns_json_list_newest_first(
    client: TestClient, library: Library, clock: FixedClock
) -> None:
    member = library.member()

    response = client.get(f"/members/{member['id']}/loans")
    assert response.status_code == 200
    assert response.json() == []

    book1 = library.book()
    book2 = library.book()
    book3 = library.book()

    loan1 = library.checkout(book1["id"], member["id"])
    clock.advance(hours=1)
    loan2 = library.checkout(book2["id"], member["id"])
    clock.advance(hours=1)
    loan3 = library.checkout(book3["id"], member["id"])

    response = client.get(f"/members/{member['id']}/loans")
    assert response.status_code == 200
    loans = response.json()
    assert len(loans) == 3

    assert loans[0]["id"] == loan3["id"]
    assert loans[1]["id"] == loan2["id"]
    assert loans[2]["id"] == loan1["id"]

    for loan in loans:
        single_loan = client.get(f"/loans/{loan['id']}").json()
        assert loan == single_loan


def test_member_loans_tie_break_newest_first_at_same_timestamp(
    client: TestClient, library: Library
) -> None:
    member = library.member()
    book1 = library.book()
    book2 = library.book()

    loan1 = library.checkout(book1["id"], member["id"])
    loan2 = library.checkout(book2["id"], member["id"])

    response = client.get(f"/members/{member['id']}/loans")
    assert response.status_code == 200
    loans = response.json()
    assert [loan["id"] for loan in loans] == [loan2["id"], loan1["id"]]


def test_member_loans_filter_by_status(client: TestClient, library: Library) -> None:
    member = library.member()
    book1 = library.book()
    book2 = library.book()
    book3 = library.book()

    loan1 = library.checkout(book1["id"], member["id"])
    loan2 = library.checkout(book2["id"], member["id"])
    loan3 = library.checkout(book3["id"], member["id"])

    library.give_back(loan2["id"])

    # ?status=open returns only unreturned loans
    response_open = client.get(f"/members/{member['id']}/loans?status=open")
    assert response_open.status_code == 200
    open_loans = response_open.json()
    assert [item["id"] for item in open_loans] == [loan3["id"], loan1["id"]]
    assert all(item["returned_at"] is None for item in open_loans)

    # ?status=returned returns only returned loans
    response_returned = client.get(f"/members/{member['id']}/loans?status=returned")
    assert response_returned.status_code == 200
    returned_loans = response_returned.json()
    assert [item["id"] for item in returned_loans] == [loan2["id"]]
    assert all(item["returned_at"] is not None for item in returned_loans)

    # No parameter returns all loans
    response_all = client.get(f"/members/{member['id']}/loans")
    assert response_all.status_code == 200
    assert [item["id"] for item in response_all.json()] == [loan3["id"], loan2["id"], loan1["id"]]


@pytest.mark.parametrize("status_val", ["closed", "all", "active", ""])
def test_member_loans_invalid_status_is_422(
    client: TestClient, library: Library, status_val: str
) -> None:
    member = library.member()
    response = client.get(f"/members/{member['id']}/loans", params={"status": status_val})
    assert response.status_code == 422


def test_member_loans_unknown_member_is_404(client: TestClient) -> None:
    assert client.get("/members/999/loans").status_code == 404
    assert client.get("/members/999/loans?status=open").status_code == 404
    assert client.get("/members/999/loans?status=returned").status_code == 404


def test_member_loans_no_admin_key_needed(client: TestClient, library: Library) -> None:
    member = library.member()
    response = client.get(f"/members/{member['id']}/loans")
    assert response.status_code == 200


def test_readme_lists_member_loans_endpoint() -> None:
    readme_path = Path(__file__).parents[1] / "README.md"
    if not readme_path.exists():
        readme_path = Path(__file__).parents[2] / "README.md"
    if readme_path.exists():
        assert "/members/{id}/loans" in readme_path.read_text()
