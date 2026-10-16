"""Helpers shared by the tests."""

import itertools
from typing import Any

from fastapi.testclient import TestClient


class Library:
    """Creates books, members and loans through the API."""

    def __init__(self, client: TestClient, admin: dict[str, str]) -> None:
        self.client = client
        self.admin = admin
        self._isbns = itertools.count(1)
        self._members = itertools.count(1)

    def book(self, **overrides: Any) -> dict[str, Any]:
        payload = {
            "isbn": f"978{next(self._isbns):010d}",
            "title": "Dune",
            "author": "Frank Herbert",
            "year": 1965,
            "copies": 1,
            **overrides,
        }
        response = self.client.post("/books", json=payload, headers=self.admin)
        assert response.status_code == 201, response.text
        return dict(response.json())

    def member(self, **overrides: Any) -> dict[str, Any]:
        n = next(self._members)
        payload = {"name": f"Member {n}", "email": f"member{n}@example.org", **overrides}
        response = self.client.post("/members", json=payload)
        assert response.status_code == 201, response.text
        return dict(response.json())

    def checkout(self, book_id: int, member_id: int) -> dict[str, Any]:
        response = self.client.post("/loans", json={"book_id": book_id, "member_id": member_id})
        assert response.status_code == 201, response.text
        return dict(response.json())

    def give_back(self, loan_id: int) -> dict[str, Any]:
        response = self.client.post(f"/loans/{loan_id}/return")
        assert response.status_code == 200, response.text
        return dict(response.json())
