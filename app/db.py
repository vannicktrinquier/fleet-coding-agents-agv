"""SQLite access: connections, timestamps and schema migrations."""

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_MIGRATION_NAME = re.compile(r"^\d{3}_[a-z0-9_]+$")


def dict_row(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    """Row factory: rows as plain dicts keyed by column name."""
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection configured the way every request expects.

    Connections are opened per request and may be used from FastAPI's worker
    threads, hence ``check_same_thread=False``.
    """
    conn = sqlite3.connect(db_path, timeout=5.0, check_same_thread=False)
    conn.row_factory = dict_row
    conn.execute("""PRAGMA foreign_keys = ON""")
    return conn


def timestamp(moment: datetime) -> str:
    """Format a moment for storage: UTC, ISO 8601, second precision.

    Stored timestamps all share this format, so they compare correctly as text.
    """
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def pending_migrations(conn: sqlite3.Connection) -> list[Path]:
    done = {row["version"] for row in conn.execute("""SELECT version FROM schema_migrations""")}
    return [path for path in sorted(MIGRATIONS_DIR.glob("*.sql")) if path.stem not in done]


def migrate(db_path: str | Path, applied_at: datetime) -> list[str]:
    """Apply pending ``app/migrations/*.sql`` files in name order.

    Each file runs in its own transaction together with its bookkeeping row,
    so a failing migration leaves the schema as it was. Returns the versions
    applied by this call.
    """
    conn = connect(db_path)
    try:
        conn.execute("""PRAGMA journal_mode = WAL""")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     TEXT PRIMARY KEY,
                applied_at  TEXT NOT NULL
            )
            """
        )
        conn.commit()
        applied: list[str] = []
        for path in pending_migrations(conn):
            version = path.stem
            if not _MIGRATION_NAME.match(version):
                raise RuntimeError(f"unexpected migration file name: {path.name}")
            script = path.read_text(encoding="utf-8")
            conn.executescript(
                f"""
                BEGIN;
                {script}
                ;
                INSERT INTO schema_migrations (version, applied_at)
                VALUES ('{version}', '{timestamp(applied_at)}');
                COMMIT;
                """
            )
            applied.append(version)
        return applied
    finally:
        conn.close()


def schema_version(db_path: str | Path) -> str | None:
    """Return the latest applied migration, or None for an empty database."""
    conn = connect(db_path)
    try:
        row = conn.execute("""SELECT max(version) AS version FROM schema_migrations""").fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    version: str | None = row["version"]
    return version
