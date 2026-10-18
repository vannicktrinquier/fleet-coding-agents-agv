from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.clock import FixedClock
from app.reports import popular_books
from tests.support import Library


def test_summary_report(client: TestClient, admin: dict[str, str], library: Library) -> None:
    library.checkout(library.book(copies=2)["id"], library.member()["id"])

    response = client.get("/reports/summary", headers=admin)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"generated_at", "books", "members", "loans", "outstanding_fines_cents"}
    assert set(body["books"]) == {"titles", "copies", "available", "on_loan"}
    assert set(body["members"]) == {"total", "active", "with_overdue"}
    assert body["members"]["with_overdue"] == 0
    assert set(body["loans"]) == {"open", "overdue", "returned_last_30_days"}


def test_summary_report_excludes_deleted_books(
    client: TestClient, admin: dict[str, str], library: Library
) -> None:
    library.book(copies=1)
    b2 = library.book(copies=1)
    library.book(copies=1)

    del_res = client.delete(f"/books/{b2['id']}", headers=admin)
    assert del_res.status_code == 204

    response = client.get("/reports/summary", headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert body["books"]["titles"] == 2
    assert body["books"]["copies"] == 2
    assert body["books"]["available"] == 2
    assert body["books"]["on_loan"] == 0


def test_summary_report_members_with_overdue_field(
    client: TestClient, admin: dict[str, str], library: Library, clock: FixedClock
) -> None:
    m1 = library.member()
    b1 = library.book()
    library.checkout(b1["id"], m1["id"])

    clock.advance(days=15)

    m2 = library.member()
    b2 = library.book()
    library.checkout(b2["id"], m2["id"])

    library.member()

    response = client.get("/reports/summary", headers=admin)
    assert response.status_code == 200
    members = response.json()["members"]
    assert members["total"] == 3
    assert members["active"] == 3
    assert members["with_overdue"] == 1


def test_summary_report_member_with_several_overdue_loans_counts_once(
    client: TestClient, admin: dict[str, str], library: Library, clock: FixedClock
) -> None:
    member = library.member()
    b1 = library.book()
    b2 = library.book()
    library.checkout(b1["id"], member["id"])
    library.checkout(b2["id"], member["id"])

    clock.advance(days=15)

    response = client.get("/reports/summary", headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert body["members"]["with_overdue"] == 1
    assert body["loans"]["overdue"] == 2


def test_summary_report_loans_due_today_are_not_overdue_and_returned_loans_never_count(
    client: TestClient, admin: dict[str, str], library: Library, clock: FixedClock
) -> None:
    m_returned = library.member()
    b_returned = library.book()
    l_returned = library.checkout(b_returned["id"], m_returned["id"])

    m_overdue = library.member()
    b_overdue = library.book()
    library.checkout(b_overdue["id"], m_overdue["id"])

    # Advance 1 day, then check out for m_due_today (due on day 1 + 14 = 15)
    clock.advance(days=1)
    m_due_today = library.member()
    b_due_today = library.book()
    library.checkout(b_due_today["id"], m_due_today["id"])

    # Advance 14 days to day 15 (m_due_today is due today, others are past due date)
    clock.advance(days=14)
    library.give_back(l_returned["id"])

    response = client.get("/reports/summary", headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert body["members"]["with_overdue"] == 1
    assert body["loans"]["overdue"] == 1
    assert body["loans"]["open"] == 2


def test_popular_report(client: TestClient, admin: dict[str, str], library: Library) -> None:
    book = library.book()
    library.checkout(book["id"], library.member()["id"])

    response = client.get("/reports/popular", headers=admin)

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_popular_report_validates_its_parameters(client: TestClient, admin: dict[str, str]) -> None:
    assert client.get("/reports/popular", params={"days": 0}, headers=admin).status_code == 422
    assert client.get("/reports/popular", params={"limit": 51}, headers=admin).status_code == 422
    assert client.get("/reports/popular", params={"min_loans": 0}, headers=admin).status_code == 422


def test_popular_books_includes_only_books_with_loans_ge_min_loans(
    client: TestClient, library: Library, db_path: Path, clock: FixedClock
) -> None:
    b1 = library.book(title="Book 1")
    b2 = library.book(title="Book 2")
    library.book(title="Book 3")
    m1 = library.member()
    m2 = library.member()

    l1 = library.checkout(b1["id"], m1["id"])
    library.give_back(l1["id"])
    library.checkout(b1["id"], m2["id"])

    library.checkout(b2["id"], m1["id"])

    conn = db.connect(db_path)
    try:
        # min_loans=1 includes books with 1 or 2 loans
        res_1 = popular_books(conn, clock.now(), days=30, limit=10, min_loans=1)
        assert [b.book_id for b in res_1] == [b1["id"], b2["id"]]
        assert res_1[0].loans == 2
        assert res_1[1].loans == 1

        # min_loans=2 includes only books with >= 2 loans
        res_2 = popular_books(conn, clock.now(), days=30, limit=10, min_loans=2)
        assert [b.book_id for b in res_2] == [b1["id"]]
        assert res_2[0].loans == 2

        # min_loans=3 excludes all books
        res_3 = popular_books(conn, clock.now(), days=30, limit=10, min_loans=3)
        assert res_3 == []

        # Default min_loans=1 preserves behavior
        res_default = popular_books(conn, clock.now(), days=30, limit=10)
        assert [b.book_id for b in res_default] == [b1["id"], b2["id"]]
    finally:
        conn.close()


def test_get_reports_popular_min_loans_2_returns_only_books_borrowed_at_least_twice(
    client: TestClient, admin: dict[str, str], library: Library
) -> None:
    b1 = library.book(title="Book 1")
    b2 = library.book(title="Book 2")
    m1 = library.member()
    m2 = library.member()

    l1 = library.checkout(b1["id"], m1["id"])
    library.give_back(l1["id"])
    library.checkout(b1["id"], m2["id"])

    library.checkout(b2["id"], m1["id"])

    # min_loans=2 returns only books borrowed at least twice
    response_2 = client.get("/reports/popular", params={"min_loans": 2}, headers=admin)
    assert response_2.status_code == 200
    items_2 = response_2.json()
    assert len(items_2) == 1
    assert items_2[0]["book_id"] == b1["id"]
    assert items_2[0]["loans"] == 2

    # default min_loans=1 preserves current behavior
    response_default = client.get("/reports/popular", headers=admin)
    assert response_default.status_code == 200
    items_default = response_default.json()
    assert [b["book_id"] for b in items_default] == [b1["id"], b2["id"]]

    # explicit min_loans=1 matches default
    response_1 = client.get("/reports/popular", params={"min_loans": 1}, headers=admin)
    assert response_1.status_code == 200
    assert response_1.json() == items_default


def test_popular_report_min_loans_less_than_1_returns_422(
    client: TestClient, admin: dict[str, str]
) -> None:
    assert client.get("/reports/popular", params={"min_loans": 0}, headers=admin).status_code == 422
    assert (
        client.get("/reports/popular", params={"min_loans": -1}, headers=admin).status_code == 422
    )


def test_reports_need_the_admin_key(client: TestClient) -> None:
    assert client.get("/reports/summary").status_code == 401
    assert client.get("/reports/popular").status_code == 401
