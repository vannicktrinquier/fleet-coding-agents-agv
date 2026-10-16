from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import FinePolicy
from app.fines import compute_fine, days_late, format_cents
from tests.support import Library

POLICY = FinePolicy(grace_days=3, daily_cents=25, cap_cents=1000)
DUE = date(2026, 3, 16)


@pytest.mark.parametrize(
    ("on", "expected"),
    [
        (date(2026, 3, 10), 0),
        (date(2026, 3, 16), 0),
        (date(2026, 3, 17), 0),
        (date(2026, 3, 26), 250),
        (date(2026, 6, 1), 1000),
    ],
    ids=["early", "on-due-date", "one-day-late", "ten-days-late", "capped"],
)
def test_compute_fine(on: date, expected: int) -> None:
    assert compute_fine(DUE, on, POLICY) == expected


def test_days_late_is_never_negative() -> None:
    assert days_late(DUE, date(2026, 3, 1)) == 0
    assert days_late(DUE, date(2026, 3, 20)) == 4


def test_format_cents() -> None:
    assert format_cents(0) == "$0.00"
    assert format_cents(5) == "$0.05"
    assert format_cents(1250) == "$12.50"


def test_member_fines_list_settled_and_accruing_fines(
    client: TestClient, clock: FixedClock, library: Library
) -> None:
    member = library.member()
    first = library.checkout(library.book()["id"], member["id"])
    second = library.checkout(library.book()["id"], member["id"])
    clock.advance(days=14 + 6)
    library.give_back(first["id"])
    clock.advance(days=4)

    response = client.get(f"/members/{member['id']}/fines")

    assert response.status_code == 200
    summary = response.json()
    assert summary["total_cents"] == 150 + 250
    assert [
        (item["loan_id"], item["days_late"], item["amount_cents"], item["accruing"])
        for item in summary["items"]
    ] == [(first["id"], 6, 150, False), (second["id"], 10, 250, True)]


def test_member_without_fines(client: TestClient, library: Library) -> None:
    member = library.member()

    response = client.get(f"/members/{member['id']}/fines")

    assert response.json() == {"member_id": member["id"], "total_cents": 0, "items": []}


def test_paying_fines(
    client: TestClient, admin: dict[str, str], clock: FixedClock, library: Library
) -> None:
    member = library.member()
    loan = library.checkout(library.book()["id"], member["id"])
    clock.advance(days=14 + 8)
    library.give_back(loan["id"])

    response = client.post(f"/members/{member['id']}/fines/pay", headers=admin)

    assert response.status_code == 200
    assert response.json() == {
        "member_id": member["id"],
        "paid_cents": 200,
        "loan_ids": [loan["id"]],
    }
    assert client.get(f"/members/{member['id']}/fines").json()["total_cents"] == 0


def test_paying_fines_needs_the_admin_key(client: TestClient, library: Library) -> None:
    member = library.member()

    assert client.post(f"/members/{member['id']}/fines/pay").status_code == 401


def test_unpaid_fines_block_new_loans(
    client: TestClient, clock: FixedClock, library: Library
) -> None:
    member = library.member()
    loan = library.checkout(library.book()["id"], member["id"])
    clock.advance(days=14 + 20)
    library.give_back(loan["id"])

    response = client.post(
        "/loans", json={"book_id": library.book()["id"], "member_id": member["id"]}
    )

    assert response.status_code == 409
    assert response.json() == {"detail": f"member {member['id']} owes $5.00 in fines"}
