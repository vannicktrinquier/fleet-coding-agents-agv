"""Late fines.

A loan returned after its due date is fined per day late, after a grace
period and up to a cap per loan (see ``app.config.FinePolicy``). Fines on
books that are still out keep growing until the book comes back. Amounts are
in cents.
"""

import re
import sqlite3
from datetime import date, datetime

from fastapi import APIRouter, Depends

from app.auth import require_admin
from app.config import FinePolicy
from app.db import timestamp
from app.deps import ClockDep, ConnDep, SettingsDep
from app.members import get_member
from app.models import FineItem, FinePayment, FineSummary

router = APIRouter(tags=["fines"])


def days_late(due_on: date, on: date) -> int:
    return max(0, (on - due_on).days)


def compute_fine(due_on: date, on: date, policy: FinePolicy) -> int:
    """Fine for a book due on ``due_on`` and returned (or still out) on ``on``."""
    late = days_late(due_on, on)
    if late <= policy.grace_days:
        return 0
    return min(late * policy.daily_cents, policy.cap_cents)


def is_at_fine_cap(due_on: date, on: date, policy: FinePolicy) -> bool:
    """Whether the fine for a book due on ``due_on`` has reached the policy cap on ``on``."""
    return policy.cap_cents > 0 and compute_fine(due_on, on, policy) >= policy.cap_cents


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    total = abs(cents)
    return f"{sign}${total // 100}.{total % 100:02d}"


def parse_cents(text: str) -> int:
    match = re.fullmatch(r"(-?)\$([0-9]+)(?:\.([0-9]{2}))?", text.strip())
    if match is None:
        raise ValueError(f"invalid amount: {text!r}")
    sign, dollars, cents = match.groups()
    total = int(dollars) * 100 + int(cents or 0)
    return -total if sign == "-" else total


def member_fines(
    conn: sqlite3.Connection, member_id: int, today: date, policy: FinePolicy
) -> FineSummary:
    """Unpaid fines: settled amounts on returned loans plus fines still accruing."""
    get_member(conn, member_id)
    rows = conn.execute(
        """
        SELECT id, book_id, due_on, returned_at, fine_cents FROM loans
        WHERE member_id = ? AND fine_paid_at IS NULL
          AND (returned_at IS NULL OR fine_cents > 0)
        ORDER BY id
        """,
        (member_id,),
    ).fetchall()
    items: list[FineItem] = []
    for row in rows:
        due_on = date.fromisoformat(row["due_on"])
        if row["returned_at"] is None:
            late = days_late(due_on, today)
            amount = compute_fine(due_on, today, policy)
            accruing = True
        else:
            returned_on = datetime.fromisoformat(row["returned_at"]).date()
            late = days_late(due_on, returned_on)
            amount = row["fine_cents"]
            accruing = False
        if amount > 0:
            items.append(
                FineItem(
                    loan_id=row["id"],
                    book_id=row["book_id"],
                    due_on=due_on,
                    days_late=late,
                    amount_cents=amount,
                    accruing=accruing,
                )
            )
    return FineSummary(
        member_id=member_id,
        total_cents=sum(item.amount_cents for item in items),
        items=items,
    )


def outstanding_cents(
    conn: sqlite3.Connection, member_id: int, today: date, policy: FinePolicy
) -> int:
    return member_fines(conn, member_id, today, policy).total_cents


def pay_fines(conn: sqlite3.Connection, member_id: int, now: datetime) -> FinePayment:
    """Settle the fines on returned loans. Fines still accruing cannot be paid yet."""
    get_member(conn, member_id)
    rows = conn.execute(
        """
        SELECT id, fine_cents FROM loans
        WHERE member_id = ? AND returned_at IS NOT NULL
          AND fine_cents > 0 AND fine_paid_at IS NULL
        ORDER BY id
        """,
        (member_id,),
    ).fetchall()
    paid_at = timestamp(now)
    with conn:
        conn.executemany(
            """UPDATE loans SET fine_paid_at = ? WHERE id = ?""",
            [(paid_at, row["id"]) for row in rows],
        )
    return FinePayment(
        member_id=member_id,
        paid_cents=sum(row["fine_cents"] for row in rows),
        loan_ids=[row["id"] for row in rows],
    )


@router.get("/members/{member_id}/fines")
def get_fines(member_id: int, conn: ConnDep, clock: ClockDep, settings: SettingsDep) -> FineSummary:
    return member_fines(conn, member_id, clock.today(), settings.fines)


@router.post("/members/{member_id}/fines/pay", dependencies=[Depends(require_admin)])
def pay(member_id: int, conn: ConnDep, clock: ClockDep) -> FinePayment:
    return pay_fines(conn, member_id, clock.now())
