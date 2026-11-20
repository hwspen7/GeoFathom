"""Bounded topology preview and atomic linked-node updates."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import StorageError
from .topology import apply_shared_vertex, preview_shared_vertex

router=APIRouter(prefix="/projects",tags=["topology"])


class SharedMove(BaseModel):
    old: list[float] = Field(min_length=2,max_length=2)
    new: list[float] = Field(min_length=2,max_length=2)
    tolerance_m: float = Field(default=0.05,ge=0,le=2)
    expected_revisions: dict[str,int] = Field(default_factory=dict)


@router.post("/{project_id}/topology/preview")
def preview(project_id: str, body: SharedMove) -> dict:
    try: return preview_shared_vertex(project_id,body.old,body.new,body.tolerance_m)
    except StorageError as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


@router.post("/{project_id}/topology/move")
def move(project_id: str, body: SharedMove) -> dict:
    try:
        return apply_shared_vertex(project_id,body.old,body.new,
                                   body.expected_revisions,body.tolerance_m)
    except StorageError as error:
        message=str(error)
        raise HTTPException(status_code=409 if "locked" in message or "conflict" in message
                            else 422,detail=message) from error
