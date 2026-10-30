"""Compare a naive N+1 ticket list with the optimised service query.

Run from the project root against a scratch database:

    python -m scripts.benchmark --db-url postgresql+psycopg2://ticketdesk:ticketdesk@localhost:5432/ticketdesk --reset

WARNING: --reset DROPS AND RECREATES every table in that database. Never point it at data you
care about. On PostgreSQL the script also prints the query plan for the status filter.
"""

import argparse
import statistics
import time

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.database import Base
from app.models import Comment, Ticket, User
from app.services import TicketService

STATUSES = ["open", "in_progress", "resolved", "closed"]


def seed(session, n_tickets: int, n_users: int = 50, comments_per_ticket: int = 3) -> None:
    users = [User(name=f"User {i}", email=f"user{i}@example.com") for i in range(n_users)]
    session.add_all(users)
    session.flush()

    for start in range(0, n_tickets, 1000):
        batch = []
        for i in range(start, min(start + 1000, n_tickets)):
            ticket = Ticket(
                title=f"Ticket {i}",
                status=STATUSES[i % len(STATUSES)],
                assignee_id=users[i % n_users].id,
            )
            ticket.comments = [
                Comment(author_id=users[(i + j) % n_users].id, body=f"Comment {j}")
                for j in range(comments_per_ticket)
            ]
            batch.append(ticket)
        session.add_all(batch)
        session.flush()
    session.commit()


def list_naive(session, limit: int) -> list[dict]:
    """What a first draft often looks like: relations are lazy-loaded row by row (N+1)."""
    tickets = session.scalars(
        select(Ticket).order_by(Ticket.created_at.desc(), Ticket.id.desc()).limit(limit)
    ).all()
    return [
        {
            "id": t.id,
            "assignee_name": t.assignee.name if t.assignee else None,
            "comment_count": len(t.comments),
        }
        for t in tickets
    ]


def list_optimised(session, limit: int):
    return TicketService(session).list_tickets(limit=limit)


def measure(engine, factory, fn, limit: int, runs: int) -> tuple[int, float]:
    """Return (queries per run, median milliseconds). A fresh session per run avoids cache effects."""
    counter = {"n": 0}

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    timings = []
    try:
        for _ in range(runs):
            with factory() as session:
                start = time.perf_counter()
                fn(session, limit)
                timings.append((time.perf_counter() - start) * 1000)
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return counter["n"] // runs, statistics.median(timings)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--db-url", required=True)
    parser.add_argument("--tickets", type=int, default=5000)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--reset", action="store_true", help="drop and recreate all tables first (required)")
    args = parser.parse_args()

    if not args.reset:
        raise SystemExit("Refusing to run without --reset: it drops all tables in the target database.")

    engine = create_engine(args.db_url)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with factory() as session:
        seed(session, args.tickets)
    print(f"Seeded {args.tickets} tickets (3 comments each) on {engine.dialect.name}.")
    print(f"Listing one page of {args.page_size} tickets, median of {args.runs} runs:\n")

    naive_q, naive_ms = measure(engine, factory, list_naive, args.page_size, args.runs)
    fast_q, fast_ms = measure(engine, factory, list_optimised, args.page_size, args.runs)

    print(f"{'approach':<28}{'queries':>10}{'median ms':>14}")
    print(f"{'naive (lazy loading, N+1)':<28}{naive_q:>10}{naive_ms:>14.1f}")
    print(f"{'optimised (JOIN + subquery)':<28}{fast_q:>10}{fast_ms:>14.1f}")
    print(f"\nQueries: {naive_q} -> {fast_q}.  Time: {naive_ms:.1f} ms -> {fast_ms:.1f} ms "
          f"({naive_ms / fast_ms:.1f}x faster).")

    if engine.dialect.name == "postgresql":
        print("\nQuery plan for: open tickets, newest first (uses ix_tickets_status_created):")
        with engine.connect() as conn:
            plan = conn.execute(
                text(
                    "EXPLAIN ANALYZE SELECT id, title FROM tickets WHERE status = 'open' "
                    "ORDER BY created_at DESC, id DESC LIMIT 20"
                )
            )
            for (line,) in plan:
                print("  " + line)


if __name__ == "__main__":
    main()
