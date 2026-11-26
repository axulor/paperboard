from fastapi import APIRouter
from pydantic import BaseModel

from app import VERSION

router = APIRouter()


class Health(BaseModel):
    status: str
    version: str


@router.get("/health")
async def health() -> Health:
    return Health(status="ok", version=VERSION)
