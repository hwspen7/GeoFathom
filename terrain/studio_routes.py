"""Bounded scientific figure studio API and reproducibility export."""
import base64
import hashlib
import json
import math
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool
from .figure_routes import FigureValidationRoute, FigurePDFInput
from .studio_catalog import catalog, BY_ID
from .studio_data import FigureInputError, raster_table, inspect_sources
from .studio_render import render
from typing import Literal

router=APIRouter(prefix='/terrain/studio',tags=['scientific figure studio'],route_class=FigureValidationRoute)

class RasterInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=160)
    data:str=Field(min_length=1,max_length=32_000_000)
    unit:str=Field(default='',max_length=80)
    band:int=Field(default=1,ge=1,le=1024)

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
    variogram_model:Literal['none','exponential','gaussian','spherical']='none'
    variogram_view:Literal['fit','kriging_validation','kriging_prediction','kriging_sd']='fit'
    kriging_max_distance_m:float=Field(default=500,gt=0,le=100000)
    kriging_neighbors:int=Field(default=24,ge=3,le=48)
    spectral_mode:Literal['angle','abundance','reconstruction_error']='angle'
    endmember_csv:str=Field(default='',max_length=20000)
    endmember_index:int=Field(default=1,ge=1,le=8)
    hydrology_mode:Literal['observed','calibrated_reservoir']='observed'
    training_fraction:float=Field(default=.7,ge=.5,le=.85)
    model_validation:Literal['recorded','spatial_blocks']='recorded'
    block_size_m:float=Field(default=100,gt=0,le=1000000)
    validation_buffer_m:float=Field(default=0,ge=0,le=1000000)
    validation_folds:int=Field(default=5,ge=3,le=10)
    ridge_penalty:float=Field(default=1,ge=0,le=1000000)
    point_mode:Literal['planar','voxel']='planar'
    voxel_size:float=Field(default=10,gt=0,le=1000000)
    export_grid:bool=False
    spatial_inference:Literal['statistic','p','q','cluster']='statistic'
    permutations:int=Field(default=199,ge=99,le=9999)
    random_seed:int=Field(default=42,ge=0,le=4294967295)
    alpha:float=Field(default=.05,gt=0,lt=1)
    response_style:Literal['heatmap','filled','contour','surface']='surface'
    contour_levels:int=Field(default=12,ge=4,le=30)
    show_values:bool=True
    show_points:bool=True
    optimum:Literal['none','min','max']='none'
    profile_style:Literal['series','overlay','delta','bands']='series'
    map_style:Literal['continuous','diverging','categorical']='continuous'
    map_columns:int|None=Field(default=None,ge=1,le=3)
    map_common_mask:bool=False
    map_min:float|None=None
    map_max:float|None=None
    class_breaks:list[float]=Field(default_factory=list,max_length=25)
    line_width:float=Field(default=1.3,ge=.4,le=4)
    legend_position:Literal['best','upper left','upper right','lower left','lower right','center left','center right']='best'

    @model_validator(mode='after')
    def validate_budget(self):
        if self.recipe not in BY_ID:raise ValueError('Unknown figure recipe.')
        if self.recipe=='spectral_angle' and self.spectral_mode!='angle' and not self.endmember_csv.strip():raise ValueError('Supply calibrated endmember spectra.')
        if self.recipe=='model_learning' and self.model_validation=='spatial_blocks' and not self.columns:raise ValueError('Select regression feature columns.')
        if self.recipe=='point_density' and self.point_mode=='voxel' and not self.z:raise ValueError('Select the vertical coordinate column.')
        if self.class_breaks and (len(self.class_breaks)<2 or any(a>=b for a,b in zip(self.class_breaks,self.class_breaks[1:]))):raise ValueError('Class breaks must be strictly increasing.')
        if (self.map_min is None)!=(self.map_max is None) or (self.map_min is not None and self.map_min>=self.map_max):raise ValueError('Fixed display range requires increasing minimum and maximum.')
        if self.recipe=='raster_profile' and not self.csv.strip():raise ValueError('Supply path coordinates.')
        if sum(len(r.data) for r in self.rasters)>48_000_000:raise ValueError('Combined raster payload exceeds limit.')
        if self.width_mm*self.height_mm*(self.dpi/25.4)**2>20_000_000:raise ValueError('Image exceeds 20 megapixels; reduce dimensions or DPI.')
        if any(not c or len(c)>120 for c in self.columns):raise ValueError('Invalid series column.')
        if BY_ID[self.recipe][3]=='table' and not self.csv.strip():raise ValueError('Supply a CSV table.')
        return self

@router.get('/catalog')
def studio_catalog():
    entries=catalog()
    basic=sum(r['tier']=='basic' for r in entries)
    return {'legacy_recipe_count':24,'additional_recipe_count':len(entries),'basic_recipe_count':24+basic,'professional_recipe_count':len(entries)-basic,'recipes':entries}

@router.post('/render')
async def studio_render(body:StudioInput):
    try:
        grids=[] if body.export_grid else None
        payload,metadata,table=await run_in_threadpool(render,body,grid_sink=grids)
        if body.csv:metadata['csv_sha256']=hashlib.sha256(body.csv.encode('utf-8')).hexdigest()
        metadata.update(schema='geofathom-studio-1',settings=body.model_dump(exclude={'csv','rasters'}))
        # Strict JSON serialization catches a broken numerical result before a successful response.
        json.dumps({'metadata':metadata,'table':table},allow_nan=False)
        return {'figure':base64.b64encode(payload).decode('ascii'),
                'media_type':{'png':'image/png','pdf':'application/pdf','svg':'image/svg+xml','tiff':'image/tiff'}[body.format],
                'metadata':metadata,'table':table,'derived_rasters':grids or []}
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


class LegacyPanel(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    scene:FigurePDFInput
    table:list[list[str|float|None]]=Field(default_factory=list,max_length=20001)
    provenance:dict=Field(default_factory=dict)

class PanelSlot(BaseModel):
    model_config=ConfigDict(extra='forbid')
    row:int=Field(ge=0,le=5)
    column:int=Field(ge=0,le=5)
    row_span:int=Field(default=1,ge=1,le=6)
    column_span:int=Field(default=1,ge=1,le=6)

class CompositionInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    panels:list[StudioInput|LegacyPanel]=Field(min_length=2,max_length=12)
    title:str=Field(default='',max_length=200)
    caption:str=Field(default='',max_length=600)
    columns:int=Field(default=2,ge=1,le=3)
    width_mm:float=Field(default=240,ge=120,le=300)
    height_mm:float=Field(default=180,ge=80,le=300)
    dpi:Literal[120,300,600]=120
    format:Literal['png','pdf','svg','tiff']='png'
    spacing:float=Field(default=.06,ge=.02,le=.2)
    slots:list[PanelSlot]=Field(default_factory=list,max_length=12)
    row_weights:list[float]=Field(default_factory=list,max_length=6)
    column_weights:list[float]=Field(default_factory=list,max_length=6)

    @model_validator(mode='after')
    def budget(self):
        if sum(len(p.csv)+sum(len(r.data) for r in p.rasters) if isinstance(p,StudioInput) else len(p.model_dump_json()) for p in self.panels)>64_000_000:
            raise ValueError('Composition data exceeds payload limit.')
        if self.width_mm*self.height_mm*(self.dpi/25.4)**2>45_000_000:
            raise ValueError('Composition exceeds 45 megapixels.')
        slots=self.layout_slots()
        nr=max(s.row+s.row_span for s in slots);nc=max(s.column+s.column_span for s in slots)
        if nr>6 or nc>6:raise ValueError('Layout extends beyond six rows or columns.')
        if len(slots)!=len(self.panels):raise ValueError('Provide one layout slot per panel.')
        seen=set()
        for s in slots:
            cells={(r,c) for r in range(s.row,s.row+s.row_span) for c in range(s.column,s.column+s.column_span)}
            if seen&cells:raise ValueError('Panel slots overlap.')
            seen|=cells
        rw=self.row_weights or [1.]*nr;cw=self.column_weights or [1.]*nc
        if len(rw)!=nr or len(cw)!=nc or any(not math.isfinite(v) or not .2<=v<=5 for v in rw+cw):raise ValueError('Supply positive bounded weights for each layout row and column.')
        available_height=self.height_mm*(.81 if self.caption else 1)
        for s in slots:
            if self.width_mm*sum(cw[s.column:s.column+s.column_span])/sum(cw)<55 or available_height*sum(rw[s.row:s.row+s.row_span])/sum(rw)<40:
                raise ValueError('Panels are too small; increase dimensions, merge cells or adjust weights.')
        return self

    def layout_slots(self):
        if self.slots:return self.slots
        if self.columns>len(self.panels):raise ValueError('Column count exceeds panel count.')
        return [PanelSlot(row=i//self.columns,column=i%self.columns) for i in range(len(self.panels))]

def render_composition(body):
    import io
    import textwrap
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib import rc_context
    from .studio_render import LOCK
    from .studio_publication import layout_receipt,draw_legacy_panel,fit_publication_text,publication_title,prepare_publication
    with LOCK,rc_context({'pdf.fonttype':42,'svg.fonttype':'none','font.family':'sans-serif','font.size':9}):
        fig=Figure(figsize=(body.width_mm/25.4,body.height_mm/25.4),layout='constrained',facecolor='white')
        FigureCanvasAgg(fig)
        slots=body.layout_slots();nrows=max(s.row+s.row_span for s in slots);ncols=max(s.column+s.column_span for s in slots)
        # Subfigures share the parent canvas: plots, ticks and text remain vectors.
        # Reserve a real caption row rather than drawing across the data panels.
        if body.caption:
            gs=fig.add_gridspec(2,1,height_ratios=[1,.10 if len(body.caption)<180 else .19])
            top=fig.add_subfigure(gs[0]);bottom=fig.add_subplot(gs[1]);bottom.axis('off')
            bottom.text(.01,.92,textwrap.fill(body.caption,width=max(36,int(body.width_mm/1.4))),ha='left',va='top',transform=bottom.transAxes,fontsize=8)
        else:top=fig
        gs=top.add_gridspec(nrows,ncols,height_ratios=body.row_weights or None,width_ratios=body.column_weights or None,wspace=body.spacing,hspace=body.spacing)
        containers=[top.add_subfigure(gs[s.row:s.row+s.row_span,s.column:s.column+s.column_span]) for s in slots]
        receipts=[]
        for i,panel in enumerate(body.panels):
            if isinstance(panel,LegacyPanel):
                draw_legacy_panel(containers[i],panel.scene,f'({chr(97+i)})')
                meta={'recipe':'native_vector_figure','title':panel.scene.title,'provenance':panel.provenance};table=panel.table
            else:
                _,meta,table=render(panel,container=containers[i],panel_label=f'({chr(97+i)}) ')
                meta['csv_sha256']=hashlib.sha256(panel.csv.encode()).hexdigest() if panel.csv else None
            receipts.append({'label':chr(97+i),'metadata':meta,'table':table})
        if body.title:fig.suptitle(publication_title(body.title,body.width_mm,12),fontsize=12,fontweight='medium')
        layout=prepare_publication(fig)
        buf=io.BytesIO()
        if body.format=='tiff':fig.savefig(buf,format='tiff',dpi=body.dpi,pil_kwargs={'compression':'tiff_lzw'})
        else:fig.savefig(buf,format=body.format,dpi=body.dpi)
        fig.clear()
        return buf.getvalue(),{'schema':'geofathom-composition-1','layout':layout,'panel_count':len(receipts),'slots':[s.model_dump() for s in slots],'row_weights':body.row_weights,'column_weights':body.column_weights,'panels':receipts}

@router.post('/compose')
async def studio_compose(body:CompositionInput):
    try:
        payload,metadata=await run_in_threadpool(render_composition,body)
        json.dumps(metadata,allow_nan=False)
        return {'figure':base64.b64encode(payload).decode('ascii'),
                'media_type':{'png':'image/png','pdf':'application/pdf','svg':'image/svg+xml','tiff':'image/tiff'}[body.format],
                'metadata':metadata,'table':[]}
    except (FigureInputError,ValueError,OverflowError,RuntimeError,OSError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


class SourceInspectionInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    csv:str=Field(default='',max_length=5_000_000)
    rasters:list[RasterInput]=Field(default_factory=list,max_length=8)

    @model_validator(mode='after')
    def budget(self):
        if sum(len(r.data) for r in self.rasters)>48_000_000:raise ValueError('Combined raster payload exceeds limit.')
        return self

@router.post('/inspect')
async def inspect_studio_sources(body:SourceInspectionInput):
    try:
        result=await run_in_threadpool(inspect_sources,body.csv,body.rasters)
        json.dumps(result,allow_nan=False)
        return result
    except (FigureInputError,ValueError,OverflowError,RuntimeError,OSError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error
