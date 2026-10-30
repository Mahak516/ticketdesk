# TicketDesk API

A support-ticket REST API built with **Python 3, FastAPI, SQLAlchemy and PostgreSQL**. Users file
tickets, assign them, comment on them and move them through a validated status workflow.

The project is small on purpose. It focuses on the things a backend service has to get right:
clean layering, a real relational schema, input validation, tests, a measured query optimisation
and a CI pipeline.

## Stack

| Concern | Choice |
|---|---|
| Language | Python 3.10+ |
| Web framework | FastAPI (auto-generated docs at `/docs`) |
| Database / ORM | PostgreSQL 16, SQLAlchemy 2.0 |
| Validation | Pydantic v2 |
| Tests | pytest (SQLite by default, PostgreSQL in CI) |
| Packaging / CI | Docker, docker-compose, GitHub Actions |

## Run it

With Docker (PostgreSQL + API):

```bash
docker compose up --build
# API:  http://localhost:8000      Docs: http://localhost:8000/docs
```

Without Docker (needs a PostgreSQL you can reach):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg2://ticketdesk:ticketdesk@localhost:5432/ticketdesk
uvicorn app.main:app --reload
```

## API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/users` | Create a user (email must be unique, case-insensitive) |
| `GET` | `/users/{id}` | Fetch a user |
| `POST` | `/tickets` | Create a ticket |
| `GET` | `/tickets` | List tickets: `status`, `assignee_id`, `limit` (1-100), `offset` |
| `GET` | `/tickets/stats` | Ticket count per status |
| `GET` | `/tickets/{id}` | Fetch a ticket with its comments |
| `PATCH` | `/tickets/{id}` | Partial update; `"assignee_id": null` un-assigns |
| `DELETE` | `/tickets/{id}` | Delete a ticket and its comments |
| `POST` | `/tickets/{id}/comments` | Add a comment |
| `GET` | `/health` | Liveness plus a database round trip |

Errors share one shape, `{"error": "<code>", "detail": "<message>"}`, with these codes:
`not_found` (404), `duplicate` (409), `invalid_transition` (409). Validation problems return the
standard FastAPI 422 body.

## Design notes

**Layering.** Routers only translate HTTP; all logic and database access live in `app/services.py`
(`UserService`, `TicketService`). Services raise domain exceptions (`app/exceptions.py`) and one
handler in `app/main.py` turns them into JSON, so the business logic never imports HTTP code.

**Status workflow.** The lifecycle is a dictionary of allowed moves (`ALLOWED_TRANSITIONS`):

```
open -> in_progress | closed
in_progress -> open | resolved
resolved -> in_progress | closed
closed -> (terminal)
```

Invalid moves return `409 invalid_transition` and change nothing; `PATCH` validates every field
before it writes any of them.

**Avoiding N+1 queries.** Listing tickets needs the assignee's name and a comment count for each
row. Loading those lazily costs one or two extra queries per ticket. `TicketService.list_tickets`
fetches the assignee with a `JOIN` and the count with a correlated subquery, so a page always costs
exactly **2 queries** (the page and the total), whatever its size. `tests/test_services.py` asserts
this with a SQLAlchemy query counter, and `scripts/benchmark.py` measures it.

**Indexes.** `ix_tickets_status_created (status, created_at)` serves "tickets with this status,
newest first". Foreign keys used in filters and joins (`tickets.assignee_id`, `comments.ticket_id`)
are indexed.

**Decorators (`app/decorators.py`).**
- `@timed()` logs how long a call took and warns when it exceeds `SLOW_CALL_MS` (default 200). It is
  applied to the list query so slow requests show up in the logs.
- `@retry(times, delay, exceptions)` re-runs a call on the listed exceptions. `init_db` uses it, so the
  API waits for PostgreSQL to come up instead of crashing on start.

**Configuration** is read from environment variables: `DATABASE_URL`, `SLOW_CALL_MS`, `CORS_ORIGINS`
(comma-separated, defaults to the usual React dev-server origins).

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                   # in-memory SQLite, no setup

# the same suite against PostgreSQL (this is what CI runs):
TEST_DATABASE_URL=postgresql+psycopg2://ticketdesk:ticketdesk@localhost:5432/ticketdesk pytest
```

The suite covers the full HTTP surface (validation, 404/409 paths, pagination, filters, cascade
delete), the status state machine, the 2-query guarantee, and both decorators.

## Benchmark: N+1 vs optimised

```bash
# Uses a scratch database: --reset drops and recreates its tables.
python -m scripts.benchmark --db-url postgresql+psycopg2://ticketdesk:ticketdesk@localhost:5432/ticketdesk --reset
```

It seeds 5,000 tickets (3 comments each), lists one page of 100, and compares the lazy-loading
version with the service query. Record your own run here:

| Approach | Queries per page | Median time |
|---|---|---|
| Naive (lazy loading) | _run the script_ | _run the script_ |
| Optimised (`list_tickets`) | _run the script_ | _run the script_ |

## Project layout

```
app/
  main.py          app, CORS, error handler, /health
  config.py        settings from environment variables
  database.py      engine, session dependency, init_db
  models.py        User, Ticket, Comment (+ indexes)
  schemas.py       Pydantic request/response models
  services.py      business logic and queries
  exceptions.py    domain errors
  decorators.py    timed, retry
  routers/         users.py, tickets.py
tests/             API, service and decorator tests
scripts/benchmark.py
```

## Contributing workflow

Work happens on short-lived branches and lands through pull requests. CI (GitHub Actions) runs the
test suite against a real PostgreSQL service on every push and pull request; require it to pass
before merging.
