from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient

from app import db
from app.clock import FixedClock

CATALOG_SIZE = 2_000
AUTHORS = [
    "Frank Herbert",
    "Jane Austen",
    "Octavia E. Butler",
    "Ursula K. Le Guin",
    "Terry Pratchett",
]


def seed_catalog(db_path: Path, clock: FixedClock, count: int) -> None:
    created_at = db.timestamp(clock.now())
    rows = [
        (f"978{n:010d}", f"Volume {n}", AUTHORS[n % len(AUTHORS)], 1950 + n % 70, created_at)
        for n in range(count)
    ]
    conn = db.connect(db_path)
    try:
        with conn:
            conn.executemany(
                """
                INSERT INTO books
                    (isbn, title, author, year, copies_total, copies_available, created_at)
                VALUES (?, ?, ?, ?, 1, 1, ?)
                """,
                rows,
            )
    finally:
        conn.close()


def test_search_is_fast(client: TestClient, db_path: Path, clock: FixedClock) -> None:
    seed_catalog(db_path, clock, CATALOG_SIZE)

    started = perf_counter()
    for term in ("Herbert", "Le Guin", "Volume 1999", "Pratchett"):
        response = client.get("/books/search", params={"q": term, "limit": 50})
        assert response.status_code == 200
        assert response.json()
    elapsed = perf_counter() - started

    assert elapsed < 0.25
