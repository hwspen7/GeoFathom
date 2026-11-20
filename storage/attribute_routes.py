"""Project attribute querying and safe batch editing."""

from typing import Any, Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .attributes import query_attributes, update_properties
from .database import StorageError

router=APIRouter(prefix="/projects",tags=["attributes"])


class SearchAttributes(BaseModel):
    field: str | None = None
    operator: Literal["contains","equals","gte","lte","exists"] = "contains"
    value: Any = None
    limit: int = Field(default=100,ge=1,le=200)
    offset: int = Field(default=0,ge=0,le=10000)


class PropertyUpdate(BaseModel):
    id: str
    expected_revision: int = Field(ge=0)
    properties: dict[str,Any]


class UpdateProperties(BaseModel):
    updates: list[PropertyUpdate] = Field(min_length=1,max_length=100)


@router.post("/{project_id}/attributes/query")
def query(project_id:str,body:SearchAttributes)->dict:
    try:
        return query_attributes(project_id,body.field,body.operator,body.value,body.limit,body.offset)
    except StorageError as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


@router.patch("/{project_id}/attributes/batch")
def bulk(project_id:str,body:UpdateProperties)->dict:
    try:
        return update_properties(project_id,[entry.model_dump() for entry in body.updates])
    except StorageError as error:
        raise HTTPException(status_code=409 if "locked" in str(error).lower()
                            or "conflict" in str(error).lower() else 422,
                            detail=str(error)) from error
