"""Preview GIS choropleth classification without persisting unsafe expressions."""
from typing import Literal
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from storage.database import StorageError
from .classification import classify
router=APIRouter(prefix="/analysis",tags=["symbology"])

class ClassificationRequest(BaseModel):
    values:list[float]=Field(min_length=2,max_length=10000)
    classes:int=Field(default=5,ge=2,le=9)
    method:Literal["equal_interval","quantile","jenks"]="quantile"

@router.post("/classify")
def classify_values(body:ClassificationRequest)->dict:
    try:return classify(body.values,body.classes,body.method)
    except StorageError as error:raise HTTPException(status_code=422,detail=str(error)) from error



class SavedGraduatedStyle(BaseModel):
    field:str=Field(min_length=1,max_length=64)
    classes:int=Field(default=5,ge=2,le=9)
    method:Literal["equal_interval","quantile","jenks"]="quantile"
    colors:list[str]|None=Field(default=None,max_length=9)
    layer_id:str
    expected_revision:int|None=Field(default=None,ge=0)

# Project-specific grading is included in the same /projects router as its
# existing layer editor; the API path intentionally avoids /analysis prefixes.
from fastapi import APIRouter as _Router
from storage.database import _connect,_required_project
from storage.workspace import _layer,_schema
from storage.cartography import change_style

project_router=_Router(prefix="/projects",tags=["symbology"])


@project_router.post("/{project_id}/symbology/graduated")
def graduate_project_layer(project_id:str,body:SavedGraduatedStyle)->dict:
    try:
        with _connect() as c:
            _required_project(c,project_id)
            _schema(c)
            _layer(c,project_id,body.layer_id)
            rows=c.execute("""SELECT f.name,f.source,f.properties
                FROM features f LEFT JOIN geo_layer_members m ON m.feature_id=f.id
                WHERE f.project_id=? AND
                  COALESCE(m.layer_id,(
                    SELECT id FROM geo_layers WHERE project_id=f.project_id
                    ORDER BY created_at,id LIMIT 1))=?
                ORDER BY f.created_at,f.id LIMIT 10001""",
                (project_id,body.layer_id)).fetchall()
        if len(rows)>10000:
            raise StorageError("Graduated classification supports at most 10,000 features per layer.")
        import json
        values=[]
        for row in rows:
            props=json.loads(row["properties"])
            raw=(row["name"] if body.field=="name" else
                 row["source"] if body.field=="source" else props.get(body.field))
            try:
                if isinstance(raw,bool) or raw is None:continue
                number=float(raw)
                import math
                if math.isfinite(number):values.append(number)
            except (TypeError,ValueError):pass
        result=classify(values,body.classes,body.method)
        palette=body.colors or [
            "#f7fbff","#c6dbef","#9ecae1","#6baed6","#4292c6",
            "#2171b5","#08519c","#08306b","#041e42",
        ]
        if len(palette)<result["classes"]:
            raise StorageError("Not enough palette colors for requested classes.")
        colors=palette[:result["classes"]]
        # Classify read-only first; validated style write is revision checked.
        saved=change_style(project_id,body.layer_id,{"symbol":{
            "graduated_field":body.field,"graduated_method":body.method,
            "graduated_breaks":result["breaks"],"graduated_colors":colors,
            "category_field":"","category_colors":{},
        }},body.expected_revision)
        return {"classification":result,"layer":saved}
    except StorageError as error:
        raise HTTPException(status_code=409 if "conflict" in str(error).lower()
                            else 404 if "not found" in str(error).lower()
                            else 422,detail=str(error)) from error
