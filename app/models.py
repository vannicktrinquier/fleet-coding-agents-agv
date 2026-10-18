"""Request and response models."""

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Author = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Email = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]
Year = Annotated[int, Field(ge=1450, le=2100)]


def normalize_isbn(value: str) -> str:
    """Strip hyphens and spaces from an ISBN-10 or ISBN-13 and validate its shape."""
    compact = value.replace("-", "").replace(" ", "").upper()
    if not compact.isascii():
        raise ValueError("ISBN must contain only digits, hyphens and spaces")
    if len(compact) == 13 and compact.isdigit():
        return compact
    if len(compact) == 10 and compact[:9].isdigit() and (compact[9].isdigit() or compact[9] == "X"):
        return compact
    raise ValueError("ISBN must have 10 or 13 digits (an ISBN-10 may end in X)")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BookCreate(_Input):
    isbn: str
    title: Title
    author: Author
    year: Year | None = None
    copies: int = Field(default=1, ge=1, le=500)

    @field_validator("isbn")
    @classmethod
    def _check_isbn(cls, value: str) -> str:
        return normalize_isbn(value)


class BookUpdate(_Input):
    title: Title | None = None
    author: Author | None = None
    year: Year | None = None
    copies: int | None = Field(default=None, ge=0, le=500)

    @field_validator("title", "author", "copies")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("may not be null")
        return value


class Book(BaseModel):
    id: int
    isbn: str
    title: str
    author: str
    year: int | None
    copies_total: int
    copies_available: int
    created_at: datetime


class BookPage(BaseModel):
    items: list[Book]
    page: int
    size: int
    total: int
    has_next: bool


class MemberCreate(_Input):
    name: PersonName
    email: Email


class MemberUpdate(_Input):
    name: PersonName | None = None
    email: Email | None = None

    @field_validator("name", "email")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("may not be null")
        return value


class Member(BaseModel):
    id: int
    name: str
    email: str
    active: bool
    created_at: datetime


class CheckoutRequest(_Input):
    book_id: int = Field(gt=0)
    member_id: int = Field(gt=0)


class Loan(BaseModel):
    id: int
    book_id: int
    member_id: int
    loaned_at: datetime
    due_on: date
    returned_at: datetime | None
    renewals: int
    fine_cents: int


class OverdueLoan(Loan):
    days_overdue: int
    accrued_fine_cents: int


class FineItem(BaseModel):
    loan_id: int
    book_id: int
    due_on: date
    days_late: int
    amount_cents: int
    accruing: bool = Field(description="True while the book is still out and the fine grows.")


class FineSummary(BaseModel):
    member_id: int
    total_cents: int
    items: list[FineItem]


class FinePayment(BaseModel):
    member_id: int
    paid_cents: int
    loan_ids: list[int]


class BookStats(BaseModel):
    titles: int
    copies: int
    available: int
    on_loan: int


class MemberStats(BaseModel):
    total: int
    active: int
    with_overdue: int


class LoanStats(BaseModel):
    open: int
    overdue: int
    returned_last_30_days: int


class SummaryReport(BaseModel):
    generated_at: datetime
    books: BookStats
    members: MemberStats
    loans: LoanStats
    outstanding_fines_cents: int


class PopularBook(BaseModel):
    book_id: int
    title: str
    author: str
    loans: int
