from typing import Annotated

from fastapi import APIRouter, Depends

from ..dependencies import get_user_service
from ..schemas import UserCreate, UserOut
from ..services import UserService

router = APIRouter(prefix="/users", tags=["users"])

Service = Annotated[UserService, Depends(get_user_service)]


@router.post("", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, service: Service):
    return service.create(data)


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, service: Service):
    return service.get(user_id)
