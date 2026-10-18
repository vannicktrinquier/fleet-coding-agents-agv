from fastapi.testclient import TestClient

from app.clock import FixedClock
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


def test_reports_need_the_admin_key(client: TestClient) -> None:
    assert client.get("/reports/summary").status_code == 401
    assert client.get("/reports/popular").status_code == 401
