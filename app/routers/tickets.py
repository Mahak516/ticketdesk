from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Response

from ..dependencies import get_ticket_service
from ..schemas import (
    CommentCreate,
    CommentOut,
    Status,
    TicketCreate,
    TicketDetail,
    TicketListItem,
    TicketOut,
    TicketPage,
    TicketUpdate,
)
from ..services import TicketService

router = APIRouter(prefix="/tickets", tags=["tickets"])

Service = Annotated[TicketService, Depends(get_ticket_service)]


@router.post("", response_model=TicketOut, status_code=201)
def create_ticket(data: TicketCreate, service: Service):
    return service.create(data)


@router.get("", response_model=TicketPage)
def list_tickets(
    service: Service,
    status: Optional[Status] = None,
    assignee_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    items, total = service.list_tickets(
        status=status, assignee_id=assignee_id, limit=limit, offset=offset
    )
    return TicketPage(
        items=[TicketListItem(**item) for item in items], total=total, limit=limit, offset=offset
    )


# Declared before "/{ticket_id}" so "stats" is not parsed as an id.
@router.get("/stats", response_model=dict[str, int])
def ticket_stats(service: Service):
    return service.stats()


@router.get("/{ticket_id}", response_model=TicketDetail)
def get_ticket(ticket_id: int, service: Service):
    return service.get(ticket_id, with_comments=True)


@router.patch("/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: int, data: TicketUpdate, service: Service):
    return service.update(ticket_id, data)


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: int, service: Service):
    service.delete(ticket_id)
    return Response(status_code=204)


@router.post("/{ticket_id}/comments", response_model=CommentOut, status_code=201)
def add_comment(ticket_id: int, data: CommentCreate, service: Service):
    return service.add_comment(ticket_id, data)
