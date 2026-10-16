-- Initial schema: catalog, members and loans.
-- Timestamps are UTC ISO 8601 strings (see app.db.timestamp); dates are YYYY-MM-DD.

CREATE TABLE books (
    id                INTEGER PRIMARY KEY,
    isbn              TEXT    NOT NULL,
    title             TEXT    NOT NULL,
    author            TEXT    NOT NULL,
    year              INTEGER,
    copies_total      INTEGER NOT NULL CHECK (copies_total >= 0),
    copies_available  INTEGER NOT NULL CHECK (copies_available >= 0),
    created_at        TEXT    NOT NULL,
    deleted_at        TEXT
);

-- A deleted book's ISBN can be catalogued again.
CREATE UNIQUE INDEX idx_books_isbn_live ON books (isbn) WHERE deleted_at IS NULL;
CREATE INDEX idx_books_title ON books (title);
CREATE INDEX idx_books_author ON books (author);

CREATE TABLE members (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    email       TEXT    NOT NULL UNIQUE,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL
);

CREATE TABLE loans (
    id            INTEGER PRIMARY KEY,
    book_id       INTEGER NOT NULL REFERENCES books (id),
    member_id     INTEGER NOT NULL REFERENCES members (id),
    loaned_at     TEXT    NOT NULL,
    due_on        TEXT    NOT NULL,
    returned_at   TEXT,
    renewals      INTEGER NOT NULL DEFAULT 0,
    fine_cents    INTEGER NOT NULL DEFAULT 0,
    fine_paid_at  TEXT
);

CREATE INDEX idx_loans_member ON loans (member_id);
CREATE INDEX idx_loans_book ON loans (book_id);
