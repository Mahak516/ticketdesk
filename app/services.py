"""Business logic. Routers stay thin; everything that touches the database lives here."""

from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from .decorators import timed
from .exceptions import DuplicateError, InvalidTransitionError, NotFoundError
from .models import Comment, Ticket, User
from .schemas import CommentCreate, TicketCreate, TicketUpdate, UserCreate

# The ticket lifecycle as a small state machine: status -> statuses it may move to.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"in_progress", "closed"}),
    "in_progress": frozenset({"open", "resolved"}),
    "resolved": frozenset({"in_progress", "closed"}),
    "closed": frozenset(),
}


class UserService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, data: UserCreate) -> User:
        email = data.email.lower()
        if self.db.scalar(select(User.id).where(User.email == email)) is not None:
            raise DuplicateError(f"A user with email '{email}' already exists")
        user = User(name=data.name, email=email)
        self.db.add(user)
        try:
            self.db.commit()
        except IntegrityError:
            # Two requests raced past the check above; the unique constraint caught it.
            self.db.rollback()
            raise DuplicateError(f"A user with email '{email}' already exists") from None
        self.db.refresh(user)
        return user

    def get(self, user_id: int) -> User:
        user = self.db.get(User, user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return user


class TicketService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserService(db)

    # --- create / read ---------------------------------------------------------

    def create(self, data: TicketCreate) -> Ticket:
        if data.assignee_id is not None:
            self.users.get(data.assignee_id)  # raises NotFoundError if missing
        ticket = Ticket(
            title=data.title,
            description=data.description,
            priority=data.priority,
            assignee_id=data.assignee_id,
        )
        self.db.add(ticket)
        self.db.commit()
        self.db.refresh(ticket)
        return ticket

    def get(self, ticket_id: int, with_comments: bool = False) -> Ticket:
        stmt = select(Ticket).where(Ticket.id == ticket_id)
        if with_comments:
            # One extra query for all comments, instead of one per access.
            stmt = stmt.options(selectinload(Ticket.comments)).execution_options(
                populate_existing=True
            )
        ticket = self.db.scalars(stmt).first()
        if ticket is None:
            raise NotFoundError(f"Ticket {ticket_id} not found")
        return ticket

    @timed()
    def list_tickets(
        self,
        *,
        status: Optional[str] = None,
        assignee_id: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one page of tickets plus the total match count, in exactly 2 queries.

        The assignee is fetched with a JOIN and the comment count with a correlated
        subquery, so the number of queries does not grow with the page size (no N+1).
        """
        filters = []
        if status is not None:
            filters.append(Ticket.status == status)
        if assignee_id is not None:
            filters.append(Ticket.assignee_id == assignee_id)

        comment_count = (
            select(func.count(Comment.id))
            .where(Comment.ticket_id == Ticket.id)
            .correlate(Ticket)
            .scalar_subquery()
        )
        stmt = (
            select(Ticket, comment_count.label("comment_count"))
            .options(joinedload(Ticket.assignee))
            .where(*filters)
            .order_by(Ticket.created_at.desc(), Ticket.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = self.db.execute(stmt).all()
        total = self.db.scalar(select(func.count()).select_from(Ticket).where(*filters)) or 0

        items = [
            {
                "id": ticket.id,
                "title": ticket.title,
                "status": ticket.status,
                "priority": ticket.priority,
                "assignee_name": ticket.assignee.name if ticket.assignee else None,
                "comment_count": count,
                "created_at": ticket.created_at,
            }
            for ticket, count in rows
        ]
        return items, total

    def stats(self) -> dict[str, int]:
        """Ticket count per status, including statuses that currently have none."""
        counts = {status: 0 for status in ALLOWED_TRANSITIONS}
        rows = self.db.execute(select(Ticket.status, func.count()).group_by(Ticket.status)).all()
        counts.update({status: n for status, n in rows})
        return counts

    # --- update / delete -------------------------------------------------------

    @staticmethod
    def _check_transition(current: str, new: str) -> None:
        allowed = ALLOWED_TRANSITIONS[current]
        if new not in allowed:
            options = ", ".join(sorted(allowed)) or "none"
            raise InvalidTransitionError(
                f"Cannot move a ticket from '{current}' to '{new}'. Allowed: {options}"
            )

    def update(self, ticket_id: int, data: TicketUpdate) -> Ticket:
        ticket = self.get(ticket_id)
        changes = data.model_dump(exclude_unset=True)

        # Validate everything first so a failed request changes nothing.
        new_status = changes.get("status")
        if new_status is not None and new_status != ticket.status:
            self._check_transition(ticket.status, new_status)
        if changes.get("assignee_id") is not None:
            self.users.get(changes["assignee_id"])

        if new_status is not None:
            ticket.status = new_status
        if "assignee_id" in changes:  # an explicit null un-assigns the ticket
            ticket.assignee_id = changes["assignee_id"]
        for field in ("title", "description", "priority"):
            if changes.get(field) is not None:
                setattr(ticket, field, changes[field])

        self.db.commit()
        self.db.refresh(ticket)
        return ticket

    def delete(self, ticket_id: int) -> None:
        ticket = self.get(ticket_id)
        self.db.delete(ticket)  # comments go with it (cascade)
        self.db.commit()

    # --- comments --------------------------------------------------------------

    def add_comment(self, ticket_id: int, data: CommentCreate) -> Comment:
        self.get(ticket_id)
        self.users.get(data.author_id)
        comment = Comment(ticket_id=ticket_id, author_id=data.author_id, body=data.body)
        self.db.add(comment)
        self.db.commit()
        self.db.refresh(comment)
        return comment
