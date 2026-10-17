"""Loans: checkout, return, renewal and overdue tracking."""

import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends, status

from app import fines
from app.auth import require_admin
from app.books import get_book
from app.clock import Clock
from app.config import Settings
from app.db import timestamp
from app.deps import ClockDep, ConnDep, SettingsDep
from app.errors import Conflict, NotFound
from app.members import get_member
from app.models import CheckoutRequest, Loan

router = APIRouter(prefix="/loans", tags=["loans"])

_COLUMNS = "id, book_id, member_id, loaned_at, due_on, returned_at, renewals, fine_cents"


def get_loan(conn: sqlite3.Connection, loan_id: int) -> Loan:
    row = conn.execute(f"""SELECT {_COLUMNS} FROM loans WHERE id = ?""", (loan_id,)).fetchone()
    if row is None:
        raise NotFound(f"loan {loan_id} not found")
    return Loan.model_validate(row)


def open_loan_book_ids(conn: sqlite3.Connection, member_id: int) -> list[int]:
    rows = conn.execute(
        """
        SELECT book_id FROM loans
        WHERE member_id = ? AND returned_at IS NULL
        ORDER BY id
        """,
        (member_id,),
    ).fetchall()
    return [row["book_id"] for row in rows]


def checkout(
    conn: sqlite3.Connection, book_id: int, member_id: int, clock: Clock, settings: Settings
) -> Loan:
    """Lend one copy of a book to a member for ``settings.loan_days`` days."""
    member = get_member(conn, member_id)
    if not member.active:
        raise Conflict(f"member {member_id} is not active")
    get_book(conn, book_id)
    holding = open_loan_book_ids(conn, member_id)
    if book_id in holding:
        raise Conflict(f"member {member_id} already has a copy of book {book_id}")
    if len(holding) >= settings.max_active_loans:
        raise Conflict(
            f"member {member_id} already has {len(holding)} books out"
            f" (limit {settings.max_active_loans})"
        )
    owed = fines.outstanding_cents(conn, member_id, clock.today(), settings.fines)
    if owed >= settings.fine_block_cents:
        raise Conflict(f"member {member_id} owes {fines.format_cents(owed)} in fines")

    due_on = clock.today() + timedelta(days=settings.loan_days)
    with conn:
        taken = conn.execute(
            """
            UPDATE books SET copies_available = copies_available - 1
            WHERE id = ? AND copies_available > 0
            """,
            (book_id,),
        ).rowcount
        if not taken:
            raise Conflict(f"no copies of book {book_id} are available")
        row = conn.execute(
            """
            INSERT INTO loans (book_id, member_id, loaned_at, due_on)
            VALUES (?, ?, ?, ?)
            RETURNING id
            """,
            (book_id, member_id, timestamp(clock.now()), due_on.isoformat()),
        ).fetchone()
    return get_loan(conn, row["id"])


def return_loan(conn: sqlite3.Connection, loan_id: int, clock: Clock, settings: Settings) -> Loan:
    """Check a book back in and record the loan's fine, if any."""
    loan = get_loan(conn, loan_id)
    if loan.returned_at is not None:
        raise Conflict(f"loan {loan_id} has already been returned")
    fine = fines.compute_fine(loan.due_on, clock.today(), settings.fines)
    with conn:
        conn.execute(
            """UPDATE loans SET returned_at = ?, fine_cents = ? WHERE id = ?""",
            (timestamp(clock.now()), fine, loan_id),
        )
        conn.execute(
            """UPDATE books SET copies_available = copies_available + 1 WHERE id = ?""",
            (loan.book_id,),
        )
    return get_loan(conn, loan_id)


def renew_loan(conn: sqlite3.Connection, loan_id: int, clock: Clock, settings: Settings) -> Loan:
    """Extend a loan: the new due date is ``settings.loan_days`` after today."""
    loan = get_loan(conn, loan_id)
    if loan.returned_at is not None:
        raise Conflict(f"loan {loan_id} has already been returned")
    due_on = clock.today() + timedelta(days=settings.loan_days)
    with conn:
        conn.execute(
            """UPDATE loans SET due_on = ?, renewals = renewals + 1 WHERE id = ?""",
            (due_on.isoformat(), loan_id),
        )
    return get_loan(conn, loan_id)


def list_overdue(conn: sqlite3.Connection, today: date) -> list[Loan]:
    """Open loans whose due date has passed, most overdue first."""
    rows = conn.execute(
        f"""
        SELECT {_COLUMNS} FROM loans
        WHERE returned_at IS NULL AND due_on < ?
        ORDER BY due_on, id
        """,
        (today.isoformat(),),
    ).fetchall()
    return [Loan.model_validate(row) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def borrow(body: CheckoutRequest, conn: ConnDep, clock: ClockDep, settings: SettingsDep) -> Loan:
    return checkout(conn, body.book_id, body.member_id, clock, settings)


@router.get("/overdue", dependencies=[Depends(require_admin)])
def overdue(conn: ConnDep, clock: ClockDep) -> list[Loan]:
    return list_overdue(conn, clock.today())


@router.get("/{loan_id}")
def get_one(loan_id: int, conn: ConnDep) -> Loan:
    return get_loan(conn, loan_id)


@router.post("/{loan_id}/return")
def give_back(loan_id: int, conn: ConnDep, clock: ClockDep, settings: SettingsDep) -> Loan:
    return return_loan(conn, loan_id, clock, settings)


@router.post("/{loan_id}/renew")
def renew(loan_id: int, conn: ConnDep, clock: ClockDep, settings: SettingsDep) -> Loan:
    return renew_loan(conn, loan_id, clock, settings)
