"""Validated geometric measurement HTTP endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .measure import GeometryError, measure_geometry
from .topology import bbox_overlaps, contains_point, native_available

router = APIRouter(tags=["geometry"])


class MeasureRequest(BaseModel):
    geometry: dict[str, Any]


@router.post("/measure")
def measure(body: MeasureRequest) -> dict:
    try:
        return measure_geometry(body.geometry)
    except GeometryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


class ContainsRequest(BaseModel):
    geometry: dict[str, Any]
    longitude: float
    latitude: float


class BoundsRequest(BaseModel):
    first: list[float]
    second: list[float]


@router.post("/spatial/contains")
def contains(body: ContainsRequest) -> dict:
    try:
        inside = contains_point(body.geometry, body.longitude, body.latitude)
        simple = (
            body.geometry.get("type") == "Polygon"
            and len(body.geometry.get("coordinates", [])) == 1
        )
        return {
            "inside": inside,
            "method": "native-cpp" if native_available() and simple else "shapely",
            "boundary_included": False,
        }
    except GeometryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/spatial/bbox-overlap")
def bbox_overlap(body: BoundsRequest) -> dict:
    try:
        return {
            "overlaps": bbox_overlaps(body.first, body.second),
            "method": "native-cpp" if native_available() else "python",
        }
    except GeometryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
