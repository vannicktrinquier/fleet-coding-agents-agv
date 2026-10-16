"""Library members."""

import sqlite3
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, status

from app.auth import require_admin
from app.db import timestamp
from app.deps import ClockDep, ConnDep
from app.errors import Conflict, NotFound
from app.models import Member, MemberCreate, MemberUpdate

router = APIRouter(prefix="/members", tags=["members"])

_COLUMNS = "id, name, email, active, created_at"


def _email_taken(conn: sqlite3.Connection, email: str, exclude_id: int | None = None) -> bool:
    row = conn.execute(
        """SELECT id FROM members WHERE email = ? AND id IS NOT ?""", (email, exclude_id)
    ).fetchone()
    return row is not None


def create_member(conn: sqlite3.Connection, data: MemberCreate, now: datetime) -> Member:
    if _email_taken(conn, data.email):
        raise Conflict(f"{data.email} is already registered")
    with conn:
        row = conn.execute(
            """
            INSERT INTO members (name, email, active, created_at)
            VALUES (?, ?, 1, ?)
            RETURNING id
            """,
            (data.name, data.email, timestamp(now)),
        ).fetchone()
    return get_member(conn, row["id"])


def get_member(conn: sqlite3.Connection, member_id: int) -> Member:
    row = conn.execute(f"""SELECT {_COLUMNS} FROM members WHERE id = ?""", (member_id,)).fetchone()
    if row is None:
        raise NotFound(f"member {member_id} not found")
    return Member.model_validate(row)


def update_member(conn: sqlite3.Connection, member_id: int, changes: MemberUpdate) -> Member:
    member = get_member(conn, member_id)
    fields: dict[str, Any] = changes.model_dump(exclude_unset=True)
    if not fields:
        return member
    if "email" in fields and _email_taken(conn, fields["email"], exclude_id=member_id):
        raise Conflict(f"{fields['email']} is already registered")
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with conn:
        conn.execute(
            f"""UPDATE members SET {assignments} WHERE id = ?""", (*fields.values(), member_id)
        )
    return get_member(conn, member_id)


def deactivate_member(conn: sqlite3.Connection, member_id: int) -> Member:
    """Deactivated members keep their history but cannot borrow."""
    get_member(conn, member_id)
    with conn:
        conn.execute("""UPDATE members SET active = 0 WHERE id = ?""", (member_id,))
    return get_member(conn, member_id)


@router.post("", status_code=status.HTTP_201_CREATED)
def register(data: MemberCreate, conn: ConnDep, clock: ClockDep) -> Member:
    return create_member(conn, data, clock.now())


@router.get("/{member_id}")
def get_one(member_id: int, conn: ConnDep) -> Member:
    return get_member(conn, member_id)


@router.patch("/{member_id}")
def edit(member_id: int, changes: MemberUpdate, conn: ConnDep) -> Member:
    return update_member(conn, member_id, changes)


@router.post("/{member_id}/deactivate", dependencies=[Depends(require_admin)])
def deactivate(member_id: int, conn: ConnDep) -> Member:
    return deactivate_member(conn, member_id)
