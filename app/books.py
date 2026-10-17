"""Catalog: books, listing and search."""

import sqlite3
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status

from app.auth import require_admin
from app.db import timestamp
from app.deps import ClockDep, ConnDep
from app.errors import Conflict, NotFound
from app.models import Book, BookCreate, BookPage, BookUpdate

router = APIRouter(prefix="/books", tags=["books"])

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_SEARCH_RESULTS = 100

_COLUMNS = "id, isbn, title, author, year, copies_total, copies_available, created_at"


def create_book(conn: sqlite3.Connection, data: BookCreate, now: datetime) -> Book:
    try:
        with conn:
            row = conn.execute(
                """
                INSERT INTO books
                    (isbn, title, author, year, copies_total, copies_available, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    data.isbn,
                    data.title,
                    data.author,
                    data.year,
                    data.copies,
                    data.copies,
                    timestamp(now),
                ),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"a book with ISBN {data.isbn} is already in the catalog") from exc
    return get_book(conn, row["id"])


def get_book(conn: sqlite3.Connection, book_id: int) -> Book:
    row = conn.execute(
        f"""SELECT {_COLUMNS} FROM books WHERE id = ? AND deleted_at IS NULL""", (book_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"book {book_id} not found")
    return Book.model_validate(row)


def list_books(conn: sqlite3.Connection, page: int = 1, size: int = DEFAULT_PAGE_SIZE) -> BookPage:
    """Return one page of the catalog, oldest entries first."""
    total = conn.execute("""SELECT COUNT(*) AS n FROM books WHERE deleted_at IS NULL""").fetchone()[
        "n"
    ]
    offset = (page - 1) * size
    rows = conn.execute(
        f"""
        SELECT {_COLUMNS} FROM books
        WHERE deleted_at IS NULL
        ORDER BY id
        LIMIT ? OFFSET ?
        """,
        (size + 1, offset),
    ).fetchall()
    return BookPage(
        items=[Book.model_validate(row) for row in rows[:size]],
        page=page,
        size=size,
        total=total,
        has_next=len(rows) > size,
    )


def search_books(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[Book]:
    """Find books whose title or author contains ``query``.

    ``instr`` with ``lower`` is used rather than ``LIKE`` so that ``%`` and ``_``
    in the query are matched literally and comparisons are case-insensitive.
    """
    term = query.strip().lower()
    if not term:
        return []
    rows = conn.execute(
        f"""
        SELECT {_COLUMNS} FROM books
        WHERE deleted_at IS NULL
          AND (instr(lower(title), ?) > 0 OR instr(lower(author), ?) > 0)
        ORDER BY title, id
        LIMIT ?
        """,
        (term, term, limit),
    ).fetchall()
    return [Book.model_validate(row) for row in rows]


def update_book(conn: sqlite3.Connection, book_id: int, changes: BookUpdate) -> Book:
    book = get_book(conn, book_id)
    fields: dict[str, Any] = changes.model_dump(exclude_unset=True)
    if not fields:
        return book
    if "copies" in fields:
        copies = fields.pop("copies")
        on_loan = book.copies_total - book.copies_available
        if copies < on_loan:
            raise Conflict(f"{on_loan} copies are on loan; the total cannot go below that")
        fields["copies_total"] = copies
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with conn:
        conn.execute(
            f"""UPDATE books SET {assignments} WHERE id = ?""",
            (*fields.values(), book_id),
        )
    return get_book(conn, book_id)


def delete_book(conn: sqlite3.Connection, book_id: int, now: datetime) -> None:
    """Soft-delete a book. Books with copies still out cannot be deleted."""
    get_book(conn, book_id)
    out = conn.execute(
        """SELECT COUNT(*) AS n FROM loans WHERE book_id = ? AND returned_at IS NULL""",
        (book_id,),
    ).fetchone()["n"]
    if out:
        raise Conflict(f"book {book_id} has {out} copies on loan")
    with conn:
        conn.execute("""UPDATE books SET deleted_at = ? WHERE id = ?""", (timestamp(now), book_id))


@router.get("")
def get_books(
    conn: ConnDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> BookPage:
    return list_books(conn, page=page, size=size)


@router.get("/search")
def search(
    conn: ConnDep,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=MAX_SEARCH_RESULTS)] = 20,
) -> list[Book]:
    return search_books(conn, q, limit=limit)


@router.get("/{book_id}")
def get_one(book_id: int, conn: ConnDep) -> Book:
    return get_book(conn, book_id)


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def add_book(data: BookCreate, conn: ConnDep, clock: ClockDep) -> Book:
    return create_book(conn, data, clock.now())


@router.patch("/{book_id}", dependencies=[Depends(require_admin)])
def edit_book(book_id: int, changes: BookUpdate, conn: ConnDep) -> Book:
    return update_book(conn, book_id, changes)


@router.delete(
    "/{book_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)]
)
def remove_book(book_id: int, conn: ConnDep, clock: ClockDep) -> Response:
    delete_book(conn, book_id, clock.now())
    return Response(status_code=status.HTTP_204_NO_CONTENT)
