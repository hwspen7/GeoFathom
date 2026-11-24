"""Shared, bounded spatial scientific computation API and AI tool contracts."""
import base64
import csv
import hashlib
import io
import json
import math
from typing import Literal
from fastapi import APIRouter,HTTPException
from storage.database import StorageError
from storage.vectorio import VectorIOError
from imagery.store import image_file,describe
from pydantic import BaseModel,ConfigDict,Field
from rasterio.io import MemoryFile
from pyproj import CRS,Transformer
import numpy as np
from shapely.errors import ShapelyError
from pyproj.exceptions import ProjError
from terrain.studio_data import read_grids,aligned_grids,FigureInputError
from terrain.studio_routes import RasterInput
from .science_catalog import BY_ID,catalog
from .science_raster import require,raster_operation,sample_cells,permutation_stat,decision,local_stat
from .science_vector import load_layers,vector_operation,integrated
from .science_advanced import euclidean_distance,focal_quantile,lag_scan,bivariate_moran,robust_overlay,blocked_raster_regression

router=APIRouter(prefix='/analysis/science',tags=['spatial science'])
source_router=APIRouter(tags=['spatial science sources'])

class SpatialInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    operation:str=Field(max_length=80)
    vectors:list[dict]=Field(default_factory=list,max_length=2)
    rasters:list[RasterInput]=Field(default_factory=list,max_length=8)
    epsg:int=Field(default=32617,ge=1,le=999999)
    parameters:dict[str,float]=Field(default_factory=dict,max_length=12)
    weights:list[float]=Field(default_factory=list,max_length=8)
    directions:list[str]=Field(default_factory=list,max_length=8)
    pairwise:list[list[float]]=Field(default_factory=list,max_length=8)
    breaks:list[float]=Field(default_factory=list,max_length=25)
    resampling:Literal['nearest','bilinear']='nearest'
    local_view:Literal['statistic','p','q','cluster']='statistic'
    robust_view:Literal['mean','sd','probability','mc_se']='mean'
    neighborhood:Literal['rook','queen']='rook'
    regression_view:Literal['prediction','residual']='prediction'

def raster_product(name,z,transform,crs,unit):
    require(not np.isinf(z).any(),'Numerical overflow in derived raster; rescale the input quantities.')
    valid=np.isfinite(z);require(valid.any(),'Operation produced no valid cells.')
    require(np.max(np.abs(z[valid]))<=1e100,'Output exceeds numerical range.')
    # Describe the full numerical product before display resampling or export.
    values=z[valid];probs=np.linspace(0,1,21)
    summary={'valid_cells':int(values.size),'nodata_cells':int(z.size-values.size),
             'minimum':float(values.min()),'maximum':float(values.max()),
             'quantiles':[[float(p),float(q)] for p,q in zip(probs,np.quantile(values,probs))]}
    if unit=='class':
        classes,counts=np.unique(values,return_counts=True)
        if len(classes)<=50:summary['class_counts']=[[float(c),int(n)] for c,n in zip(classes,counts)]
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',width=z.shape[1],height=z.shape[0],count=1,dtype='float64',crs=crs,
                      transform=transform,nodata=float('nan'),compress='deflate') as ds:
            ds.write(z,1);ds.update_tags(TERRAIN_UNIT=unit,SPATIAL_METHOD=name)
        raw=mem.read()
    require(len(raw)<=24_000_000,'Derived raster exceeds the inline export budget.')
    return {'name':name,'data':base64.b64encode(raw).decode(),'unit':unit,'sha256':hashlib.sha256(raw).hexdigest(),'band':1,'summary':summary}


def raster_preview(product):
    """Render a separate Mercator-aligned display image; never resample the scientific product."""
    from rasterio.transform import array_bounds,from_bounds
    from rasterio.warp import calculate_default_transform,reproject,Resampling
    from PIL import Image
    from matplotlib import colormaps
    try:
        with MemoryFile(base64.b64decode(product['data'])) as mem,mem.open() as ds:
            transform,w,h=calculate_default_transform(ds.crs,'EPSG:3857',ds.width,ds.height,*ds.bounds)
            if w<=0 or h<=0:return None
            west,south,east,north=array_bounds(h,w,transform)
            reverse=Transformer.from_crs(3857,4326,always_xy=True)
            lon0,lat0=reverse.transform(west,south);lon1,lat1=reverse.transform(east,north)
            if not(-180<=lon0<lon1<=180 and lon1-lon0<170 and -85.0512<=lat0<lat1<=85.0512):return None
            scale=min(1,640/max(w,h));ww=max(1,round(w*scale));hh=max(1,round(h*scale))
            target=from_bounds(west,south,east,north,ww,hh)
            out=np.full((hh,ww),np.nan)
            reproject(ds.read(1),out,src_transform=ds.transform,src_crs=ds.crs,src_nodata=np.nan,
                      dst_transform=target,dst_crs='EPSG:3857',dst_nodata=np.nan,resampling=Resampling.nearest)
            valid=np.isfinite(out)
            if not valid.any():return None
            lo=float(np.nanmin(out));hi=float(np.nanmax(out))
            normalized=np.divide(out-lo,hi-lo,out=np.zeros_like(out),where=valid) if hi>lo else np.full_like(out,.5)
            rgba=colormaps['viridis'](np.where(valid,np.clip(normalized,0,1),0),bytes=True)
            rgba[:,:,3]=np.where(valid,255,0);buffer=io.BytesIO();Image.fromarray(rgba).save(buffer,format='PNG')
            return {'png':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),'corners':[[lon0,lat1],[lon1,lat1],[lon1,lat0],[lon0,lat0]],
                    'width':ww,'height':hh,'valid_cells':int(valid.sum()),'minimum':lo,'maximum':hi,'unit':product['unit'],
                    'method':'Nearest-neighbor display only; original GeoTIFF remains unchanged.'}
    except (ValueError,RuntimeError,OSError,ProjError):
        return None

def csv_output(headers,rows):
    if not headers:return ''
    f=io.StringIO();writer=csv.writer(f);writer.writerow(headers);writer.writerows(rows);return f.getvalue()

def execute(body):
    method=BY_ID.get(body.operation);require(method is not None,'Unknown spatial operation.')
    kind=method.id;params={}
    require(set(body.parameters)<=set(p[0] for p in method.parameters),'Unknown parameter for this method.')
    for key,_,default,lo,hi,integer in method.parameters:
        value=body.parameters.get(key,default)
        require(math.isfinite(value) and lo<=value<=hi and (not integer or float(value).is_integer()),'Invalid parameter: '+key)
        params[key]=int(value) if integer else float(value)
    nv=len(body.vectors);nr=len(body.rasters)
    if method.source=='vector':require(method.minimum<=nv<=method.maximum and nr==0,'Select required vector layers only.')
    elif method.source=='raster':require(method.minimum<=nr<=method.maximum and nv==0,'Select required raster layers only.')
    else:require(nr==1 and nv==1,'Select one raster and one vector layer.')
    require(sum(len(r.data) for r in body.rasters)<=48_000_000,'Raster payload budget exceeded.')
    require(len(json.dumps(body.vectors,allow_nan=False))<=8_000_000,'Vector payload budget exceeded.')
    grids=read_grids(body.rasters) if nr else []
    g=grids[0] if nr else None
    if nr and method.source=='integrated':require(g.is_meter,'Vector/raster integration requires a projected metre grid.')
    if nv:groups,reverse=load_layers(body.vectors,g.crs if nr else f'EPSG:{body.epsg}')
    elif nr:reverse=Transformer.from_crs(g.crs,4326,always_xy=True)
    features=None;headers=[];rows=[];product=None;meta={}
    if method.source=='vector':
        features,headers,rows,meta=vector_operation(kind,groups,reverse,params)
    elif kind=='raster_distance':
        require(g.is_meter,'Exact proximity requires a projected metre raster.')
        out=euclidean_distance(g.values,g.transform.a,abs(g.transform.e));product=raster_product(kind,out,g.transform,g.crs,'m')
        meta={'target_cells':int(np.count_nonzero(g.values==1)),'maximum_distance_m':float(np.nanmax(out))}
    elif kind=='focal_quantile':
        out=focal_quantile(g.values,params['radius'],params['quantile']);product=raster_product(kind,out,g.transform,g.crs,g.unit)
    elif kind=='directional_lag_scan':
        require(g.is_meter,'Directional distance scans require a projected metre grid.')
        headers,rows=lag_scan(g.values,g.transform.a,abs(g.transform.e),params['max_lag'])
    elif kind=='bivariate_moran':
        stack,common=aligned_grids(grids,require_same_unit=False)
        meta,null=bivariate_moran(stack[0],stack[1],params['permutations'],params['seed'])
        headers=['permutation','null_statistic','observed_statistic'];rows=[[i+1,float(value),meta['observed']] for i,value in enumerate(null)]
    elif kind=='robust_overlay':
        stack,common=aligned_grids(grids,require_same_unit=False)
        products,meta=robust_overlay(stack,common,body.weights,body.directions,params['draws'],params['concentration'],params['threshold'],params['seed'])
        product=raster_product(kind,products[body.robust_view],g.transform,g.crs,'probability' if body.robust_view in {'probability','mc_se'} else 'unitless')
        meta['view']=body.robust_view
    elif kind=='blocked_regression':
        out,headers,rows,meta=blocked_raster_regression(grids,params)
        if body.regression_view=='residual':out=g.values-out
        product=raster_product(kind,out,g.transform,g.crs,g.unit);meta['view']=body.regression_view
    elif method.source=='integrated' or kind=='polygonize':
        if kind=='polygonize':require(g.is_meter,'Polygonization requires projected metre raster.')
        out,unit,headers,rows,features,meta=integrated(kind,g,groups if nv else [],params,reverse)
        if out is not None:product=raster_product(kind,out,g.transform,g.crs,unit)
    elif kind.startswith('sample_'):
        idx,weights=sample_cells(g.values,kind,params['count'],params['seed'])
        yy,xx=np.unravel_index(idx,g.values.shape);east,north=g.axes
        headers=['row','column','x','y','value','design_weight']
        rows=[[int(r),int(c),float(east[c]),float(north[r]),float(g.values[r,c]),float(w)] for r,c,w in zip(yy,xx,weights)]
        meta={'sample_count':len(rows),'valid_population':int(np.isfinite(g.values).sum()),'weight_sum':float(weights.sum())}
    elif kind in {'global_moran','global_geary','join_count'}:
        meta,null=permutation_stat(g.values,kind,params['permutations'],params['seed'],body.neighborhood,return_null=True)
        headers=['permutation','null_statistic','observed_statistic'];rows=[[i+1,float(value),meta['observed']] for i,value in enumerate(null)]
    elif kind in {'local_moran','getis_ord_gi_star'}:
        out,meta,unit=local_stat(g.values,kind,body.local_view,params['permutations'],params['seed'],params['alpha'])
        product=raster_product(kind,out,g.transform,g.crs,unit);meta['view']=body.local_view
    elif kind=='raster_quantile':
        v=g.values[np.isfinite(g.values)];meta={'count':len(v),'quantile':params['quantile'],'value':float(np.quantile(v,params['quantile'])),'mean':float(v.mean()),'sample_sd':float(v.std(ddof=1)) if len(v)>1 else None}
        headers=list(meta);rows=[list(meta.values())]
    elif kind=='resample_grid':
        from rasterio.warp import reproject,Resampling
        source=grids[1];out=np.full(g.values.shape,np.nan)
        if body.resampling=='bilinear':require(source.unit!='class','Categorical grids require nearest resampling.')
        reproject(source.values,out,src_transform=source.transform,src_crs=source.crs,src_nodata=np.nan,
                  dst_transform=g.transform,dst_crs=g.crs,dst_nodata=np.nan,resampling=getattr(Resampling,body.resampling))
        out[~np.isfinite(g.values)]=np.nan;product=raster_product(kind,out,g.transform,g.crs,source.unit)
        meta={'valid_output_cells':int(np.isfinite(out).sum()),'resampling':body.resampling}
    elif kind=='reclassify':
        breaks=np.asarray(body.breaks,float);require(2<=len(breaks)<=25 and np.isfinite(breaks).all() and np.all(np.diff(breaks)>0),'Provide 2–25 strictly increasing class breaks.')
        z=g.values;valid=np.isfinite(z)&(z>=breaks[0])&(z<=breaks[-1]);out=np.full(z.shape,np.nan)
        out[valid]=np.minimum(np.searchsorted(breaks,z[valid],side='right')-1,len(breaks)-2)
        product=raster_product(kind,out,g.transform,g.crs,'class');meta={'valid_output_cells':int(valid.sum()),'breaks':body.breaks,'class_counts':[int(np.count_nonzero(out==i)) for i in range(len(breaks)-1)]}
    else:
        stack,common=aligned_grids(grids,require_same_unit=method.group!='Decision')
        if method.group=='Decision':
            if kind=='constraint_mask':
                require(np.isin(stack[1,np.isfinite(stack[1])],[0,1]).all(),'Constraint grid must contain only zero or one.')
                out=np.where(common&(stack[1]==1),stack[0],np.nan);unit=g.unit
            else:out,meta=decision(stack,common,kind,body.weights,body.directions,body.pairwise);unit='class' if kind=='pareto_cells' else 'unitless'
            transform=g.transform
        else:
            if nr>1:require(bool(g.unit),'Declare physical units before arithmetic.')
            out,transform,unit=raster_operation(kind,stack,common,g,params)
        product=raster_product(kind,out,transform,g.crs,unit)
        meta.update(valid_output_cells=int(np.isfinite(out).sum()),minimum=float(np.nanmin(out)),maximum=float(np.nanmax(out)),mean=float(np.nanmean(out)))
    receipt={'schema':'geofathom-spatial-science-1','operation':kind,'assumption':method.assumption,'parameters':params,
             'crs':str(g.crs) if nr else 'EPSG:'+str(body.epsg),'raster_sources':[{'name':x.name,'sha256':x.sha256,'band':x.band,'unit':x.unit,'scale':x.scale,'offset':x.offset} for x in grids],
             'vector_sources':[hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest() for x in body.vectors],
             'weights':body.weights,'directions':body.directions,'pairwise':body.pairwise,'breaks':body.breaks,'resampling':body.resampling,'local_view':body.local_view,'neighborhood':body.neighborhood,'robust_view':body.robust_view,'regression_view':body.regression_view,'metrics':meta,
             'vector_count':len(features['features']) if features else 0,'table_rows':len(rows),'raster_sha256':product['sha256'] if product else None,
             'raster_summary':product['summary'] if product else None,
             'table_sha256':hashlib.sha256(csv_output(headers,rows).encode('utf-8')).hexdigest(),
             'vector_output_sha256':hashlib.sha256(json.dumps(features,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest() if features else None}
    result={'operation':kind,'receipt':receipt,'features':features,'raster':product,'preview':raster_preview(product) if product else None,'columns':headers,'rows':rows,'csv':csv_output(headers,rows)}
    from .science_figures import figure_sources
    result['figures']=figure_sources(result,grids)
    json.dumps(result,allow_nan=False)
    return result

@router.get('/catalog')
def get_catalog():
    return {'schema':'geofathom-spatial-science-1','operations':catalog(),'operation_count':len(BY_ID),'ai_tool':{'name':'execute_spatial_science','endpoint':'/analysis/science/run','input_schema':SpatialInput.model_json_schema(),'output_types':['GeoJSON FeatureCollection','GeoTIFF','CSV','receipt']}}

@router.post('/run')
def run(body:SpatialInput):
    try:return execute(body)
    except (ValueError,TypeError,OverflowError,ShapelyError,ProjError,RuntimeError) as e:
        raise HTTPException(422,detail=str(e)) from e


@source_router.get('/projects/{project_id}/spatial-science/source/{layer_id}')
def project_layer(project_id:str,layer_id:str):
    from storage.exchange import snapshot
    try:
        source=snapshot(project_id,layer_ids=[layer_id])
        features=source['features']
        require(0<len(features)<=5000,'Select a nonempty layer with at most 5,000 features.')
        collection={'type':'FeatureCollection','features':features}
        require(len(json.dumps(collection,allow_nan=False))<=8_000_000,'Vector layer exceeds spatial science payload budget.')
        return collection
    except (StorageError,VectorIOError,ValueError) as e:raise HTTPException(422,detail=str(e)) from e

@source_router.get('/imagery/{image_id}/spatial-science/source')
def imagery_source(image_id:str):
    try:
        path=image_file(image_id)
        require(path.stat().st_size<=24_000_000,'Managed GeoTIFF exceeds 24 MB inline analysis budget; export a smaller study window.')
        raw=path.read_bytes();asset=describe(image_id)
        return {'name':asset['name'],'data':base64.b64encode(raw).decode(),'unit':'','band':1}
    except (FileNotFoundError,ValueError,RuntimeError,OSError) as e:raise HTTPException(422,detail=str(e)) from e
