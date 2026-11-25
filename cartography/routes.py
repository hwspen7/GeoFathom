"""Project map print-layout PDF with no unlicensed basemap scraping."""
from fastapi import APIRouter,HTTPException
from fastapi.responses import Response
from pydantic import BaseModel,Field
from storage.database import StorageError
from .printing import render_pdf

router=APIRouter(prefix="/projects",tags=["cartographic-print"])

class PrintLayout(BaseModel):
    title:str=Field(default="GeoFathom map",min_length=1,max_length=120)
    paper:str="a4"
    orientation:str="landscape"
    extent:list[float]|None=Field(default=None,min_length=4,max_length=4)
    show_grid:bool=True
    show_legend:bool=True
    layer_ids:list[str]|None=Field(default=None,max_length=100)

@router.post("/{project_id}/print/pdf")
def export_print(project_id:str,body:PrintLayout):
    try:
        data=render_pdf(project_id,body.title,body.paper,body.orientation,
                        body.extent,body.show_grid,body.show_legend,body.layer_ids)
    except StorageError as error:
        raise HTTPException(status_code=404 if "not found" in str(error).lower()
                           else 422,detail=str(error)) from error
    return Response(content=data,media_type="application/pdf",headers={
        "Content-Disposition":'attachment; filename="geofathom-map.pdf"',
        "Cache-Control":"no-store",
    })
