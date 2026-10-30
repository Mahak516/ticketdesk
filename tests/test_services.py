"""Service-layer tests: the state machine and the query-count guarantee."""

from contextlib import contextmanager
from typing import get_args

from sqlalchemy import event, select

from app.models import Ticket
from app.schemas import CommentCreate, Status, TicketCreate, UserCreate
from app.services import ALLOWED_TRANSITIONS, TicketService, UserService


@contextmanager
def count_queries(engine):
    """Count SQL statements sent to the database while the block runs."""
    counter = {"n": 0}

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


def seed(db, n_tickets, comments_each):
    users = UserService(db)
    tickets = TicketService(db)
    user = users.create(UserCreate(name="Asha", email="asha@example.com"))
    for i in range(n_tickets):
        ticket = tickets.create(TicketCreate(title=f"T{i}", assignee_id=user.id))
        for j in range(comments_each):
            tickets.add_comment(ticket.id, CommentCreate(author_id=user.id, body=f"c{j}"))


def test_transition_table_is_consistent_with_the_status_type():
    statuses = set(get_args(Status))
    assert set(ALLOWED_TRANSITIONS) == statuses
    for targets in ALLOWED_TRANSITIONS.values():
        assert targets <= statuses
    assert ALLOWED_TRANSITIONS["closed"] == frozenset()  # closed is terminal


def test_list_uses_two_queries_regardless_of_page_size(db, engine):
    seed(db, n_tickets=25, comments_each=2)
    service = TicketService(db)

    with count_queries(engine) as small:
        items, total = service.list_tickets(limit=5)
    with count_queries(engine) as large:
        items_large, _ = service.list_tickets(limit=25)

    assert (len(items), total, len(items_large)) == (5, 25, 25)
    assert small["n"] == 2  # one page query + one count query
    assert large["n"] == 2  # same, with five times as many rows


def test_naive_loading_would_be_n_plus_one(db, engine):
    """The pattern the service avoids: lazy-loading relations row by row."""
    seed(db, n_tickets=25, comments_each=2)
    db.expunge_all()

    with count_queries(engine) as counter:
        tickets = db.scalars(select(Ticket).limit(25)).all()
        for ticket in tickets:
            _ = ticket.assignee
            _ = len(ticket.comments)

    assert counter["n"] > 25
