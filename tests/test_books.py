import pytest
from fastapi.testclient import TestClient

from tests.support import Library


def test_create_book_returns_the_new_book(client: TestClient, admin: dict[str, str]) -> None:
    response = client.post(
        "/books",
        json={
            "isbn": "978-0-441-17271-9",
            "title": "Dune",
            "author": "Frank Herbert",
            "year": 1965,
            "copies": 2,
        },
        headers=admin,
    )

    assert response.status_code == 201
    book = response.json()
    assert book["isbn"] == "9780441172719"
    assert book["copies_total"] == 2
    assert book["copies_available"] == 2
    assert book["created_at"] == "2026-03-02T10:00:00Z"


def test_isbn10_may_end_in_x(client: TestClient, admin: dict[str, str]) -> None:
    response = client.post(
        "/books",
        json={"isbn": "0-8044-2957-x", "title": "Kindred", "author": "Octavia E. Butler"},
        headers=admin,
    )

    assert response.status_code == 201
    assert response.json()["isbn"] == "080442957X"


@pytest.mark.parametrize("isbn", ["12345", "97804411727190", "978044117271A", "X780441172719"])
def test_malformed_isbn_is_rejected(client: TestClient, admin: dict[str, str], isbn: str) -> None:
    response = client.post(
        "/books", json={"isbn": isbn, "title": "Dune", "author": "Frank Herbert"}, headers=admin
    )

    assert response.status_code == 422


def test_creating_a_book_needs_the_admin_key(client: TestClient) -> None:
    response = client.post(
        "/books", json={"isbn": "9780441172719", "title": "Dune", "author": "Frank Herbert"}
    )

    assert response.status_code == 401


def test_duplicate_isbn_is_rejected(
    client: TestClient, admin: dict[str, str], library: Library
) -> None:
    library.book(isbn="9780441172719")

    response = client.post(
        "/books",
        json={"isbn": "978-0441-172719", "title": "Dune (reprint)", "author": "Frank Herbert"},
        headers=admin,
    )

    assert response.status_code == 409


def test_get_book(client: TestClient, library: Library) -> None:
    book = library.book(title="Kindred", author="Octavia E. Butler")

    response = client.get(f"/books/{book['id']}")

    assert response.status_code == 200
    assert response.json() == book


def test_missing_book_is_404(client: TestClient) -> None:
    response = client.get("/books/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "book 999 not found"}


def test_list_books(client: TestClient, library: Library) -> None:
    dune = library.book(title="Dune")
    emma = library.book(title="Emma", author="Jane Austen")

    response = client.get("/books")

    assert response.status_code == 200
    page = response.json()
    assert [book["id"] for book in page["items"]] == [dune["id"], emma["id"]]
    assert page["total"] == 2
    assert page["page"] == 1
    assert page["size"] == 20
    assert page["has_next"] is False


def test_list_books_paging_does_not_duplicate_items(client: TestClient, library: Library) -> None:
    books = [library.book(title=f"Book {i}") for i in range(1, 6)]

    p1 = client.get("/books", params={"page": 1, "size": 2}).json()
    assert len(p1["items"]) == 2
    assert [b["id"] for b in p1["items"]] == [books[0]["id"], books[1]["id"]]
    assert p1["has_next"] is True
    assert p1["total"] == 5

    p2 = client.get("/books", params={"page": 2, "size": 2}).json()
    assert len(p2["items"]) == 2
    assert [b["id"] for b in p2["items"]] == [books[2]["id"], books[3]["id"]]
    assert p2["has_next"] is True
    assert p2["total"] == 5

    p3 = client.get("/books", params={"page": 3, "size": 2}).json()
    assert len(p3["items"]) == 1
    assert [b["id"] for b in p3["items"]] == [books[4]["id"]]
    assert p3["has_next"] is False
    assert p3["total"] == 5


@pytest.mark.parametrize("params", [{"page": 0}, {"size": 0}, {"size": 101}])
def test_list_books_rejects_bad_paging(client: TestClient, params: dict[str, int]) -> None:
    assert client.get("/books", params=params).status_code == 422


def test_search_matches_title_or_author(client: TestClient, library: Library) -> None:
    dune = library.book(title="Dune", author="Frank Herbert")
    library.book(title="Persuasion", author="Jane Austen")
    library.book(title="Emma", author="Jane Austen")

    by_title = client.get("/books/search", params={"q": "Dune"}).json()
    by_author = client.get("/books/search", params={"q": "Austen"}).json()

    assert [book["id"] for book in by_title] == [dune["id"]]
    assert [book["title"] for book in by_author] == ["Emma", "Persuasion"]


def test_search_is_case_insensitive(client: TestClient, library: Library) -> None:
    dune = library.book(title="Dune", author="Frank Herbert")

    by_title_lower = client.get("/books/search", params={"q": "dune"}).json()
    by_title_mixed = client.get("/books/search", params={"q": "DuNe"}).json()
    by_author_lower = client.get("/books/search", params={"q": "herbert"}).json()
    by_author_upper = client.get("/books/search", params={"q": "HERBERT"}).json()

    assert [book["id"] for book in by_title_lower] == [dune["id"]]
    assert [book["id"] for book in by_title_mixed] == [dune["id"]]
    assert [book["id"] for book in by_author_lower] == [dune["id"]]
    assert [book["id"] for book in by_author_upper] == [dune["id"]]


def test_search_treats_wildcards_literally(client: TestClient, library: Library) -> None:
    library.book(title="100% Cotton", author="Ann Weaver")
    library.book(title="1000 Nights", author="Ben Teller")

    results = client.get("/books/search", params={"q": "100%"}).json()

    assert [book["title"] for book in results] == ["100% Cotton"]

    results_lower = client.get("/books/search", params={"q": "100% cotton"}).json()
    assert [book["title"] for book in results_lower] == ["100% Cotton"]


def test_search_needs_a_query(client: TestClient) -> None:
    assert client.get("/books/search").status_code == 422
    assert client.get("/books/search", params={"q": ""}).status_code == 422


def test_update_book(client: TestClient, admin: dict[str, str], library: Library) -> None:
    book = library.book(title="Dun", year=1964)

    response = client.patch(
        f"/books/{book['id']}", json={"title": "Dune", "year": 1965}, headers=admin
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Dune"
    assert response.json()["year"] == 1965


def test_update_copies_adjusts_copies_available(
    client: TestClient, admin: dict[str, str], library: Library
) -> None:
    book = library.book(copies=1)
    response = client.patch(f"/books/{book['id']}", json={"copies": 2}, headers=admin)
    assert response.status_code == 200
    updated = response.json()
    assert updated["copies_total"] == 2
    assert updated["copies_available"] == 2

    # Lowering copies when none on loan
    response = client.patch(f"/books/{book['id']}", json={"copies": 1}, headers=admin)
    assert response.status_code == 200
    updated = response.json()
    assert updated["copies_total"] == 1
    assert updated["copies_available"] == 1


def test_update_copies_with_active_loans(
    client: TestClient, admin: dict[str, str], library: Library
) -> None:
    book = library.book(copies=3)
    m1 = library.member()
    m2 = library.member()
    library.checkout(book["id"], m1["id"])
    library.checkout(book["id"], m2["id"])

    # 3 total, 2 on loan, 1 available
    # Increase to 5 total -> 3 available (5 - 2)
    response = client.patch(f"/books/{book['id']}", json={"copies": 5}, headers=admin)
    assert response.status_code == 200
    updated = response.json()
    assert updated["copies_total"] == 5
    assert updated["copies_available"] == 3

    # Decrease to 2 total -> 0 available (2 - 2)
    response = client.patch(f"/books/{book['id']}", json={"copies": 2}, headers=admin)
    assert response.status_code == 200
    updated = response.json()
    assert updated["copies_total"] == 2
    assert updated["copies_available"] == 0


def test_update_rejects_null_title(
    client: TestClient, admin: dict[str, str], library: Library
) -> None:
    book = library.book()

    response = client.patch(f"/books/{book['id']}", json={"title": None}, headers=admin)

    assert response.status_code == 422


def test_copies_cannot_drop_below_copies_on_loan(
    client: TestClient, admin: dict[str, str], library: Library
) -> None:
    book = library.book(copies=2)
    library.checkout(book["id"], library.member()["id"])
    library.checkout(book["id"], library.member()["id"])

    response = client.patch(f"/books/{book['id']}", json={"copies": 1}, headers=admin)

    assert response.status_code == 409


def test_delete_book_hides_it(client: TestClient, admin: dict[str, str], library: Library) -> None:
    book = library.book()

    response = client.delete(f"/books/{book['id']}", headers=admin)

    assert response.status_code == 204
    assert client.get(f"/books/{book['id']}").status_code == 404
    assert client.get("/books").json()["total"] == 0


def test_deleted_isbn_can_be_catalogued_again(
    client: TestClient, admin: dict[str, str], library: Library
) -> None:
    old = library.book(isbn="9780441172719")
    client.delete(f"/books/{old['id']}", headers=admin)

    new = library.book(isbn="9780441172719")

    assert new["id"] != old["id"]


def test_book_on_loan_cannot_be_deleted(
    client: TestClient, admin: dict[str, str], library: Library
) -> None:
    book = library.book()
    library.checkout(book["id"], library.member()["id"])

    response = client.delete(f"/books/{book['id']}", headers=admin)

    assert response.status_code == 409
    assert client.get(f"/books/{book['id']}").status_code == 200


def test_list_books_exact_page_multiple(client: TestClient, library: Library) -> None:
    books = [library.book(title=f"Book {i}") for i in range(1, 5)]

    p1 = client.get("/books", params={"page": 1, "size": 2}).json()
    assert len(p1["items"]) == 2
    assert [b["id"] for b in p1["items"]] == [books[0]["id"], books[1]["id"]]
    assert p1["has_next"] is True
    assert p1["total"] == 4

    p2 = client.get("/books", params={"page": 2, "size": 2}).json()
    assert len(p2["items"]) == 2
    assert [b["id"] for b in p2["items"]] == [books[2]["id"], books[3]["id"]]
    assert p2["has_next"] is False
    assert p2["total"] == 4


def test_sort_title_orders_by_title_then_id(client: TestClient, library: Library) -> None:
    b1 = library.book(title="Zeta", isbn="9780000000001")
    b2 = library.book(title="Alpha", isbn="9780000000002")
    b3 = library.book(title="Alpha", isbn="9780000000003")
    b4 = library.book(title="Beta", isbn="9780000000004")

    resp = client.get("/books", params={"sort": "title"})
    assert resp.status_code == 200
    page = resp.json()
    assert [b["id"] for b in page["items"]] == [b2["id"], b3["id"], b4["id"], b1["id"]]


def test_sort_author_orders_by_author_then_title_then_id(
    client: TestClient, library: Library
) -> None:
    b1 = library.book(title="Zeta", author="Bob", isbn="9780000000001")
    b2 = library.book(title="Alpha", author="Bob", isbn="9780000000002")
    b3 = library.book(title="Gamma", author="Alice", isbn="9780000000003")
    b4 = library.book(title="Beta", author="Alice", isbn="9780000000004")

    resp = client.get("/books", params={"sort": "author"})
    assert resp.status_code == 200
    page = resp.json()
    assert [b["id"] for b in page["items"]] == [b4["id"], b3["id"], b2["id"], b1["id"]]


def test_sort_year_orders_by_year_nulls_last_then_title_then_id(
    client: TestClient, library: Library
) -> None:
    b1 = library.book(title="Book 2000", year=2000, isbn="9780000000001")
    b2 = library.book(title="Book None Z", year=None, isbn="9780000000002")
    b3 = library.book(title="Book 1990", year=1990, isbn="9780000000003")
    b4 = library.book(title="Book None A", year=None, isbn="9780000000004")
    b5 = library.book(title="Another 2000", year=2000, isbn="9780000000005")

    resp = client.get("/books", params={"sort": "year"})
    assert resp.status_code == 200
    page = resp.json()
    # 1990 first (b3), then 2000 by title ("Another 2000" (b5) before "Book 2000" (b1)),
    # then nulls last by title ("Book None A" (b4) before "Book None Z" (b2))
    assert [b["id"] for b in page["items"]] == [b3["id"], b5["id"], b1["id"], b4["id"], b2["id"]]


def test_without_sort_order_stays_oldest_entries_first(
    client: TestClient, library: Library
) -> None:
    b1 = library.book(title="Zeta", author="Zoe", year=2020, isbn="9780000000001")
    b2 = library.book(title="Alpha", author="Adam", year=1990, isbn="9780000000002")
    b3 = library.book(title="Beta", author="Beth", year=2000, isbn="9780000000003")

    resp = client.get("/books")
    assert resp.status_code == 200
    page = resp.json()
    assert [b["id"] for b in page["items"]] == [b1["id"], b2["id"], b3["id"]]


def test_any_other_sort_value_is_422(client: TestClient) -> None:
    assert client.get("/books", params={"sort": "invalid"}).status_code == 422
    assert client.get("/books", params={"sort": "isbn"}).status_code == 422
    assert client.get("/books", params={"sort": ""}).status_code == 422


@pytest.mark.parametrize("sort_val", ["title", "author", "year"])
def test_paging_works_the_same_with_every_sort_order(
    client: TestClient, library: Library, sort_val: str
) -> None:
    # 5 books with same sort keys to verify ties are broken by id so pages are stable
    books = [
        library.book(title="Same Title", author="Same Author", year=2000, isbn=f"978000000000{i}")
        for i in range(1, 6)
    ]

    p1 = client.get("/books", params={"sort": sort_val, "page": 1, "size": 2}).json()
    assert len(p1["items"]) == 2
    assert [b["id"] for b in p1["items"]] == [books[0]["id"], books[1]["id"]]
    assert p1["has_next"] is True
    assert p1["total"] == 5
    assert p1["page"] == 1
    assert p1["size"] == 2

    p2 = client.get("/books", params={"sort": sort_val, "page": 2, "size": 2}).json()
    assert len(p2["items"]) == 2
    assert [b["id"] for b in p2["items"]] == [books[2]["id"], books[3]["id"]]
    assert p2["has_next"] is True
    assert p2["total"] == 5

    p3 = client.get("/books", params={"sort": sort_val, "page": 3, "size": 2}).json()
    assert len(p3["items"]) == 1
    assert [b["id"] for b in p3["items"]] == [books[4]["id"]]
    assert p3["has_next"] is False
    assert p3["total"] == 5
