"""Independent spatiotemporal workbench with explicit dated raster bindings."""
import base64,hashlib,math
import numpy as np
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from rasterio.errors import RasterioError
from terrain.studio_data import FigureInputError
from imagery.remote_routes import Source,Binding,Quality,read_band
from imagery.remote_kernels import quality_mask
from imagery.remote_research import long_series
from imagery.remote_temporal_models import seasonal_metrics,segmented_means
from analysis.science_raster import require
from analysis.science_routes import raster_product,raster_preview
from analysis.science_figures import csv_text
from .spacetime_models import trend,temporal,forecast,spatial_lag,variogram

router=APIRouter(prefix='/analysis/spatiotemporal',tags=['spatiotemporal science'])
# parameter = (default,minimum,maximum,integer)
P={'minimum_observations':(6,3,64,True),'lag':(1,1,32,True),'threshold':(0,-1e50,1e50,False),'horizon':(30,.000001,1e7,False),'radius':(3,1,20,True),'period':(365,.000001,1e7,False),'fraction':(.5,.01,.99,False),'minimum_amplitude':(.01,0,1e50,False),'min_segment':(3,2,32,True),'penalty':(1,.000001,1e50,False)}
METHODS={
 'coverage':('Cube quality','Valid acquisition fraction',()),
 'exceedance':('Temporal extremes','Observed exceedance fraction',('threshold','minimum_observations')),
 'lag_correlation':('Temporal dependence','Lagged temporal Pearson correlation',('lag','minimum_observations')),
 'sen':('Trend','Theil–Sen slope',()),
 'mk_p':('Trend inference','Tie-corrected Mann–Kendall p-value',()),
 'mk_by_q':('Trend inference','Benjamini–Yekutieli adjusted trend q-value',()),
 'forecast_mean':('Prediction','Linear trend future prediction',('minimum_observations','horizon')),
 'forecast_sd':('Prediction','Conditional future observation SD',('minimum_observations','horizon')),
 'hindcast_rmse':('Prediction validation','Expanding-window hindcast RMSE',('minimum_observations',)),
 'hindcast_skill':('Prediction validation','Hindcast skill against persistence',('minimum_observations',)),
 'space_time_lag':('Space-time dependence','Lagged spatial neighborhood association',('minimum_observations',)),
 'space_time_variogram':('Space-time dependence','Directional empirical space-time variogram',('lag','radius')),
 'series_median':('Temporal summary','Temporal median',()),
 'series_count':('Temporal summary','Valid observation count',()),
 'series_slope':('Trend','OLS slope on actual acquisition times',()),
 'series_amplitude':('Seasonality','Detrended harmonic amplitude',('period',)),
 'series_harmonic_rmse':('Seasonality','Harmonic residual RMSE',('period',)),
}
class CubeInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    operation:str=Field(max_length=80)
    sources:list[Source]=Field(min_length=1,max_length=64)
    observations:list[Binding]=Field(min_length=6,max_length=64)
    times:list[float]=Field(min_length=6,max_length=64)
    quality:list[Quality]=Field(default_factory=list,max_length=64)
    parameters:dict[str,float]=Field(default_factory=dict,max_length=12)
    time_unit:str=Field(default='day',min_length=1,max_length=24)

@router.get('/catalog')
def catalog():
    return {'operations':[{'id':k,'group':g,'title':title,'parameters':[{'name':p,'label':p.replace('_',' '),'default':P[p][0],'minimum':P[p][1],'maximum':P[p][2],'integer':P[p][3]} for p in params]} for k,(g,title,params) in METHODS.items()],'operation_count':len(METHODS),'input_schema':CubeInput.model_json_schema()}

def execute(body):
    require(body.operation in METHODS,'Unknown space-time method.')
    kind=body.operation;n=len(body.times);t=np.asarray(body.times,float)
    require(n==len(body.observations) and np.isfinite(t).all() and np.all(np.diff(t)>0) and 1e-9<=t[-1]-t[0]<=1e9,'One strictly increasing finite time per observation, with bounded time span.')
    require(np.min(np.diff(t))>=1e-9,'Time increments too small; rescale time units.')
    params=METHODS[kind][2];require(set(body.parameters)<=set(params),'Unknown method parameter.')
    p={}
    for key in params:
        default,lo,hi,integer=P[key];x=body.parameters.get(key,default)
        require(math.isfinite(x) and lo<=x<=hi and (not integer or x==int(x)),'Parameter outside method bounds: '+key)
        p[key]=int(x) if integer else x
    if 'minimum_observations' in p:require(p['minimum_observations']<=n,'Minimum observations exceeds cube dates.')
    require(sum(len(s.data) for s in body.sources)<=48_000_000,'Cube payload exceeds 48 MB.')
    raw=[base64.b64decode(s.data,validate=True) for s in body.sources];sha=[hashlib.sha256(x).hexdigest() for x in raw]
    first=None;arrays=[];bindings=[]
    def read(b,quantity):
        nonlocal first
        require(b.source<len(raw),'Unknown cube source.')
        g=read_band(body.sources[b.source],b,quantity,raw[b.source],sha[b.source])
        if first is None:first=g;require(n*g.values.size<=4_000_000,'Cube exceeds four million dated cells.')
        else:require(g.values.shape==first.values.shape and g.transform==first.transform and g.crs==first.crs,'Explicitly align every observation and QA grid.')
        return g
    for b in body.observations:
        quantity='reflectance' if b.encoding=='landsat_sr' else 'kelvin' if b.encoding=='landsat_st' else 'numeric'
        g=read(b,quantity);require(g.unit==first.unit,'All observations must share the same physical unit.')
        arrays.append(g.values);bindings.append({'source_sha256':sha[b.source],'binding':b.model_dump(),'unit':g.unit,'scale':g.scale,'offset':g.offset})
    quality_receipt=[]
    for q in body.quality:
        names=q.roles or [str(i+1) for i in range(n)]
        require(set(names)<={str(i+1) for i in range(n)},'QA roles must be one-based acquisition numbers.')
        g=read(Binding(source=q.source,band=q.band,encoding='raw'),'class');clear=quality_mask(g.values,q.scheme)==1
        for i in set(names):arrays[int(i)-1][~clear]=np.nan
        quality_receipt.append({'source_sha256':sha[q.source],**q.model_dump()})
    stack=np.stack(arrays);require(np.isfinite(stack).any(),'No valid cube observations.')
    out=None;rows=[];cols=[];meta={};figures=[];unit=first.unit
    def plot(title,recipe,cols,rows,**bindings):
        figures.append({'title':title,'recipe':recipe,'bindings':bindings,'csv':csv_text(cols,rows),'raster':False})
    if kind in ('sen','mk_p','mk_by_q'):
        out,meta=trend(stack,t,kind);unit=unit+'/'+body.time_unit if kind=='sen' else 'probability'
    elif kind in ('coverage','exceedance','lag_correlation'):
        out,meta=temporal(stack,t,kind,p);unit='index' if kind=='lag_correlation' else 'fraction'
    elif kind.startswith(('forecast_','hindcast_')):
        out,cols,rows,meta=forecast(stack,t,kind,p);unit='index' if kind=='hindcast_skill' else unit
        if rows:plot('Expanding-window forecast versus persistence error','multi_line',cols,rows,x='time',columns=['trend_rmse','persistence_rmse'])
    elif kind=='space_time_lag':
        out,cols,rows,meta=spatial_lag(stack,kind,p);unit='index'
        if any(r[-1] is not None for r in rows):plot('Lagged neighborhood association by acquisition','basic_line',cols,[r for r in rows if r[-1] is not None],x='acquisition',y='lag_product')
    elif kind=='space_time_variogram':
        cols,rows,meta=variogram(stack,t,first,p)
        for direction in ('east','north','temporal'):
            sub=[r for r in rows if r[0]==direction]
            if sub:plot(direction+' directional space-time semivariance','basic_scatter' if direction=='temporal' else 'basic_scatter',cols,sub,x='time_lag' if direction=='temporal' else 'space_m',y='semivariance')
    else:
        out,meta=long_series(kind,stack,t,p.get('period',365))
        if kind=='series_count':unit='count'
        if kind=='series_slope':unit=unit+'/'+body.time_unit
    # Independent cube diagnostic for every analysis: actual per-date coverage
    # and observed distribution (not a fixed spatial population).
    coverage=[]
    for time,z in zip(t,stack):
        x=z[np.isfinite(z)]
        if len(x):coverage.append([float(time),len(x),float(np.median(x)),float(np.quantile(x,.25)),float(np.quantile(x,.75))])
    if coverage:
        plot('Observed cube coverage by date','basic_column',['time','cells','median','q25','q75'],coverage,x='time',y='cells')
        plot('Observed spatial median and interquartile range','errorbar',['time','cells','median','q25','q75'],coverage,x='time',y='median',low='q25',high='q75')
    product=raster_product(kind,out,first.transform,first.crs,unit) if out is not None else None
    if product:
        figures.insert(0,{'title':METHODS[kind][1]+' map','recipe':'raster_continuous','bindings':{},'csv':None,'raster':True})
        if not rows:cols=['quantile','value'];rows=product['summary']['quantiles']
    receipt={'schema':'geofathom-spatiotemporal','operation':kind,'crs':str(first.crs),'unit':unit,'times':body.times,'time_unit':body.time_unit,'parameters':p,'observations':bindings,'quality':quality_receipt,'metrics':meta}
    return {'operation':kind,'receipt':receipt,'features':None,'raster':product,'preview':raster_preview(product) if product else None,'figures':figures,'columns':cols,'rows':rows,'csv':csv_text(cols,rows)}

@router.post('/run')
def run(body:CubeInput):
    try:return execute(body)
    except (FigureInputError,ValueError,TypeError,OverflowError,RasterioError,np.linalg.LinAlgError) as e:raise HTTPException(422,detail=str(e)) from e
