"""FastAPI access to GIS layers, revision history and version-aware edits."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import StorageError
from .workspace import (
    add_layer, copy_feature, edit_layer, feature_history, layers,
    remove_layer, restore_version, update_feature, workspace,
)

router = APIRouter(prefix="/projects", tags=["layer-editor"])


def error_response(error):
    message = str(error)
    if "not found" in message.lower():
        status = 404
    elif "conflict" in message.lower() or "locked" in message.lower():
        status = 409
    else:
        status = 422
    return HTTPException(status_code=status, detail=message)


class NewLayer(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    color: str = "#2563eb"


class UpdateLayer(BaseModel):
    name: str | None = None
    color: str | None = None
    visible: bool | None = None
    locked: bool | None = None
    z_index: int | None = None


class UpdateFeature(BaseModel):
    geometry: dict[str, Any] | None = None
    name: str | None = None
    properties: dict[str, Any] | None = None
    layer_id: str | None = None
    expected_revision: int | None = Field(default=None,ge=0)


@router.get("/{project_id}/workspace")
def get_workspace(project_id: str) -> dict:
    try: return workspace(project_id)
    except StorageError as error: raise error_response(error) from error


@router.get("/{project_id}/layers")
def get_layers(project_id: str) -> list[dict]:
    try: return layers(project_id)
    except StorageError as error: raise error_response(error) from error


@router.post("/{project_id}/layers",status_code=201)
def create_layer(project_id: str, body: NewLayer) -> dict:
    try: return add_layer(project_id,body.name,body.color)
    except StorageError as error: raise error_response(error) from error


@router.patch("/{project_id}/layers/{layer_id}")
def patch_layer(project_id: str, layer_id: str, body: UpdateLayer) -> dict:
    try:
        updates=body.model_dump(exclude_unset=True,exclude_none=True)
        return edit_layer(project_id,layer_id,updates)
    except StorageError as error: raise error_response(error) from error


@router.delete("/{project_id}/layers/{layer_id}",status_code=204)
def delete_layer(project_id: str,layer_id: str) -> None:
    try: remove_layer(project_id,layer_id)
    except StorageError as error: raise error_response(error) from error


@router.patch("/{project_id}/features/{feature_id}")
def patch_feature(project_id: str, feature_id: str, body: UpdateFeature) -> dict:
    try: return update_feature(project_id,feature_id,**body.model_dump(exclude_unset=True))
    except StorageError as error: raise error_response(error) from error


@router.get("/{project_id}/features/{feature_id}/history")
def history(project_id: str,feature_id: str) -> dict:
    try: return feature_history(project_id,feature_id)
    except StorageError as error: raise error_response(error) from error


@router.post("/{project_id}/features/{feature_id}/restore/{revision}")
def restore(project_id: str,feature_id: str,revision: int) -> dict:
    try: return restore_version(project_id,feature_id,revision)
    except StorageError as error: raise error_response(error) from error


@router.post("/{project_id}/features/{feature_id}/copy",status_code=201)
def copy(project_id: str,feature_id: str) -> dict:
    try: return copy_feature(project_id,feature_id)
    except StorageError as error: raise error_response(error) from error
