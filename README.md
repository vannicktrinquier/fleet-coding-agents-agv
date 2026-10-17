# Lending Library

A small HTTP service for a community lending library: the catalog, members, loans
and late fines. It is a [FastAPI](https://fastapi.tiangolo.com/) app on top of a
single SQLite file.

Contributors (human or AI) should read [AGENTS.md](AGENTS.md) first: it holds the
engineering rules and the definition of done.

## Quick start

You need [uv](https://docs.astral.sh/uv/) and GNU make.

```sh
make setup                              # .venv with the pinned dev dependencies
make check                              # ruff, ruff format --check, mypy, pytest
LIBRARY_ADMIN_KEY=change-me make run    # http://127.0.0.1:8000/docs
```

The database file is created and migrated on startup.

## Configuration

| Variable | Default | Meaning |
| :--- | :--- | :--- |
| `LIBRARY_DB` | `library.db` | SQLite file |
| `LIBRARY_ADMIN_KEY` | unset | Key that admin endpoints expect in the `X-API-Key` header |
| `LIBRARY_LOAN_DAYS` | `14` | Loan period, also used for renewals |
| `LIBRARY_MAX_ACTIVE_LOANS` | `5` | Books a member may have out at once |
| `LIBRARY_FINE_GRACE_DAYS` | `3` | Days late before a fine applies |
| `LIBRARY_FINE_DAILY_CENTS` | `25` | Fine per day late |
| `LIBRARY_FINE_CAP_CENTS` | `1000` | Maximum fine per loan |
| `LIBRARY_FINE_BLOCK_CENTS` | `500` | Unpaid fines at which a member can no longer borrow |

## API

Endpoints marked *admin* need the `X-API-Key` header. Interactive documentation is
served at `/docs`.

| Method | Path | Admin | Description |
| :--- | :--- | :---: | :--- |
| GET | `/health` | | Liveness and schema version |
| GET | `/books?page=1&size=20` | | The catalog, oldest entries first |
| GET | `/books/search?q=...&limit=20` | | Search titles and authors |
| GET | `/books/{id}` | | One book |
| POST | `/books` | admin | Add a book: `isbn`, `title`, `author`, `year`, `copies` |
| PATCH | `/books/{id}` | admin | Change `title`, `author`, `year` or `copies` |
| DELETE | `/books/{id}` | admin | Remove a book from the catalog |
| POST | `/members` | | Register a member: `name`, `email` |
| GET | `/members/{id}` | | One member |
| PATCH | `/members/{id}` | | Change `name` or `email` |
| POST | `/members/{id}/deactivate` | admin | Stop a member from borrowing |
| GET | `/members/{id}/loans` | | A member's loans, newest first |
| GET | `/members/{id}/fines` | | Unpaid fines, settled and still accruing |
| POST | `/members/{id}/fines/pay` | admin | Mark the settled fines as paid |
| POST | `/loans` | | Check out a book: `book_id`, `member_id` |
| GET | `/loans/{id}` | | One loan |
| POST | `/loans/{id}/return` | | Check a book back in |
| POST | `/loans/{id}/renew` | | Renew a loan |
| GET | `/loans/overdue` | admin | Open loans past their due date |
| GET | `/reports/summary` | admin | Catalog, member, loan and fine totals |

Errors are JSON objects with a `detail` field: `401` for a missing or wrong admin
key, `404` for unknown ids, `409` when a library rule forbids the request and `422`
for invalid input. Money is in cents. Dates and times are UTC.

## Library rules

- **Catalog.** Books are identified by ISBN-10 or ISBN-13; hyphens and spaces are
  ignored. Changing the number of copies keeps the copies on loan out and makes the
  others available. A book with copies on loan cannot be deleted. Deleted books
  disappear from listings, search and reports, and their ISBN can be added again.
- **Listing.** `GET /books` returns pages of `size` books (default 20, at most 100)
  with `total` and `has_next`. Walking the pages from 1 visits every book once.
- **Search.** Case-insensitive substring match on the title or the author, ordered
  by title. `%` and `_` in the query are matched literally.
- **Members.** Email addresses are unique, compared case-insensitively. Deactivated
  members keep their history but cannot borrow.
- **Loans.** A loan lasts 14 days. A member may have up to 5 books out, at most one
  copy of each, and cannot borrow while they owe $5.00 or more in fines.
- **Returns.** A loan is returned once. The copy goes back on the shelf and the fine,
  if any, is recorded on the loan.
- **Renewals.** Renewing sets the due date to 14 days after the renewal date.
  Overdue loans cannot be renewed: the book has to be returned and the fine paid.
- **Fines.** A book returned up to 3 days after its due date is not fined. After
  that, the fine is 25 cents for every day since the due date, capped at $10.00 per
  loan. Fines on books that are still out keep growing and count toward the
  borrowing limit above.
- **Reports.** The summary only counts books that are in the catalog (deleted books
  are excluded). Outstanding fines cover returned loans only.

## Development

```text
app/
  main.py         create_app(db_path, clock, settings) factory
  db.py           connections, timestamps, migrations (app/migrations/*.sql)
  clock.py        Clock protocol, SystemClock, FixedClock
  config.py       Settings and FinePolicy, read from LIBRARY_* variables
  models.py       request and response models (pydantic)
  books.py        catalog, listing, search
  members.py      members
  loans.py        checkout, return, renewal, overdue
  fines.py        fine rules, member fines, payment
  reports.py      admin reports
  auth.py         admin API key check
tests/            pytest suite: one temporary SQLite file and a FixedClock per test
scripts/          CI evidence scripts (see below)
```

| Command | What it does |
| :--- | :--- |
| `make setup` | Create `.venv` from `requirements-dev.txt` and install the app in editable mode |
| `make check` | `make lint typecheck test` |
| `make format` | Apply ruff formatting and safe fixes |
| `make mutate` | Mutation testing with mutmut (`MUTANTS='app.reports*'` to scope it) |
| `make lock` | Regenerate the hash-pinned `requirements.txt` and `requirements-dev.txt` |
| `make run` | Serve the API locally |

Dependencies are declared in `pyproject.toml` and pinned, with hashes, in
`requirements.txt` (runtime) and `requirements-dev.txt` (runtime and tools). The
pinned files work with any package index; there is no `uv.lock`.

### CI

`.github/workflows/fleet.yml` runs on pull requests and on pushes to `main` and
`fleet/train/**`, always against the exact commit under test:

- **fleet/tests** runs `scripts/ci_evidence.sh`: ruff, ruff format, mypy and pytest.
- **fleet/repro** runs `scripts/repro.sh` on pull requests labelled `type:bug`: the
  tests the PR adds or changes must pass at its head and fail when the code outside
  `tests/` is put back to the merge base.

Both report a single `fleet-verdict` annotation: `PASS`, `FAIL` or `UNKNOWN` (the
check could not tell, for example because no tests ran or a step timed out).
