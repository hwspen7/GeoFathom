"""Validated geometric measurement HTTP endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .measure import GeometryError, measure_geometry

router = APIRouter(tags=["geometry"])


class MeasureRequest(BaseModel):
    geometry: dict[str, Any]


@router.post("/measure")
def measure(body: MeasureRequest) -> dict:
    try:
        return measure_geometry(body.geometry)
    except GeometryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
