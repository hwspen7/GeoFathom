"""Feature editing and constructive geometry operations for FastAPI."""

from typing import Any, Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .editing import construct, validate, snap, simplify, polygon_split, polygon_hole, move
from .tracing import trace_along
from .measure import GeometryError

router = APIRouter(prefix="/edit", tags=["geometry-editor"])


class GeometryBody(BaseModel):
    geometry: dict[str, Any]


class ConstructBody(BaseModel):
    mode: Literal["polygon","rectangle","circle","bearing"]
    vertices: list[list[float]] = Field(min_length=1,max_length=4001)
    radius_m: float | None = None
    bearing_deg: float | None = None
    length_m: float | None = None
    segments: int = 72


class SnapBody(BaseModel):
    coordinate: list[float]
    paths: list[list[list[float]]] = Field(default_factory=list, max_length=100)
    tolerance_m: float = Field(ge=0,le=500)


class SimplifyBody(BaseModel):
    vertices: list[list[float]] = Field(min_length=2,max_length=20000)
    tolerance_m: float = Field(ge=0,le=500)


class PairBody(BaseModel):
    polygon: dict[str, Any]
    other: dict[str, Any]


class MoveBody(BaseModel):
    geometry: dict[str, Any]
    bearing_deg: float
    distance_m: float = Field(ge=0,le=100000)


def checked(call):
    try: return call()
    except GeometryError as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


@router.post("/validate")
def validate_geometry(body: GeometryBody) -> dict:
    return validate(body.geometry)


@router.post("/construct")
def construct_geometry(body: ConstructBody) -> dict:
    return checked(lambda: construct(body.mode,body.vertices,body.radius_m,body.bearing_deg,
                                     body.length_m,body.segments))


@router.post("/snap")
def snap_geometry(body: SnapBody) -> dict:
    return checked(lambda: snap(body.coordinate,body.paths,body.tolerance_m))


@router.post("/simplify")
def simplify_geometry(body: SimplifyBody) -> dict:
    return checked(lambda: simplify(body.vertices,body.tolerance_m))


@router.post("/split")
def split_geometry(body: PairBody) -> dict:
    return checked(lambda: polygon_split(body.polygon,body.other))


@router.post("/hole")
def hole_geometry(body: PairBody) -> dict:
    return checked(lambda: polygon_hole(body.polygon,body.other))


@router.post("/move")
def move_geometry(body: MoveBody) -> dict:
    return checked(lambda: move(body.geometry,body.bearing_deg,body.distance_m))



class TraceBody(BaseModel):
    start: list[float] = Field(min_length=2,max_length=2)
    end: list[float] = Field(min_length=2,max_length=2)
    paths: list[list[list[float]]] = Field(min_length=1,max_length=300)
    tolerance_m: float = Field(default=30,gt=0,le=200)


@router.post("/trace")
def trace_existing_network(body:TraceBody)->dict:
    return checked(lambda: trace_along(body.start,body.end,body.paths,body.tolerance_m))


class PolygonizeBody(BaseModel):
    """Each source is a GeoJSON line, polygon boundary or point reference."""
    geometries: list[dict[str, Any]] = Field(min_length=1,max_length=300)
    tolerance_m: float = Field(default=1.0,ge=0,le=20)
    minimum_area_m2: float = Field(default=0.01,ge=0,le=1e10)
    max_faces: int = Field(default=300,ge=1,le=500)
    exclude_existing: bool = False
    existing_areas: list[dict[str, Any]] = Field(default_factory=list,max_length=500)


@router.post("/polygonize")
def polygonize_line_network(body:PolygonizeBody)->dict:
    """Node intersections, derive closed faces and measure each on WGS84."""
    from .polygonize import polygonize_network
    return checked(lambda: polygonize_network(
        body.geometries,body.tolerance_m,body.minimum_area_m2,body.max_faces,
        body.exclude_existing,body.existing_areas))
