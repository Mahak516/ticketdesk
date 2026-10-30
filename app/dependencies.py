"""FastAPI dependencies that build services from the request's database session."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from .database import get_db
from .services import TicketService, UserService


def get_ticket_service(db: Annotated[Session, Depends(get_db)]) -> TicketService:
    return TicketService(db)


def get_user_service(db: Annotated[Session, Depends(get_db)]) -> UserService:
    return UserService(db)
