"""FastAPI endpoints for spatial buffers, overlay and comparison."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from geometry.measure import GeometryError
from .operations import (
    buffer_geometry, compare_areas, distance_between_points, overlay_geometries,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])


class BufferRequest(BaseModel):
    geometry: dict[str, Any]
    distance_m: float = Field(gt=0, le=100_000)
    resolution: int = Field(default=16, ge=4, le=64)


class OverlayRequest(BaseModel):
    left: dict[str, Any]
    right: dict[str, Any]
    operation: Literal["intersection", "union", "difference"]


class PairRequest(BaseModel):
    left: dict[str, Any]
    right: dict[str, Any]


class DistanceRequest(BaseModel):
    first: tuple[float, float]
    second: tuple[float, float]


@router.post("/buffer")
def buffer(body: BufferRequest) -> dict:
    try:
        return buffer_geometry(body.geometry, body.distance_m, body.resolution)
    except GeometryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/overlay")
def overlay(body: OverlayRequest) -> dict:
    try:
        return overlay_geometries(body.left, body.right, body.operation)
    except GeometryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/compare")
def compare(body: PairRequest) -> dict:
    try:
        return compare_areas(body.left, body.right)
    except GeometryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/distance")
def distance(body: DistanceRequest) -> dict:
    try:
        return distance_between_points(list(body.first), list(body.second))
    except GeometryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
