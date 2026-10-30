"""Pydantic request and response models."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Status = Literal["open", "in_progress", "resolved", "closed"]
Priority = Literal["low", "medium", "high"]


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    created_at: datetime


class TicketCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    priority: Priority = "medium"
    assignee_id: Optional[int] = None


class TicketUpdate(BaseModel):
    """Partial update. Fields that are not sent are left unchanged.

    Sending ``"assignee_id": null`` un-assigns the ticket.
    """

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    priority: Optional[Priority] = None
    status: Optional[Status] = None
    assignee_id: Optional[int] = None


class CommentCreate(BaseModel):
    author_id: int
    body: str = Field(min_length=1, max_length=2000)


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    author_id: int
    body: str
    created_at: datetime


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    status: Status
    priority: Priority
    assignee_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class TicketDetail(TicketOut):
    comments: list[CommentOut]


class TicketListItem(BaseModel):
    id: int
    title: str
    status: Status
    priority: Priority
    assignee_name: Optional[str]
    comment_count: int
    created_at: datetime


class TicketPage(BaseModel):
    items: list[TicketListItem]
    total: int
    limit: int
    offset: int
