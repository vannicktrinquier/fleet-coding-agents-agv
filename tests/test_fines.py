from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.config import FinePolicy
from app.fines import compute_fine, days_late, format_cents, is_at_fine_cap, parse_cents
from tests.support import Library

POLICY = FinePolicy(grace_days=3, daily_cents=25, cap_cents=1000)
DUE = date(2026, 3, 16)


@pytest.mark.parametrize(
    ("on", "expected"),
    [
        (date(2026, 3, 10), 0),
        (date(2026, 3, 16), 0),
        (date(2026, 3, 17), 0),
        (date(2026, 3, 19), 0),
        (date(2026, 3, 20), 100),
        (date(2026, 3, 26), 250),
        (date(2026, 6, 1), 1000),
    ],
    ids=[
        "early",
        "on-due-date",
        "one-day-late",
        "last-day-of-grace-period",
        "four-days-late",
        "ten-days-late",
        "capped",
    ],
)
def test_compute_fine(on: date, expected: int) -> None:
    assert compute_fine(DUE, on, POLICY) == expected


def test_is_at_fine_cap_on_time_returns() -> None:
    assert is_at_fine_cap(DUE, date(2026, 3, 10), POLICY) is False
    assert is_at_fine_cap(DUE, DUE, POLICY) is False
    assert is_at_fine_cap(DUE, date(2026, 3, 19), POLICY) is False


def test_is_at_fine_cap_below_cap() -> None:
    assert is_at_fine_cap(DUE, date(2026, 3, 20), POLICY) is False
    assert is_at_fine_cap(DUE, date(2026, 4, 24), POLICY) is False


def test_is_at_fine_cap_at_cap() -> None:
    assert is_at_fine_cap(DUE, date(2026, 4, 25), POLICY) is True
    assert is_at_fine_cap(DUE, date(2026, 6, 1), POLICY) is True


def test_is_at_fine_cap_with_zero_or_custom_cap() -> None:
    zero_cap = FinePolicy(grace_days=3, daily_cents=25, cap_cents=0)
    assert is_at_fine_cap(DUE, DUE, zero_cap) is False
    assert is_at_fine_cap(DUE, date(2026, 6, 1), zero_cap) is False

    one_cent_cap = FinePolicy(grace_days=3, daily_cents=1, cap_cents=1)
    assert is_at_fine_cap(DUE, date(2026, 3, 20), one_cent_cap) is True

    no_grace_small_cap = FinePolicy(grace_days=0, daily_cents=25, cap_cents=10)
    assert is_at_fine_cap(DUE, date(2026, 3, 20), no_grace_small_cap) is True


def test_days_late_is_never_negative() -> None:
    assert days_late(DUE, date(2026, 3, 1)) == 0
    assert days_late(DUE, date(2026, 3, 20)) == 4


def test_format_cents() -> None:
    assert format_cents(0) == "$0.00"
    assert format_cents(5) == "$0.05"
    assert format_cents(100) == "$1.00"
    assert format_cents(1234) == "$12.34"
    assert format_cents(1250) == "$12.50"
    assert format_cents(-1) == "-$0.01"
    assert format_cents(-5) == "-$0.05"
    assert format_cents(-100) == "-$1.00"
    assert format_cents(-150) == "-$1.50"


def test_parse_cents() -> None:
    assert parse_cents("$12.34") == 1234
    assert parse_cents("$0.05") == 5
    assert parse_cents("-$1.50") == -150
    assert parse_cents("$7") == 700
    assert parse_cents("-$7") == -700
    assert parse_cents("$0.00") == 0


def test_parse_cents_ignores_leading_and_trailing_whitespace() -> None:
    assert parse_cents("  $12.34  ") == 1234
    assert parse_cents("\t-$1.50\n") == -150
    assert parse_cents(" $7 ") == 700


@pytest.mark.parametrize(
    "bad_input",
    [
        "12.34",
        "$12.345",
        "$abc",
        "abc",
        "$12.ab",
        "",
        "   ",
        "$12.3",
        "$12.",
        "$.50",
        "$-1.50",
    ],
    ids=[
        "missing-dollar-sign",
        "more-than-two-decimal-places",
        "letters-after-dollar",
        "letters-only",
        "letters-in-cents",
        "empty-string",
        "whitespace-only",
        "one-decimal-place",
        "trailing-decimal-point",
        "missing-dollar-digits",
        "sign-after-dollar",
    ],
)
def test_parse_cents_rejects_invalid_input(bad_input: str) -> None:
    with pytest.raises(ValueError) as exc_info:
        parse_cents(bad_input)
    message = str(exc_info.value)
    assert bad_input in message
    assert message == f"invalid amount: {bad_input!r}"


@pytest.mark.parametrize(
    "cents",
    [-123456, -1000, -150, -100, -5, -1, 0, 1, 5, 99, 100, 700, 1234, 987654],
)
def test_parse_cents_round_trips_with_format_cents(cents: int) -> None:
    assert parse_cents(format_cents(cents)) == cents


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


def test_fine_cap_loan_returned_100_days_late_and_cap_applies_per_loan(
    client: TestClient, clock: FixedClock, library: Library
) -> None:
    """A loan returned 100 days late is fined exactly 1000 cents, and the cap applies per loan."""
    member = library.member()
    loan1 = library.checkout(library.book()["id"], member["id"])
    loan2 = library.checkout(library.book()["id"], member["id"])

    clock.advance(days=14 + 100)
    returned1 = library.give_back(loan1["id"])
    returned2 = library.give_back(loan2["id"])

    assert returned1["fine_cents"] == 1000
    assert returned2["fine_cents"] == 1000

    fines = client.get(f"/members/{member['id']}/fines").json()
    assert fines["total_cents"] == 2000


def test_borrowing_block_threshold_at_5_dollars(
    client: TestClient, clock: FixedClock, library: Library
) -> None:
    """A member who owes less than $5.00 can still borrow; exactly $5.00 cannot."""
    member = library.member()
    book1 = library.book()["id"]
    book2 = library.book()["id"]

    # 19 days late -> 19 * 25 = 475 cents (< 500 cents / $5.00)
    loan = library.checkout(book1, member["id"])
    clock.advance(days=14 + 19)
    library.give_back(loan["id"])

    fines_under = client.get(f"/members/{member['id']}/fines").json()
    assert fines_under["total_cents"] == 475

    # Can still borrow with 475 cents owed
    loan2 = library.checkout(book2, member["id"])
    assert loan2["id"] is not None

    # Test with a new member owing exactly 500 cents
    member_exact = library.member()
    book3 = library.book()["id"]
    book4 = library.book()["id"]

    # 20 days late -> 20 * 25 = 500 cents (exactly $5.00)
    loan_exact = library.checkout(book3, member_exact["id"])
    clock.advance(days=14 + 20)
    library.give_back(loan_exact["id"])

    fines_exact = client.get(f"/members/{member_exact['id']}/fines").json()
    assert fines_exact["total_cents"] == 500

    # Cannot borrow when owing exactly $5.00 (500 cents)
    response = client.post("/loans", json={"book_id": book4, "member_id": member_exact["id"]})
    assert response.status_code == 409
    assert response.json() == {"detail": f"member {member_exact['id']} owes $5.00 in fines"}

    # Test with a new member owing more than $5.00
    member_over = library.member()
    book5 = library.book()["id"]
    book6 = library.book()["id"]

    # 21 days late -> 21 * 25 = 525 cents (> $5.00)
    loan_over = library.checkout(book5, member_over["id"])
    clock.advance(days=14 + 21)
    library.give_back(loan_over["id"])

    fines_over = client.get(f"/members/{member_over['id']}/fines").json()
    assert fines_over["total_cents"] == 525

    # Cannot borrow when owing > $5.00 (525 cents)
    response_over = client.post("/loans", json={"book_id": book6, "member_id": member_over["id"]})
    assert response_over.status_code == 409
    assert response_over.json() == {"detail": f"member {member_over['id']} owes $5.25 in fines"}


def test_fines_accruing_on_books_still_out_count_toward_borrowing_block(
    client: TestClient, clock: FixedClock, library: Library
) -> None:
    """Fines still growing on books that are out count toward the block."""
    member = library.member()
    book1 = library.book()["id"]
    book2 = library.book()["id"]

    # Member borrows book1, does not return it.
    library.checkout(book1, member["id"])

    # Advance 14 days loan + 20 days late -> 20 * 25 = 500 cents accruing
    clock.advance(days=14 + 20)

    fines = client.get(f"/members/{member['id']}/fines").json()
    assert fines["total_cents"] == 500
    assert len(fines["items"]) == 1
    assert fines["items"][0]["accruing"] is True

    # Attempt to borrow book2 while fine is accruing and at threshold
    response = client.post("/loans", json={"book_id": book2, "member_id": member["id"]})
    assert response.status_code == 409
    assert response.json() == {"detail": f"member {member['id']} owes $5.00 in fines"}


def test_paying_fines_lifts_the_borrowing_block(
    client: TestClient, admin: dict[str, str], clock: FixedClock, library: Library
) -> None:
    """Paying the fines lifts the block."""
    member = library.member()
    book1 = library.book()["id"]
    book2 = library.book()["id"]
    book3 = library.book()["id"]

    loan1 = library.checkout(book1, member["id"])
    loan2 = library.checkout(book2, member["id"])
    clock.advance(days=14 + 10)
    library.give_back(loan1["id"])
    library.give_back(loan2["id"])

    # Blocked initially (owes 500 cents from 2 loans)
    blocked_resp = client.post("/loans", json={"book_id": book3, "member_id": member["id"]})
    assert blocked_resp.status_code == 409

    # Admin pays the fine
    pay_resp = client.post(f"/members/{member['id']}/fines/pay", headers=admin)
    assert pay_resp.status_code == 200
    assert pay_resp.json()["paid_cents"] == 500

    # Borrowing is now permitted
    borrow_resp = client.post("/loans", json={"book_id": book3, "member_id": member["id"]})
    assert borrow_resp.status_code == 201
    assert borrow_resp.json()["book_id"] == book3
    assert borrow_resp.json()["member_id"] == member["id"]
