"""Safe GIS layer labeling, map symbols and free-form point annotations."""
from typing import Any

from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field

from .cartography import change_style
from .database import StorageError
from .workspace import add_in_layer, layers

router=APIRouter(prefix="/projects",tags=["cartography"])


class StylePatch(BaseModel):
    labels:dict[str,Any]|None=None
    symbol:dict[str,Any]|None=None
    expected_revision:int|None=Field(default=None,ge=0)


@router.patch("/{project_id}/layers/{layer_id}/style")
def patch_style(project_id:str,layer_id:str,body:StylePatch)->dict:
    try:
        changes=body.model_dump(exclude_unset=True,exclude_none=True,
                                exclude={"expected_revision"})
        return change_style(project_id,layer_id,changes,body.expected_revision)
    except StorageError as error:
        message=str(error)
        status=409 if "conflict" in message.lower() else 404 if "not found" in message.lower() else 422
        raise HTTPException(status_code=status,detail=message) from error


class MapNote(BaseModel):
    text:str=Field(min_length=1,max_length=120)
    position:tuple[float,float]
    layer_id:str|None=None


@router.post("/{project_id}/annotations",status_code=201)
def create_map_annotation(project_id:str,body:MapNote)->dict:
    text=body.text.strip()
    if not text or any(ord(ch)<32 and ch not in "\n\t" for ch in text):
        raise HTTPException(status_code=422,detail="Annotation requires printable text.")
    try:
        result=add_in_layer(project_id,[{
            "name":text[:80],
            "source":"User map annotation",
            "properties":{"annotation":True,"annotation_text":text},
            "geometry":{"type":"Point","coordinates":list(body.position)},
        }],body.layer_id)
        return result["results"][0]
    except StorageError as error:
        status=404 if "not found" in str(error).lower() else 409 if "locked" in str(error).lower() else 422
        raise HTTPException(status_code=status,detail=str(error)) from error
