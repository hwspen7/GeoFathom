"""Persistent projects and GeoJSON feature collections for FastAPI."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .database import (
    StorageError, add_features, create_project, delete_feature, delete_project,
    export_project, get_project, list_features, list_projects,
)

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=1000)


class FeatureCreate(BaseModel):
    name: str = Field(default="Untitled feature", max_length=200)
    geometry: dict[str, Any]
    properties: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="User supplied", max_length=200)


class ImportRequest(BaseModel):
    type: str
    features: list[dict[str, Any]] = Field(min_length=1, max_length=100)


def _missing(error: StorageError) -> HTTPException:
    return HTTPException(
        status_code=404 if "not found" in str(error).lower() else 422,
        detail=str(error),
    )


@router.post("", status_code=201)
def create(body: ProjectCreate) -> dict:
    return create_project(body.name, body.description)


@router.get("")
def all_projects(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)) -> dict:
    return list_projects(limit, offset)


@router.get("/{project_id}")
def one_project(project_id: str) -> dict:
    try:
        return get_project(project_id)
    except StorageError as error:
        raise _missing(error) from error


@router.delete("/{project_id}", status_code=204)
def remove_project(project_id: str) -> None:
    try:
        delete_project(project_id)
    except StorageError as error:
        raise _missing(error) from error


@router.post("/{project_id}/features", status_code=201)
def create_feature(project_id: str, body: FeatureCreate) -> dict:
    try:
        return add_features(project_id, [body.model_dump()])["results"][0]
    except StorageError as error:
        raise _missing(error) from error


@router.post("/{project_id}/import", status_code=201)
def import_geojson(project_id: str, body: ImportRequest) -> dict:
    if body.type != "FeatureCollection":
        raise HTTPException(status_code=422, detail="Expected a GeoJSON FeatureCollection.")
    incoming = []
    for item in body.features:
        if item.get("type") != "Feature":
            raise HTTPException(status_code=422, detail="Every item must be a GeoJSON Feature.")
        properties = item.get("properties") or {}
        if not isinstance(properties, dict):
            raise HTTPException(status_code=422, detail="Feature properties must be objects.")
        incoming.append({
            "geometry": item.get("geometry"),
            "name": str(properties.get("name") or "Imported feature")[:200],
            "source": str(properties.get("source") or "Imported GeoJSON")[:200],
            "properties": properties,
        })
    try:
        return add_features(project_id, incoming)
    except StorageError as error:
        raise _missing(error) from error


@router.get("/{project_id}/features")
def features(project_id: str, limit: int = Query(200, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    try:
        return list_features(project_id, limit, offset)
    except StorageError as error:
        raise _missing(error) from error


@router.delete("/{project_id}/features/{feature_id}", status_code=204)
def remove_feature(project_id: str, feature_id: str) -> None:
    try:
        delete_feature(project_id, feature_id)
    except StorageError as error:
        raise _missing(error) from error


@router.get("/{project_id}/export")
def download_geojson(project_id: str) -> dict:
    try:
        return export_project(project_id)
    except StorageError as error:
        raise _missing(error) from error
