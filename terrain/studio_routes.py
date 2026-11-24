"""Bounded scientific figure studio API and reproducibility export."""
import base64
import hashlib
import json
import math
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool
from .figure_routes import FigureValidationRoute
from .studio_catalog import catalog, BY_ID
from .studio_data import FigureInputError, raster_table
from .studio_render import render
from typing import Literal

router=APIRouter(prefix='/terrain/studio',tags=['scientific figure studio'],route_class=FigureValidationRoute)

class RasterInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=160)
    data:str=Field(min_length=1,max_length=32_000_000)
    unit:str=Field(default='',max_length=80)

class StudioInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    recipe:str=Field(max_length=80)
    csv:str=Field(default='',max_length=5_000_000)
    rasters:list[RasterInput]=Field(default_factory=list,max_length=8)
    x:str=Field(default='',max_length=120)
    y:str=Field(default='',max_length=120)
    z:str=Field(default='',max_length=120)
    group:str=Field(default='',max_length=120)
    low:str=Field(default='',max_length=120)
    high:str=Field(default='',max_length=120)
    columns:list[str]=Field(default_factory=list,max_length=12)
    title:str=Field(default='',max_length=200)
    x_label:str=Field(default='',max_length=160)
    y_label:str=Field(default='',max_length=160)
    parameter:float|None=None
    maximize_x:bool=False
    maximize_y:bool=False
    palette:Literal['mono','color','earth']='color'
    font:Literal['sans','serif']='sans'
    font_size:int=Field(default=10,ge=6,le=18)
    grid:bool=True
    width_mm:float=Field(default=180,ge=60,le=300)
    height_mm:float=Field(default=125,ge=40,le=250)
    dpi:Literal[120,300,600]=120
    format:Literal['png','pdf','svg','tiff']='png'

    @model_validator(mode='after')
    def validate_budget(self):
        if self.recipe not in BY_ID:raise ValueError('Unknown figure recipe.')
        if sum(len(r.data) for r in self.rasters)>48_000_000:raise ValueError('Combined raster payload exceeds limit.')
        if self.width_mm*self.height_mm*(self.dpi/25.4)**2>20_000_000:raise ValueError('Image exceeds 20 megapixels; reduce dimensions or DPI.')
        if any(not c or len(c)>120 for c in self.columns):raise ValueError('Invalid series column.')
        if BY_ID[self.recipe][3]=='table' and not self.csv.strip():raise ValueError('Supply a CSV table.')
        return self

@router.get('/catalog')
def studio_catalog():
    return {'legacy_recipe_count':24,'additional_recipe_count':len(BY_ID),'recipes':catalog()}

@router.post('/render')
async def studio_render(body:StudioInput):
    try:
        payload,metadata,table=await run_in_threadpool(render,body)
        if body.csv:metadata['csv_sha256']=hashlib.sha256(body.csv.encode('utf-8')).hexdigest()
        metadata.update(schema='geofathom-studio-1',settings=body.model_dump(exclude={'csv','rasters'}))
        # Strict JSON serialization catches a broken numerical result before a successful response.
        json.dumps({'metadata':metadata,'table':table},allow_nan=False)
        return {'figure':base64.b64encode(payload).decode('ascii'),
                'media_type':{'png':'image/png','pdf':'application/pdf','svg':'image/svg+xml','tiff':'image/tiff'}[body.format],
                'metadata':metadata,'table':table}
    except (FigureInputError,ValueError,OverflowError,RuntimeError,OSError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


class RasterTableInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    rasters:list[RasterInput]=Field(min_length=1,max_length=8)
    limit:int=Field(default=20000,ge=1,le=20000)

    @model_validator(mode='after')
    def validate_payload(self):
        if sum(len(r.data) for r in self.rasters)>48_000_000:raise ValueError('Combined raster payload exceeds limit.')
        return self

@router.post('/raster-table')
async def studio_raster_table(body:RasterTableInput):
    try:return await run_in_threadpool(raster_table,body.rasters,body.limit)
    except (FigureInputError,ValueError,RuntimeError,OSError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error
