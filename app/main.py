"""FastAPI application entry point: `uvicorn app.main:app`."""

import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db, init_db
from .exceptions import AppError
from .routers import tickets, users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ticketdesk")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="TicketDesk API",
    version="1.0.0",
    description="A small support-ticket REST API: FastAPI, SQLAlchemy and PostgreSQL.",
    lifespan=lifespan,
)

# Lets a browser front end (React dev servers by default) call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(tickets.router)


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    """Turn domain errors into a consistent JSON body: {"error": ..., "detail": ...}."""
    return JSONResponse(
        status_code=exc.status_code, content={"error": exc.code, "detail": exc.detail}
    )


@app.get("/health", tags=["meta"])
def health(db: Annotated[Session, Depends(get_db)]):
    """Liveness plus a real database round trip, for load balancers and debugging."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("database health check failed")
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "down"})
    return {"status": "ok", "database": "up"}
