"""Remote sensing API: typed band bindings, quality masks and reproducible products."""
import base64
import hashlib
import json
import math
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel,ConfigDict,Field
from rasterio.io import MemoryFile
from rasterio.errors import RasterioError
from terrain.studio_data import Grid,FigureInputError
from analysis.science_raster import require
from analysis.science_routes import raster_product,raster_preview,csv_output
from analysis.science_figures import figure_sources,csv_text
from .remote_catalog import BY_ID,catalog,SERIES_IDS
from .remote_research import surface_temperature,c_correction,ndvi_uncertainty,change_vectors,spatial_classifier,long_series,gamma_map,mad_distance
from .remote_products import rgb_product
from .remote_kernels import ratio,nd,optical,quality_mask,transition,agreement,temporal,pca,classify,sen_slope,temporal_slope_se,lee_filter,unmix,stratified_accuracy

router=APIRouter(prefix='/analysis/remote-sensing',tags=['remote sensing'])

class Source(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=160)
    data:str=Field(min_length=1,max_length=32_000_000)

class Binding(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    source:int=Field(ge=0,le=63)
    band:int=Field(default=1,ge=1,le=1024)
    encoding:Literal['metadata','raw','landsat_sr','landsat_st','custom']='metadata'
    scale:float=Field(default=1,gt=0,le=1e12)
    offset:float=Field(default=0,ge=-1e12,le=1e12)
    unit:str=Field(default='',max_length=80)

class Quality(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source:int=Field(ge=0,le=63)
    band:int=Field(default=1,ge=1,le=1024)
    scheme:Literal['binary','sentinel_clear','landsat_clear','landsat_unsaturated']='binary'
    roles:list[str]=Field(default_factory=list,max_length=64)

class RemoteInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    operation:str=Field(max_length=80)
    sources:list[Source]=Field(min_length=1,max_length=64)
    bindings:dict[str,Binding]=Field(min_length=1,max_length=64)
    quality:list[Quality]=Field(default_factory=list,max_length=64)
    parameters:dict[str,float]=Field(default_factory=dict,max_length=12)
    times:list[float]=Field(default_factory=list,max_length=64)

def read_band(source,binding,quantity,raw,sha):
    with MemoryFile(raw) as mem,mem.open() as ds:
        require(ds.driver=='GTiff' and ds.crs,'Use georeferenced GeoTIFF sources.')
        require(1<=binding.band<=ds.count,'Selected band is outside the raster band count.')
        a=ds.transform;require(a.b==0 and a.d==0 and a.a>0 and a.e<0,'Explicitly align north-up raster grids first.')
        require(ds.width*ds.height<=2_000_000,'Raster exceeds two million cell limit.')
        b=binding.band;z=ds.read(b,masked=True).astype(float).filled(np.nan)
        native_scale=float(ds.scales[b-1]);native_offset=float(ds.offsets[b-1])
        require(math.isfinite(native_scale) and math.isfinite(native_offset),'Invalid band calibration metadata.')
        tag=ds.tags(b).get('TERRAIN_UNIT') or ds.units[b-1] or ds.tags().get('TERRAIN_UNIT') or ''
        encoding=binding.encoding
        if encoding=='metadata':scale,offset=native_scale,native_offset
        elif encoding=='raw':scale,offset=1.,0.
        elif encoding=='custom':scale,offset=binding.scale,binding.offset
        else:
            require((encoding=='landsat_sr' and quantity=='reflectance') or (encoding=='landsat_st' and quantity=='kelvin'),'Landsat calibration must match the requested physical quantity.')
            require(np.all(z[np.isfinite(z)]==np.floor(z[np.isfinite(z)])) and np.all((z[np.isfinite(z)]>=0)&(z[np.isfinite(z)]<=65535)),'Landsat preset expects original unsigned integer DN.')
            scale,offset=(.0000275,-.2) if encoding=='landsat_sr' else (.00341802,149.)
            require((native_scale,native_offset)==(1.,0.) or (math.isclose(native_scale,scale,rel_tol=1e-7) and math.isclose(native_offset,offset,abs_tol=1e-7)),'Raster metadata conflicts with selected Landsat preset.')
            z[z==0]=np.nan
        if quantity=='class':require(scale==1 and offset==0,'Categorical and QA bands must not be radiometrically scaled.')
        z=z*scale+offset
        require(not np.isinf(z).any(),'Band calibration overflow.')
        valid=np.isfinite(z);v=z[valid]
        require(not len(v) or np.max(abs(v))<=1e100,'Calibrated values exceed numerical range.')
        if quantity=='reflectance':require(np.all((v>=-.2-1e-9)&(v<=1.6+1e-9)),'Reflectance outside supported physical tolerance [-0.2, 1.6]; check scale, offset and product level.')
        if quantity=='class':require(np.all(v==np.floor(v)) and np.all((v>=0)&(v<=65535)),'Class codes must be integers in [0,65535].')
        if quantity in {'power','radiance'}:require(np.all(v>=0),'Linear power and radiance cannot be negative.')
        if quantity=='kelvin':require(np.all(v>0),'Kelvin temperature must be positive.')
        if quantity=='emissivity':require(np.all((v>0)&(v<=1)),'Emissivity must be in (0,1].')
        if quantity=='transmittance':require(np.all((v>0)&(v<=1)),'Transmittance must be in (0,1].')
        if quantity=='nonnegative':require(np.all(v>=0),'Standard uncertainty must be nonnegative.')
        if quantity=='slope':require(np.all((v>=0)&(v<=90)),'Slope must be in [0,90] degrees.')
        if quantity=='aspect':require(np.all((v>=0)&(v<=360)),'Aspect must be in [0,360] degrees.')
        if quantity=='db':require(np.all((v>=-1000)&(v<=1000)),'Radar dB outside supported numeric range.')
        expected={'reflectance':'reflectance','class':'class','power':'linear_power','db':'dB','radiance':'radiance','kelvin':'K','emissivity':'unitless','transmittance':'unitless','nonnegative':'reflectance','slope':'degree','aspect':'degree'}.get(quantity)
        unit=expected or binding.unit or tag
        if quantity=='numeric':require(bool(unit),'Declare the physical unit of each numeric band.')
        if binding.unit and expected:require(binding.unit==expected,'Declared unit conflicts with required physical quantity.')
        # Explicit role binding asserts semantics; known incompatible tagged units cannot be overridden.
        if tag and quantity!='class':
            allowed={unit}
            if quantity in {'reflectance','emissivity','power','transmittance','nonnegative'}:allowed|={'unitless','1','dimensionless'}
            if quantity in {'slope','aspect'}:allowed|={'degrees','deg'}
            require(tag in allowed or encoding in {'landsat_sr','landsat_st','custom'},'GeoTIFF unit conflicts with selected band quantity.')
        g=Grid(source.name,z,a,ds.crs,unit,sha,b,ds.count,scale,offset)
        return g

def execute(body):
    method=BY_ID.get(body.operation);require(method is not None,'Unknown remote sensing operation.')
    roles=dict(method.roles)
    if method.id in SERIES_IDS:
        require(6<=len(body.times)<=64,'Supply 6–64 acquisition times.')
        roles={f'date{i+1}':'numeric' for i in range(len(body.times))}
    else:require(not body.times,'Acquisition times are only accepted by variable series methods.')
    require(set(body.bindings)==set(roles),'Bind every required spectral role exactly once.')
    require(set(body.parameters)<=set(p[0] for p in method.parameters),'Unknown remote sensing parameter.')
    params={}
    for name,_,default,lo,hi,integer in method.parameters:
        value=body.parameters.get(name,default)
        require(math.isfinite(value) and lo<=value<=hi and (not integer or float(value).is_integer()),'Invalid parameter: '+name)
        params[name]=int(value) if integer else float(value)
    require(sum(len(s.data) for s in body.sources)<=48_000_000,'Combined source payload exceeds budget.')
    raw=[];hashes=[]
    for source in body.sources:
        data=base64.b64decode(source.data,validate=True);require(len(data)<=24_000_000,'Source exceeds inline GeoTIFF budget.')
        raw.append(data);hashes.append(hashlib.sha256(data).hexdigest())
    grids={};provenance={};first=None;cells=0
    aligning=method.id in {'align_continuous','align_categorical'}
    if aligning:require(not body.quality,'Apply QA before or after explicit alignment, not during reprojection.')
    def load(binding,quantity,allow_mismatch=False):
        nonlocal first,cells
        i=binding.source;require(i<len(raw),'Source index does not exist.')
        g=read_band(body.sources[i],binding,quantity,raw[i],hashes[i])
        cells+=g.values.size;require(cells<=8_000_000,'Combined decoded cell budget exceeded.')
        if first is None:first=g
        elif not allow_mismatch:require(g.crs==first.crs and g.transform==first.transform and g.values.shape==first.values.shape,'All bands and QA rasters must be explicitly aligned to the same grid.')
        return g
    for name,quantity in roles.items():
        b=body.bindings[name];g=load(b,quantity,aligning and name=='source');grids[name]=g
        provenance[name]={'source':g.name,'sha256':g.sha256,'band':g.band,'quantity':quantity,'unit':g.unit,'scale':g.scale,'offset':g.offset,'encoding':b.encoding,'crs':str(g.crs),'shape':list(g.values.shape),'transform':list(g.transform)[:6]}
    quality=[]
    for q in body.quality:
        require(set(q.roles)<=set(roles),'Unknown quality mask target role.')
        g=load(Binding(source=q.source,band=q.band,encoding='raw'),'class')
        mask=quality_mask(g.values,q.scheme)==1
        targets=q.roles or list(roles)
        for name in targets:grids[name].values[~mask]=np.nan
        quality.append({'sha256':g.sha256,'band':g.band,'scheme':q.scheme,'roles':targets,'retained_mask_cells':int(mask.sum())})
    v={name:g.values for name,g in grids.items()};kind=method.id
    if any(q=='numeric' for q in roles.values()):
        units={grids[r].unit for r,q in roles.items() if q=='numeric'}
        require(len(units)==1,'Comparable numerical bands must share physical units.')
    if aligning:
        from rasterio.warp import reproject,Resampling
        target=grids['target'];source=grids['source'];out=np.full(target.values.shape,np.nan)
        if method.id=='align_continuous':require(source.unit!='class','Categorical rasters require nearest neighbor alignment.')
        reproject(source.values,out,src_transform=source.transform,src_crs=source.crs,src_nodata=np.nan,
                  dst_transform=target.transform,dst_crs=target.crs,dst_nodata=np.nan,
                  resampling=Resampling.bilinear if method.id=='align_continuous' else Resampling.nearest)
        out[~np.isfinite(target.values)]=np.nan
        v['source']=out
    common=np.logical_and.reduce([np.isfinite(z) for z in v.values()])
    unit=method.unit;rows=[];headers=[];meta={};out=None;rgb=None
    if unit in {'source','source/time'}:unit=next(iter(grids.values())).unit+('/time' if unit=='source/time' else '')
    if kind in {'true_color','false_color'}:
        rgb=rgb_product(kind,np.stack(list(v.values())),first,list(v));meta['display_channel_order']=list(v)
    elif aligning:
        out=v['source'];unit=grids['source'].unit;meta['resampling']='bilinear' if kind=='align_continuous' else 'nearest'
    elif kind=='calibrated_reflectance':out=v['band']
    elif kind=='ndvi_change':out=nd(v['nir_after'],v['red_after'])-nd(v['nir_before'],v['red_before'])
    elif kind=='dnbr':out=nd(v['nir_before'],v['swir_before'])-nd(v['nir_after'],v['swir_after'])
    elif kind=='surface_temperature_rte':out,meta=surface_temperature(v,params)
    elif kind=='topographic_c':out,meta=c_correction(v,params)
    elif kind=='ndvi_uncertainty':out,meta=ndvi_uncertainty(v,params)
    elif kind in {'change_vector','change_mahalanobis'}:out,meta=change_vectors(v,kind=='change_mahalanobis')
    elif kind=='spatial_lda':out,headers,rows,meta=spatial_classifier(v,first,params)
    elif kind in SERIES_IDS:
        out,meta=long_series(kind,np.stack(list(v.values())),body.times,params.get('period',365))
        headers=['time','valid_cells','mean'];rows=[[t,int(np.isfinite(z).sum()),float(np.nanmean(z)) if np.isfinite(z).any() else None] for t,z in zip(body.times,v.values())]
    elif method.group=='Optical':
        out=optical(kind,v,params);out[~common]=np.nan
        meta['reflectance_outside_0_1']={r:int(np.count_nonzero(np.isfinite(z)&((z<0)|(z>1)))) for r,z in v.items()}
    elif method.group=='Quality':out=quality_mask(v['qa'],kind)
    elif kind=='transition_matrix':
        require(first.is_meter and common.any(),'Transitions require common valid projected metre cells.')
        headers,rows,meta=transition(v['before'][common],v['after'][common],abs(first.transform.a*first.transform.e))
    elif kind in {'difference','relative_change','change_classes'}:
        delta=v['after']-v['before']
        if kind=='difference':out=delta
        elif kind=='relative_change':out=100*ratio(delta,abs(v['before']))
        else:out=np.where(common,np.where(delta>params['threshold'],2,np.where(delta< -params['threshold'],1,0)),np.nan)
    elif kind=='brightness_temperature':
        l=v['radiance'];out=np.divide(params['k2'],np.log1p(np.divide(params['k1'],l,out=np.full_like(l,np.nan),where=l>0)))
    elif kind=='emissivity_temperature':
        t=v['temperature'];e=v['emissivity'];den=1+params['wavelength_um']*1e-6*t/0.01438776877*np.log(e)
        out=np.divide(t,den,out=np.full_like(t,np.nan),where=den>0)
    elif kind=='temperature_celsius':out=v['temperature']-273.15
    elif kind=='sar_db':out=10*np.log10(np.where(v['power']>0,v['power'],np.nan))
    elif kind=='sar_linear':out=np.power(10,v['backscatter']/10)
    elif kind=='sar_ratio':out=ratio(v['cross'],v['co'])
    elif kind=='dualpol_rvi':out=4*ratio(v['cross'],v['co']+v['cross'])
    elif kind=='sar_gamma_map':out,meta=gamma_map(v['power'],params['radius'],params['enl'])
    elif kind=='sar_log_change':
        a,b=v['before'],v['after'];out=10*(np.log10(np.where(b>0,b,np.nan))-np.log10(np.where(a>0,a,np.nan)))
    elif kind=='sar_gamma0_flat':
        a=v['incidence'];out=np.divide(v['sigma0'],np.cos(np.deg2rad(a)),out=np.full(a.shape,np.nan),where=a<89)
    elif kind=='mad_distance':out,meta=mad_distance(v)
    elif kind=='sar_lee':out=lee_filter(v['power'],params['radius'],params['enl'])
    elif kind=='temporal_sen':out,meta=sen_slope(np.stack(list(v.values())),params)
    elif kind=='temporal_trend_se':out,meta=temporal_slope_se(np.stack(list(v.values())),params)
    elif kind.startswith('temporal_'):
        out,meta=temporal(kind,np.stack(list(v.values())),params)
    elif kind=='pca':
        out,headers,rows,meta=pca(np.stack(list(v.values())),common,params['component'])
    elif kind=='spectral_angle':
        a=np.stack([v[r] for r in ('red_before','nir_before','swir_before')])
        b=np.stack([v[r] for r in ('red_after','nir_after','swir_after')])
        cosine=ratio(np.sum(a*b,axis=0),np.linalg.norm(a,axis=0)*np.linalg.norm(b,axis=0))
        out=np.degrees(np.arccos(np.clip(cosine,-1,1)))
    elif kind=='minimum_distance':
        out,headers,rows,meta=classify(np.stack([v[r] for r in ('blue','green','red','nir')]),v['training'])
    elif kind in {'spectral_unmix','spectral_unmix_rmse'}:
        out,headers,rows,meta=unmix(np.stack([v[r] for r in ('blue','green','red','nir')]),v['training'],params.get('target_class'))
    elif kind=='stratified_accuracy':
        headers,rows,meta=stratified_accuracy(v['prediction'],v['reference'])
    elif kind=='classification_accuracy':
        require(common.any(),'No common valid reference cells.')
        headers,rows,meta=agreement(v['prediction'][common],v['reference'][common])
    else:raise FigureInputError('Unimplemented remote method.')
    product=rgb[0] if rgb else raster_product(kind,out,first.transform,first.crs,unit) if out is not None else None
    meta.update(input_valid_cells={r:int(np.isfinite(z).sum()) for r,z in v.items()},common_valid_cells=int(common.sum()))
    csv=csv_output(headers,rows)
    receipt={'schema':'geofathom-remote-sensing-1','operation':kind,'assumption':method.assumption,'parameters':params,
             'crs':str(first.crs),'grid_shape':list(first.values.shape),'transform':list(first.transform)[:6],
             'bands':provenance,'quality_masks':quality,'metrics':meta,'table_sha256':hashlib.sha256(csv.encode()).hexdigest(),
             'raster_sha256':product['sha256'] if product else None,'raster_summary':product['summary'] if product else None}
    result={'operation':kind,'receipt':receipt,'features':None,'raster':product,'preview':rgb[1] if rgb else raster_preview(product) if product else None,'columns':headers,'rows':rows,'csv':csv}
    plots=[{'title':'Publication RGB composite','recipe':'spectral_rgb','bindings':{},'csv':None,'raster':True,'bands':[1,2,3]}] if rgb else figure_sources(result,[])
    def add(title,recipe,bindings,table=None):
        plots.append({'title':title,'recipe':recipe,'bindings':bindings,'csv':csv if table is None else table,'raster':False})
    if kind=='pca':add('PCA explained variance','basic_column',{'x':'component','y':'explained_fraction'})
    if kind=='transition_matrix':add('Transition area by class pair','basic_column',{'x':'transition','y':'area_m2'},csv_text(['transition','area_m2'],[[str(a)+' → '+str(b),area] for a,b,_,area,_ in rows]) ) if len(rows)<=50 else None
    if kind in SERIES_IDS and any(row[2] is not None for row in rows):add('Acquisition mean time series','basic_line',{'x':'time','y':'mean'})
    if kind in {'classification_accuracy','spatial_lda'}:
        for key in ('precision','recall'):
            if any(r[headers.index(key)] is not None for r in rows):add('Class '+key,'basic_column',{'x':'class','y':key})
    if kind in {'minimum_distance','spectral_unmix','spectral_unmix_rmse'}:
        add('Training support by class','basic_column',{'x':'class','y':'training_cells'})
        if len(rows)<=12:add('Mean spectral signature by class','multi_line',{'x':'band','columns':[str(r[0]) for r in rows]},csv_text(['band',*[str(r[0]) for r in rows]],[[b,*[r[i+2] for r in rows]] for i,b in enumerate([1,2,3,4])]))
    if kind=='stratified_accuracy':add('Validation accuracy by mapped stratum','basic_column',{'x':'map_class','y':'within_stratum_accuracy'})
    result['figures']=plots
    json.dumps(result,allow_nan=False)
    return result

@router.get('/catalog')
def get_catalog():
    return {'schema':'geofathom-remote-sensing-1','operations':catalog(),'operation_count':len(BY_ID),
            'ai_tool':{'name':'execute_remote_sensing','endpoint':'/analysis/remote-sensing/run','input_schema':RemoteInput.model_json_schema()}}

@router.post('/run')
def run(body:RemoteInput):
    try:return execute(body)
    except (ValueError,TypeError,OverflowError,RuntimeError,OSError,RasterioError,np.linalg.LinAlgError) as e:
        raise HTTPException(422,detail=str(e)) from e
