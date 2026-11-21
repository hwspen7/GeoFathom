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
