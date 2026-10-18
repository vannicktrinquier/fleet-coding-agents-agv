"""Admin reports: catalog, membership and lending statistics."""

import sqlite3
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth import require_admin
from app.db import timestamp
from app.deps import ClockDep, ConnDep
from app.models import BookStats, LoanStats, MemberStats, PopularBook, SummaryReport

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(require_admin)])

RECENT_RETURNS_DAYS = 30


def book_stats(conn: sqlite3.Connection) -> BookStats:
    row = conn.execute(
        """
        SELECT COUNT(*) AS titles,
               COALESCE(SUM(copies_total), 0) AS copies,
               COALESCE(SUM(copies_available), 0) AS available
        FROM books
        WHERE deleted_at IS NULL
        """
    ).fetchone()
    return BookStats(
        titles=row["titles"],
        copies=row["copies"],
        available=row["available"],
        on_loan=row["copies"] - row["available"],
    )


def member_stats(conn: sqlite3.Connection, now: datetime) -> MemberStats:
    row = conn.execute(
        """SELECT COUNT(*) AS total, COALESCE(SUM(active), 0) AS active FROM members"""
    ).fetchone()
    with_overdue: int = conn.execute(
        """
        SELECT COUNT(DISTINCT member_id) AS with_overdue
        FROM loans
        WHERE returned_at IS NULL AND due_on < ?
        """,
        (now.date().isoformat(),),
    ).fetchone()["with_overdue"]
    return MemberStats(
        total=row["total"],
        active=row["active"],
        with_overdue=with_overdue,
    )


def loan_stats(conn: sqlite3.Connection, now: datetime) -> LoanStats:
    since = now - timedelta(days=RECENT_RETURNS_DAYS)
    row = conn.execute(
        """
        SELECT COALESCE(SUM(returned_at IS NULL), 0) AS open,
               COALESCE(SUM(returned_at IS NULL AND due_on < ?), 0) AS overdue,
               COALESCE(SUM(returned_at >= ?), 0) AS returned_recently
        FROM loans
        """,
        (now.date().isoformat(), timestamp(since)),
    ).fetchone()
    return LoanStats(
        open=row["open"],
        overdue=row["overdue"],
        returned_last_30_days=row["returned_recently"],
    )


def outstanding_fines(conn: sqlite3.Connection) -> int:
    """Unpaid fines on returned loans. Fines still accruing are not included."""
    total: int = conn.execute(
        """
        SELECT COALESCE(SUM(fine_cents), 0) AS cents FROM loans
        WHERE returned_at IS NOT NULL AND fine_paid_at IS NULL
        """
    ).fetchone()["cents"]
    return total


def summary(conn: sqlite3.Connection, now: datetime) -> SummaryReport:
    return SummaryReport(
        generated_at=now,
        books=book_stats(conn),
        members=member_stats(conn, now),
        loans=loan_stats(conn, now),
        outstanding_fines_cents=outstanding_fines(conn),
    )


def popular_books(
    conn: sqlite3.Connection, now: datetime, days: int = 30, limit: int = 10
) -> list[PopularBook]:
    """Most borrowed books over the last ``days`` days."""
    since = now - timedelta(days=days)
    rows = conn.execute(
        """
        SELECT b.id AS book_id, b.title, b.author, COUNT(*) AS loans
        FROM loans AS l JOIN books AS b ON b.id = l.book_id
        WHERE l.loaned_at >= ? AND b.deleted_at IS NULL
        GROUP BY b.id
        ORDER BY loans DESC, b.title, b.id
        LIMIT ?
        """,
        (timestamp(since), limit),
    ).fetchall()
    return [PopularBook.model_validate(row) for row in rows]


@router.get("/summary")
def get_summary(conn: ConnDep, clock: ClockDep) -> SummaryReport:
    return summary(conn, clock.now())


@router.get("/popular")
def get_popular(
    conn: ConnDep,
    clock: ClockDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[PopularBook]:
    return popular_books(conn, clock.now(), days=days, limit=limit)
