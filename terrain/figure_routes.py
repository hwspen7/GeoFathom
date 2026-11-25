"""Plot tables for saved terrain receipts and vector PDF figure export."""
import io
import json
import math
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Literal
from fastapi import APIRouter,HTTPException,Request,Response
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,Field,model_validator
from imagery.raster import RasterError
from imagery.store import file_sha256
from geometry.measure import GeometryError
from .routes import AdvancedTerrainInput,raster,run_cancelable
from .research import execute
from .figure_data import figure_data_from_result

class FigureValidationRoute(APIRoute):
    def get_route_handler(self):
        original=super().get_route_handler()
        async def handler(request):
            try:return await original(request)
            except RequestValidationError as error:
                # Non-standard JSON NaN/Infinity must produce a validation
                # response, rather than failing while encoding error inputs.
                details=json.loads(json.dumps(error.errors(),default=str),parse_constant=str)
                return JSONResponse(status_code=422,content={'detail':details})
        return handler

router=APIRouter(prefix='/terrain/figures',tags=['terrain figures'],route_class=FigureValidationRoute)
class FigureDataInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    base:AdvancedTerrainInput
    expected_source_sha256:str|None=Field(default=None,pattern=r'^[0-9a-f]{64}$')

def _calculate(body,cancel=None):
    path=raster(body.base.image_id)
    checksum=file_sha256(path)
    if body.expected_source_sha256 and checksum!=body.expected_source_sha256:
        raise RasterError('Source checksum changed; regenerate the analysis before plotting.')
    result=execute(body.base,path,raster,cancel)
    data=result.get('plot_data') or figure_data_from_result(result,cancel)
    if file_sha256(path)!=checksum:
        raise RasterError('Source changed during plot-data generation.')
    data['source_sha256']=checksum
    return data

@router.post('/data')
async def figure_data(request:Request,body:FigureDataInput):
    try:return await run_cancelable(request,_calculate,body)
    except (RasterError,GeometryError,ValueError,OverflowError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error

class Primitive(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    kind:Literal['line','rect','polyline','polygon','circle','text']
    x:float=Field(default=0,ge=-10000,le=10000)
    y:float=Field(default=0,ge=-10000,le=10000)
    x2:float=Field(default=0,ge=-10000,le=10000)
    y2:float=Field(default=0,ge=-10000,le=10000)
    width:float=Field(default=0,ge=0,le=10000)
    height:float=Field(default=0,ge=0,le=10000)
    radius:float=Field(default=0,ge=0,le=10000)
    points:list[tuple[float,float]]=Field(default_factory=list,max_length=5000)
    text:str=Field(default='',max_length=1000)
    stroke:str=Field(default='#000000',pattern=r'^#[0-9a-fA-F]{6}$')
    fill:str=Field(default='none',pattern=r'^(none|#[0-9a-fA-F]{6})$')
    line_width:float=Field(default=1,ge=0,le=20)
    font_size:float=Field(default=15,ge=6,le=60)
    font:Literal['sans','serif']='sans'
    anchor:Literal['start','middle','end']='start'
    angle:float=Field(default=0,ge=-360,le=360)
    dashed:bool=False
    @model_validator(mode='after')
    def check_points(self):
        if any(not math.isfinite(v) or abs(v)>10000 for point in self.points for v in point):
            raise ValueError('Figure points must be finite and bounded.')
        return self

class FigurePDFInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    width:float=Field(default=900,ge=100,le=2000)
    height:float=Field(default=600,ge=100,le=2000)
    width_mm:float=Field(default=160,ge=60,le=300)
    height_mm:float=Field(default=110,ge=40,le=300)
    title:str=Field(default='GeoFathom research figure',max_length=200)
    primitives:list[Primitive]=Field(min_length=1,max_length=6000)
    @model_validator(mode='after')
    def point_budget(self):
        if sum(len(p.points) for p in self.primitives)>20000:
            raise ValueError('Vector figure exceeds the point budget.')
        return self

_FONT_LOCK=Lock()
@lru_cache(maxsize=2)
def figure_font(serif):
    from reportlab import __file__ as reportlab_file
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    filename='Vera.ttf'
    name='GeoFathomFigureSerif' if serif else 'GeoFathomFigureSans'
    path=Path(__file__).parent/'fonts'/'DejaVuSerif.ttf' if serif else Path(reportlab_file).parent/'fonts'/filename
    with _FONT_LOCK:
        if name not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont(name,str(path)))
    return name


def make_vector_pdf(body):
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.colors import HexColor
    stream=io.BytesIO();pw=body.width_mm*72/25.4;ph=body.height_mm*72/25.4
    canvas=Canvas(stream,pagesize=(pw,ph));canvas.setTitle(body.title)
    factor=min(pw/body.width,ph/body.height)
    canvas.translate((pw-body.width*factor)/2,(ph-body.height*factor)/2)
    canvas.scale(factor,factor)
    for p in body.primitives:
        canvas.saveState();canvas.setLineWidth(p.line_width);canvas.setStrokeColor(HexColor(p.stroke))
        canvas.setFillColor(HexColor(p.fill) if p.fill!='none' else HexColor('#000000'))
        if p.dashed:canvas.setDash(5,4)
        if p.kind=='line':canvas.line(p.x,body.height-p.y,p.x2,body.height-p.y2)
        elif p.kind=='rect':canvas.rect(p.x,body.height-p.y-p.height,p.width,p.height,stroke=bool(p.line_width),fill=p.fill!='none')
        elif p.kind=='circle':canvas.circle(p.x,body.height-p.y,p.radius,stroke=bool(p.line_width),fill=p.fill!='none')
        elif p.kind in {'polyline','polygon'} and p.points:
            path=canvas.beginPath();path.moveTo(p.points[0][0],body.height-p.points[0][1])
            for x,y in p.points[1:]:path.lineTo(x,body.height-y)
            if p.kind=='polygon':path.close()
            canvas.drawPath(path,stroke=bool(p.line_width),fill=p.fill!='none')
        elif p.kind=='text':
            canvas.setFont(figure_font(p.font=='serif'),p.font_size)
            canvas.translate(p.x,body.height-p.y);canvas.rotate(-p.angle)
            draw={'start':canvas.drawString,'middle':canvas.drawCentredString,'end':canvas.drawRightString}[p.anchor]
            draw(0,0,p.text)
        canvas.restoreState()
    canvas.showPage();canvas.save();return stream.getvalue()

@router.post('/pdf')
async def figure_pdf(body:FigurePDFInput):
    from starlette.concurrency import run_in_threadpool
    data=await run_in_threadpool(make_vector_pdf,body)
    return Response(data,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="research-figure.pdf"'})
