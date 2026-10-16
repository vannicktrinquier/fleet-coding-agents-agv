# AGENTS.md

How to work on this repository. Written for AI coding agents first, and for the
humans who review their work. Product behavior (API, library rules) is specified in
[README.md](README.md); this file covers how changes are made.

## How to run

```sh
make setup      # once: .venv with the pinned dev dependencies, app installed in editable mode
make check      # ruff check, ruff format --check, mypy app, pytest: what fleet/tests runs
make test       # pytest only; for one area: .venv/bin/pytest tests/test_loans.py -k renew
make format     # apply ruff formatting and safe fixes
make mutate     # mutmut; scope it with MUTANTS='app.fines*'
make lock       # regenerate requirements*.txt after editing dependencies in pyproject.toml
```

- Python 3.12. Dependencies are pinned with hashes in `requirements.txt` and
  `requirements-dev.txt`. There is no `uv.lock`; do not add one.
- Run `make check` before pushing. The whole suite takes a few seconds.

## Map

| Path | Contents |
| :--- | :--- |
| `app/books.py`, `members.py`, `loans.py`, `fines.py`, `reports.py` | One module per domain: plain functions that take a `sqlite3.Connection`, then a thin FastAPI router at the bottom |
| `app/models.py` | Pydantic request and response models |
| `app/main.py` | `create_app(db_path, clock, settings)` and router wiring |
| `app/db.py` | `connect()`, `timestamp()`, `migrate()` |
| `app/migrations/NNN_name.sql` | Schema migrations, applied in order at startup. Never edit one that has shipped; add a new file |
| `app/clock.py` | `Clock` protocol, `SystemClock`, `FixedClock` |
| `app/config.py` | `Settings` and `FinePolicy`, read from `LIBRARY_*` variables |
| `app/auth.py` | Admin API key check |
| `tests/` | pytest. `conftest.py` gives each test its own SQLite file, a `FixedClock` at 2026-03-02 10:00 UTC and a `TestClient`; `tests/support.py` has the `Library` helper that creates books, members and loans |
| `scripts/ci_evidence.sh`, `scripts/repro.sh` | The CI checks `fleet/tests` and `fleet/repro` |
| `.github/workflows/fleet.yml` | CI workflow |

## Conventions

- Business logic lives in the domain functions, not in the routes. They raise
  `NotFound`, `Conflict` or `Unauthorized` (`app/errors.py`), which `app.main` turns
  into JSON errors.
- SQL is always parameterized (`?`). Writes that touch several rows or tables run in
  one transaction (`with conn:`).
- Money is integer cents. Timestamps are stored with `db.timestamp()` (UTC, ISO 8601,
  seconds) and dates as `YYYY-MM-DD`.
- Tests go through the HTTP API where they can, using the `client`, `admin` and
  `library` fixtures; pure rules (like `fines.compute_fine`) also get direct unit
  tests.

## Engineering rules

Each rule has an ID, the rule, why it exists, and what enforces it today: `ci`,
`reviewer`, `lint` or `none-yet`. Cite rule IDs in reviews and PR descriptions.

### E-001 Tests assert work, not time

- **Rule:** no wall-clock thresholds (`elapsed < x`) and no sleep-based waits in
  tests. For performance, assert on the work done: the number of SQL statements
  (`sqlite3.Connection.set_trace_callback`), the query plan (`EXPLAIN QUERY PLAN`),
  rows touched. For time-dependent behavior, move the `FixedClock`.
- **Why:** timing checks pass on a quiet machine and fail on a busy one. Many agents
  share one machine and CI runners are noisy, so a timing assert becomes a flaky test
  that blocks unrelated work.
- **Enforced-by:** reviewer (lint: none-yet)

### E-002 Tests are isolated

- **Rule:** tests use temporary directories and a per-test SQLite file (the `db_path`,
  `app` and `client` fixtures). No fixed ports, no shared files, no network, no
  dependence on test order.
- **Why:** many agents run the suite at the same time on one machine; shared state
  makes their runs interfere with each other.
- **Enforced-by:** reviewer

### E-003 Bug fixes start with a failing test

- **Rule:** every bug fix adds or changes a `tests/**/test_*.py` test that fails on
  the base commit and passes at head. Write it first and watch it fail.
- **Why:** it proves the test can fail. A test that never failed may not exercise
  the bug at all.
- **Enforced-by:** ci (`fleet/repro`, on pull requests labelled `type:bug`)

### E-004 One test per acceptance criterion

- **Rule:** a feature gets at least one test per acceptance criterion in its issue,
  named after the criterion.
- **Why:** reviewers can check the spec line by line, and a missing case shows.
- **Enforced-by:** reviewer

### E-005 Checks are clean

- **Rule:** `ruff check`, `ruff format --check`, `mypy app` (strict) and `pytest`
  pass. Do not silence a check (`noqa`, `type: ignore`, `skip`, `xfail`) without a
  reason on the same line.
- **Why:** one red or silenced check hides the next real failure.
- **Enforced-by:** ci (`fleet/tests`)

### E-006 Time comes from the injected Clock

- **Rule:** business logic gets the time from the `Clock` it is given
  (`clock.now()`, `clock.today()`), never from `datetime.now()`, `date.today()` or
  `time.time()`.
- **Why:** due dates, fines and reports depend on "now". With an injected clock,
  tests can pin and move time and results are reproducible.
- **Enforced-by:** lint (ruff `TID251` bans the wall-clock APIs outside
  `app/clock.py`)

### E-007 Risky changes travel alone

- **Rule:** changes to dependencies (`pyproject.toml`, `requirements*.txt`), auth
  (`app/auth.py`), migrations (`app/migrations/`), CI (`.github/`, `scripts/`) or
  this file go in their own PR with nothing unrelated. They are tier T2 or higher: a
  human approves them at the head commit.
- **Why:** risk isolation. A reviewer can judge one risky change at a time, and a
  revert removes only that change.
- **Enforced-by:** reviewer

### E-008 One issue per PR, small diffs

- **Rule:** one issue per PR, and diffs under 400 changed lines. A bigger diff is T2.
- **Why:** small diffs get real reviews, merge cleanly and are easy to revert.
- **Enforced-by:** reviewer

### E-009 Docs follow behavior

- **Rule:** when behavior visible to API users changes, update README.md (API table,
  library rules, configuration) in the same PR.
- **Why:** the README is the spec that bug reports and reviews are checked against.
  Stale docs produce bogus bug reports and wrong fixes.
- **Enforced-by:** reviewer

### E-010 Ask instead of guessing

- **Rule:** if an issue is ambiguous (missing rules, conflicting requirements,
  unclear expected behavior), ask on the issue and stop. Do not invent business
  rules.
- **Why:** a confident wrong answer costs more than a question: it ships, people
  rely on it, and someone has to find and undo it.
- **Enforced-by:** reviewer

## Definition of done

A change is done when all of this holds at the PR's head commit:

1. The PR links its issue and states what changed, why, its risk tier and how it
   was verified.
2. A bug fix has a regression test that fails on the base and passes at head
   (`fleet/repro` PASS, E-003).
3. A feature has one test per acceptance criterion (E-004).
4. `fleet/tests` PASS at the head commit (E-005).
5. No sleeps, timing asserts or fixed ports in tests (E-001, E-002).
6. README.md is updated if behavior changed (E-009).
7. Mutation testing of the changed code leaves no unexplained survivors: each
   surviving mutant is killed by a new test or explained as equivalent.
8. The PR is approved at its head commit; T2 changes by a human.

When an issue cannot be done as written, say so: **blocked** (name what is
missing), **unsure** (ask the question, E-010) or **won't fix** (explain why). Any
of these is better than a confident wrong answer.
