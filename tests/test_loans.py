import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db
from app.clock import FixedClock
from app.config import Settings
from app.main import create_app
from tests.support import Library


def test_checkout_sets_the_due_date_and_takes_a_copy(client: TestClient, library: Library) -> None:
    book = library.book(copies=2)
    member = library.member()

    loan = library.checkout(book["id"], member["id"])

    assert loan["book_id"] == book["id"]
    assert loan["member_id"] == member["id"]
    assert loan["loaned_at"] == "2026-03-02T10:00:00Z"
    assert loan["due_on"] == "2026-03-16"
    assert loan["returned_at"] is None
    assert loan["renewals"] == 0
    assert client.get(f"/books/{book['id']}").json()["copies_available"] == 1


def test_checkout_fails_when_no_copy_is_left(client: TestClient, library: Library) -> None:
    book = library.book(copies=1)
    library.checkout(book["id"], library.member()["id"])

    response = client.post(
        "/loans", json={"book_id": book["id"], "member_id": library.member()["id"]}
    )

    assert response.status_code == 409
    assert response.json() == {"detail": f"no copies of book {book['id']} are available"}


def test_checkout_of_unknown_book_or_member_is_404(client: TestClient, library: Library) -> None:
    book = library.book()
    member = library.member()

    unknown_book = client.post("/loans", json={"book_id": 999, "member_id": member["id"]})
    unknown_member = client.post("/loans", json={"book_id": book["id"], "member_id": 999})

    assert unknown_book.status_code == 404
    assert unknown_member.status_code == 404


def test_inactive_member_cannot_borrow(
    client: TestClient, admin: dict[str, str], library: Library
) -> None:
    book = library.book()
    member = library.member()
    client.post(f"/members/{member['id']}/deactivate", headers=admin)

    response = client.post("/loans", json={"book_id": book["id"], "member_id": member["id"]})

    assert response.status_code == 409


def test_member_cannot_hold_two_copies_of_a_book(client: TestClient, library: Library) -> None:
    book = library.book(copies=2)
    member = library.member()
    library.checkout(book["id"], member["id"])

    response = client.post("/loans", json={"book_id": book["id"], "member_id": member["id"]})

    assert response.status_code == 409


def test_active_loan_limit(client: TestClient, library: Library, settings: Settings) -> None:
    member = library.member()
    for _ in range(settings.max_active_loans):
        library.checkout(library.book()["id"], member["id"])

    response = client.post(
        "/loans", json={"book_id": library.book()["id"], "member_id": member["id"]}
    )

    assert response.status_code == 409


def test_return_on_time_puts_the_copy_back(
    client: TestClient, clock: FixedClock, library: Library
) -> None:
    book = library.book()
    loan = library.checkout(book["id"], library.member()["id"])
    clock.advance(days=10)

    returned = library.give_back(loan["id"])

    assert returned["returned_at"] == "2026-03-12T10:00:00Z"
    assert returned["fine_cents"] == 0
    assert client.get(f"/books/{book['id']}").json()["copies_available"] == 1


def test_return_on_last_day_of_grace_period_is_not_fined(
    clock: FixedClock, library: Library
) -> None:
    loan = library.checkout(library.book()["id"], library.member()["id"])
    clock.advance(days=14 + 3)

    returned = library.give_back(loan["id"])

    assert returned["fine_cents"] == 0


def test_late_return_is_fined(clock: FixedClock, library: Library) -> None:
    loan = library.checkout(library.book()["id"], library.member()["id"])
    clock.advance(days=14 + 10)

    returned = library.give_back(loan["id"])

    assert returned["fine_cents"] == 250


def test_returned_loan_cannot_be_returned_again(
    client: TestClient, clock: FixedClock, library: Library
) -> None:
    book = library.book(copies=1)
    member = library.member()
    loan = library.checkout(book["id"], member["id"])

    first_return = library.give_back(loan["id"])
    assert first_return["returned_at"] == "2026-03-02T10:00:00Z"

    clock.advance(days=30)
    second_return = client.post(f"/loans/{loan['id']}/return")

    assert second_return.status_code == 409
    assert second_return.json() == {"detail": f"loan {loan['id']} has already been returned"}
    assert client.get(f"/books/{book['id']}").json()["copies_available"] == 1

    persisted = client.get(f"/loans/{loan['id']}").json()
    assert persisted["returned_at"] == first_return["returned_at"]
    assert persisted["fine_cents"] == first_return["fine_cents"]


def test_renewal_moves_the_due_date(
    client: TestClient, clock: FixedClock, library: Library
) -> None:
    loan = library.checkout(library.book()["id"], library.member()["id"])
    clock.advance(days=10)

    response = client.post(f"/loans/{loan['id']}/renew")

    assert response.status_code == 200
    assert response.json()["due_on"] == "2026-03-26"
    assert response.json()["renewals"] == 1


def test_returned_loan_cannot_be_renewed(client: TestClient, library: Library) -> None:
    loan = library.checkout(library.book()["id"], library.member()["id"])
    library.give_back(loan["id"])

    response = client.post(f"/loans/{loan['id']}/renew")

    assert response.status_code == 409


def test_first_and_second_renewals_succeed(
    client: TestClient, clock: FixedClock, library: Library
) -> None:
    loan = library.checkout(library.book()["id"], library.member()["id"])

    clock.advance(days=5)
    r1 = client.post(f"/loans/{loan['id']}/renew")
    assert r1.status_code == 200
    assert r1.json()["renewals"] == 1
    assert r1.json()["due_on"] == "2026-03-21"

    clock.advance(days=5)
    r2 = client.post(f"/loans/{loan['id']}/renew")
    assert r2.status_code == 200
    assert r2.json()["renewals"] == 2
    assert r2.json()["due_on"] == "2026-03-26"


def test_third_renewal_is_rejected_with_409_when_limit_reached(
    client: TestClient, clock: FixedClock, library: Library
) -> None:
    loan = library.checkout(library.book()["id"], library.member()["id"])

    clock.advance(days=1)
    client.post(f"/loans/{loan['id']}/renew")
    clock.advance(days=1)
    client.post(f"/loans/{loan['id']}/renew")

    clock.advance(days=1)
    r3 = client.post(f"/loans/{loan['id']}/renew")
    assert r3.status_code == 409
    assert "renewal limit" in r3.json()["detail"].lower()


def test_renewal_limit_is_configurable_with_library_max_renewals(
    tmp_path: Path, clock: FixedClock, admin: dict[str, str]
) -> None:
    custom_settings = Settings.from_env(
        {"LIBRARY_MAX_RENEWALS": "1", "LIBRARY_ADMIN_KEY": admin["X-API-Key"]}
    )
    assert custom_settings.max_renewals == 1

    app = create_app(db_path=tmp_path / "custom.db", clock=clock, settings=custom_settings)
    with TestClient(app) as custom_client:
        lib = Library(custom_client, admin)
        loan = lib.checkout(lib.book()["id"], lib.member()["id"])

        r1 = custom_client.post(f"/loans/{loan['id']}/renew")
        assert r1.status_code == 200
        assert r1.json()["renewals"] == 1

        r2 = custom_client.post(f"/loans/{loan['id']}/renew")
        assert r2.status_code == 409
        assert "renewal limit" in r2.json()["detail"].lower()


def test_readme_documents_renewal_limit_and_configuration() -> None:
    readme_path = Path(__file__).parents[1] / "README.md"
    if not readme_path.exists():
        readme_path = Path(__file__).parents[2] / "README.md"
    if readme_path.exists():
        content = readme_path.read_text()
        assert "LIBRARY_MAX_RENEWALS" in content
        assert "renewed at most twice" in content or "renewal limit" in content


def test_renewal_on_due_date_succeeds(
    client: TestClient, clock: FixedClock, library: Library
) -> None:
    loan = library.checkout(library.book()["id"], library.member()["id"])
    clock.advance(days=14)

    response = client.post(f"/loans/{loan['id']}/renew")

    assert response.status_code == 200
    assert response.json()["due_on"] == "2026-03-30"
    assert response.json()["renewals"] == 1


def test_overdue_loan_cannot_be_renewed(
    client: TestClient, clock: FixedClock, library: Library
) -> None:
    loan = library.checkout(library.book()["id"], library.member()["id"])
    clock.advance(days=24)

    response = client.post(f"/loans/{loan['id']}/renew")

    assert response.status_code == 409
    assert response.json() == {"detail": f"loan {loan['id']} is overdue"}

    persisted = client.get(f"/loans/{loan['id']}").json()
    assert persisted["due_on"] == loan["due_on"]
    assert persisted["renewals"] == 0

    fines = client.get(f"/members/{loan['member_id']}/fines").json()
    assert fines["total_cents"] == 250


def test_one_day_overdue_loan_cannot_be_renewed(
    client: TestClient, clock: FixedClock, library: Library
) -> None:
    loan = library.checkout(library.book()["id"], library.member()["id"])
    clock.advance(days=15)

    response = client.post(f"/loans/{loan['id']}/renew")

    assert response.status_code == 409
    assert response.json() == {"detail": f"loan {loan['id']} is overdue"}


def test_get_loan(client: TestClient, library: Library) -> None:
    loan = library.checkout(library.book()["id"], library.member()["id"])

    response = client.get(f"/loans/{loan['id']}")

    assert response.status_code == 200
    assert response.json() == loan


def test_missing_loan_is_404(client: TestClient) -> None:
    assert client.get("/loans/7").status_code == 404
    assert client.post("/loans/7/return").status_code == 404
    assert client.post("/loans/7/renew").status_code == 404


def test_overdue_lists_open_loans_past_their_due_date(
    client: TestClient, admin: dict[str, str], clock: FixedClock, library: Library
) -> None:
    member = library.member()
    late = library.checkout(library.book()["id"], member["id"])
    clock.advance(days=7)
    library.checkout(library.book()["id"], member["id"])
    clock.advance(days=8)

    response = client.get("/loans/overdue", headers=admin)

    assert response.status_code == 200
    assert [loan["id"] for loan in response.json()] == [late["id"]]


def test_returned_loans_are_not_overdue(
    client: TestClient, admin: dict[str, str], clock: FixedClock, library: Library
) -> None:
    loan = library.checkout(library.book()["id"], library.member()["id"])
    clock.advance(days=20)
    library.give_back(loan["id"])

    assert client.get("/loans/overdue", headers=admin).json() == []


def test_overdue_query_plan_uses_index(
    app: FastAPI, client: TestClient, db_path: Path, admin: dict[str, str]
) -> None:
    from app.deps import get_conn

    queries = []

    def custom_get_conn():
        conn = db.connect(db_path)
        conn.set_trace_callback(queries.append)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = custom_get_conn

    try:
        response = client.get("/loans/overdue", headers=admin)
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()

    # Find the overdue query
    target_query = None
    for q in queries:
        if "FROM loans" in q and "returned_at IS NULL" in q:
            target_query = q
            break

    assert target_query is not None, "Could not find the overdue query"

    conn = db.connect(db_path)
    try:
        plan = conn.execute("EXPLAIN QUERY PLAN " + target_query).fetchall()
        details = [row["detail"] for row in plan]
        assert not any("SCAN loans" in d for d in details)
        assert not any("USE TEMP B-TREE" in d for d in details)
        assert any("SEARCH loans USING INDEX idx_loans_overdue" in d for d in details)
    finally:
        conn.close()


def test_renewal_limit_of_zero_rejects_first_renewal(
    tmp_path: Path, clock: FixedClock, admin: dict[str, str]
) -> None:
    custom_settings = Settings.from_env(
        {"LIBRARY_MAX_RENEWALS": "0", "LIBRARY_ADMIN_KEY": admin["X-API-Key"]}
    )
    assert custom_settings.max_renewals == 0

    app = create_app(db_path=tmp_path / "zero.db", clock=clock, settings=custom_settings)
    with TestClient(app) as custom_client:
        lib = Library(custom_client, admin)
        loan = lib.checkout(lib.book()["id"], lib.member()["id"])

        response = custom_client.post(f"/loans/{loan['id']}/renew")
        assert response.status_code == 409
        assert "renewal limit" in response.json()["detail"].lower()


def test_renewal_rejected_when_renewals_exceed_limit(
    client: TestClient, db_path: Path, library: Library, settings: Settings
) -> None:
    loan = library.checkout(library.book()["id"], library.member()["id"])

    # Simulate a limit lowering: the loan already has more renewals than the current limit.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE loans SET renewals = ? WHERE id = ?",
            (settings.max_renewals + 1, loan["id"]),
        )

    response = client.post(f"/loans/{loan['id']}/renew")

    assert response.status_code == 409
    assert "renewal limit" in response.json()["detail"].lower()
