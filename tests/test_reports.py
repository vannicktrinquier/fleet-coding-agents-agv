from fastapi.testclient import TestClient

from tests.support import Library


def test_summary_report(client: TestClient, admin: dict[str, str], library: Library) -> None:
    library.checkout(library.book(copies=2)["id"], library.member()["id"])

    response = client.get("/reports/summary", headers=admin)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"generated_at", "books", "members", "loans", "outstanding_fines_cents"}
    assert set(body["books"]) == {"titles", "copies", "available", "on_loan"}
    assert set(body["members"]) == {"total", "active"}
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
