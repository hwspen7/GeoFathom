"""Remote sensing API: typed band bindings, quality masks and reproducible products."""
import base64
import hashlib
import json
import math
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException,Header,Request
from pydantic import BaseModel,ConfigDict,Field
from rasterio.io import MemoryFile
from rasterio.errors import RasterioError
from terrain.studio_data import Grid,FigureInputError
from analysis.science_raster import require
from analysis.science_routes import raster_product,raster_preview,csv_output
from analysis.science_figures import figure_sources,csv_text
from .remote_catalog import BY_ID,catalog,SERIES_IDS,HYPER_IDS,LUT_IDS,GLOBAL_HYPER_IDS,JOINT_IDS
from .remote_spectral_inference import spectral_covariance,matched_filter,library_retrieval
from .remote_advanced_models import dualpol,brdf,support_fusion,cloud_model
from .remote_phase import reconstruct
from .remote_joint_models import joint_retrieval,two_anchor,calibrated_cloud
from .insar_decomposition import LOS_IDS,decompose
from .satellite_lut_wishart import WISHART_IDS,wishart_change
from .satellite_radiometry import ATMOS_IDS,atmospheric_error
from .remote_quality_composite import QUALITY_IDS,quality_composite
from .remote_satellite import gamma_change, area_overlap, SAR_GAMMA_IDS
from .remote_validation import aggregate_nested,continuous_reference,binary_reference
from .remote_band import read_calibrated
from .remote_fusion import fusion,canopy,unsupervised
from .remote_sar_complex import complex_products,calibrated_power,cloud_candidates,cloud_shadow
from .remote_temporal_models import seasonal_metrics,segmented_means
from .remote_hyperspectral import continuum_features
from .remote_physics import thermal_uncertainty,angular_sar,register_translation,register_subpixel
from .remote_classifiers import blocked_classifier,nested_svm
from .remote_inference import atmospheric_reflectance,robust_harmonization,irmad,cloud_buffer,series_break
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
    library:list[tuple[float,...]]=Field(default_factory=list,max_length=2048)


PrepareQuantity=Literal['reflectance','numeric','class','kelvin','power','db','radiance',
    'emissivity','transmittance','fraction','slope','aspect','nonnegative','wrapped_phase',
    'positive_gain','radiance_sd','fraction_sd','signed_power','distance_m','distance_sd_m']

class PrepareInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    sources:list[Source]=Field(min_length=1,max_length=64)
    bindings:dict[str,Binding]=Field(min_length=1,max_length=16)
    quantities:dict[str,PrepareQuantity]=Field(min_length=1,max_length=16)
    quality:list[Quality]=Field(default_factory=list,max_length=16)
    target:Binding
    target_quantity:PrepareQuantity='reflectance'
    resampling:Literal['nearest','bilinear']='bilinear'

@router.post('/prepare')
def prepare_bands(body:PrepareInput):
    from .remote_preprocess import prepare
    try:return prepare(body)
    except (ValueError,TypeError,OverflowError,RuntimeError,OSError,RasterioError) as e:
        raise HTTPException(422,detail=str(e)) from e

def read_band(source,binding,quantity,raw,sha,validity=None):
    with MemoryFile(raw) as mem,mem.open() as ds:
        require(ds.driver=='GTiff' and ds.crs,'Use georeferenced GeoTIFF sources.')
        require(1<=binding.band<=ds.count,'Selected band is outside the raster band count.')
        a=ds.transform;require(a.b==0 and a.d==0 and a.a>0 and a.e<0,'Explicitly align north-up raster grids first.')
        require(ds.width*ds.height<=2_000_000,'Raster exceeds two million cell limit.')
        if validity is not None:require(validity.shape==(ds.height,ds.width),'All bands and QA rasters must be explicitly aligned to the same grid.')
        b=binding.band;z,unit,scale,offset=read_calibrated(ds,binding,quantity,validity=validity)
        g=Grid(source.name,z,a,ds.crs,unit,sha,b,ds.count,scale,offset)
        return g

def execute(body):
    method=BY_ID.get(body.operation);require(method is not None,'Unknown remote sensing operation.')
    require(bool(body.library)==(method.id in LUT_IDS),'Supply a spectral library only for library retrieval methods.')
    if body.library:require(all(len(row)==(7 if method.id in JOINT_IDS else 6) for row in body.library),'Incorrect spectral library row width.')
    roles=dict(method.roles)
    if method.id in SERIES_IDS:
        require(6<=len(body.times)<=64,'Supply 6–64 acquisition times.')
        roles={f'date{i+1}':'numeric' for i in range(len(body.times))}
    elif method.id in HYPER_IDS:
        require(6<=len(body.times)<=64,'Supply 6–64 wavelength values in nm.')
        roles={f'band{i+1}':'reflectance' for i in range(len(body.times))}
    else:require(not body.times,'Acquisition times or wavelengths are only accepted by variable-axis methods.')
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
    aligning=method.id in {'align_continuous','align_categorical','align_area_mean','align_area_coverage','align_overlap_mean','align_overlap_coverage'}
    if aligning:require(not body.quality,'Apply QA before or after explicit alignment, not during reprojection.')
    quality_inputs=[];native_masks={}
    for q in body.quality:
        require(set(q.roles)<=set(roles),'Unknown quality mask target role.')
        require(q.source<len(raw),'Source index does not exist.')
        g=read_band(body.sources[q.source],Binding(source=q.source,band=q.band,encoding='raw'),'class',raw[q.source],hashes[q.source])
        cells+=g.values.size;require(cells<=8_000_000,'Combined decoded cell budget exceeded.')
        mask=quality_mask(g.values,q.scheme)==1
        for name in q.roles or list(roles):
            if name in native_masks:
                require(native_masks[name].shape==mask.shape,'All bands and QA rasters must be explicitly aligned to the same grid.')
                native_masks[name]&=mask
            else:native_masks[name]=mask.copy()
        quality_inputs.append((q,g,mask))
    def load(binding,quantity,allow_mismatch=False,validity=None):
        nonlocal first,cells
        i=binding.source;require(i<len(raw),'Source index does not exist.')
        g=read_band(body.sources[i],binding,quantity,raw[i],hashes[i],validity)
        cells+=g.values.size;require(cells<=8_000_000,'Combined decoded cell budget exceeded.')
        if first is None:first=g
        elif not allow_mismatch:require(g.crs==first.crs and g.transform==first.transform and g.values.shape==first.values.shape,'All bands and QA rasters must be explicitly aligned to the same grid.')
        return g
    for name,quantity in roles.items():
        b=body.bindings[name];g=load(b,quantity,aligning and name=='source',native_masks.get(name));grids[name]=g
        provenance[name]={'source':g.name,'sha256':g.sha256,'band':g.band,'quantity':quantity,'unit':g.unit,'scale':g.scale,'offset':g.offset,'encoding':b.encoding,'crs':str(g.crs),'shape':list(g.values.shape),'transform':list(g.transform)[:6]}
    quality=[]
    for q,g,mask in quality_inputs:
        require(g.crs==first.crs and g.transform==first.transform and g.values.shape==first.values.shape,'All bands and QA rasters must be explicitly aligned to the same grid.')
        targets=q.roles or list(roles)
        for name in targets:grids[name].values[~mask]=np.nan
        quality.append({'sha256':g.sha256,'band':g.band,'scheme':q.scheme,'roles':targets,'retained_mask_cells':int(mask.sum())})
    v={name:g.values for name,g in grids.items()};kind=method.id
    if any(q=='numeric' for q in roles.values()):
        units={grids[r].unit for r,q in roles.items() if q=='numeric'}
        require(len(units)==1,'Comparable numerical bands must share physical units.')
    alignment_meta={}
    if kind in {'align_overlap_mean','align_overlap_coverage'}:
        require(grids['source'].unit!='class','Area means require continuous measurements.')
        v['source'],alignment_meta=area_overlap(grids['source'],grids['target'],params,kind)
    elif kind in {'align_area_mean','align_area_coverage'}:
        require(grids['source'].unit!='class','Area means require continuous measurements.')
        v['source'],alignment_meta=aggregate_nested(grids['source'],grids['target'],params,kind)
    elif aligning:
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
        out=v['source'];unit='fraction' if kind in {'align_area_coverage','align_overlap_coverage'} else grids['source'].unit
        meta.update(alignment_meta);meta['resampling']='exact_overlap' if kind.startswith('align_overlap_') else 'nested_area' if kind.startswith('align_area_') else 'bilinear' if kind=='align_continuous' else 'nearest'
    elif kind in LOS_IDS:out,meta=decompose(v,params,kind)
    elif kind in WISHART_IDS:out,meta=wishart_change(v,params,kind)
    elif kind in ATMOS_IDS:out,meta=atmospheric_error(v,params,kind)
    elif kind in QUALITY_IDS:out,meta=quality_composite(v,params,kind)
    elif kind in SAR_GAMMA_IDS:out,meta=gamma_change(v,params,kind)
    elif kind in {'insar_phase_wls','insar_relative_range'}:
        if kind=='insar_relative_range':require(params['range_sign'] in (-1,1),'Range sign must be +1 or -1.')
        out,meta=reconstruct(v,params,kind)
    elif kind in {'sar_dual_entropy','sar_dual_purity','sar_dual_minor_fraction'}:out,meta=dualpol(v,kind)
    elif kind=='brdf_ross_li':out,meta=brdf(v,params)
    elif kind=='fusion_support_temporal':
        require(first.is_meter,'Support fusion requires a projected metre grid.')
        out,meta=support_fusion(v,params)
    elif kind in {'cloud_probability_model','shadow_probability_model'}:out,headers,rows,meta=cloud_model(v,first,params,kind)
    elif kind=='continuous_reference_error':out,headers,rows,meta=continuous_reference(v)
    elif kind=='binary_reference_error':out,headers,rows,meta=binary_reference(v)
    elif kind=='calibrated_reflectance':out=v['band']
    elif kind=='ndvi_change':out=nd(v['nir_after'],v['red_after'])-nd(v['nir_before'],v['red_before'])
    elif kind=='dnbr':out=nd(v['nir_before'],v['swir_before'])-nd(v['nir_after'],v['swir_after'])
    elif kind in {'fusion_gls','fusion_gls_sd','fusion_discrepancy'}:
        require(all(np.all(z[np.isfinite(z)]>0) for z in (v['first_sd'],v['second_sd'])),'Fusion standard deviations must be positive.')
        out,meta=fusion(v,params,kind)
    elif kind in {'canopy_lai','canopy_fpar_proxy'}:out,meta=canopy(v,params,kind)
    elif kind in {'spectral_kmeans','spectral_kmeans_distance'}:out,headers,rows,meta=unsupervised(v,params,kind)
    elif kind=='atmospheric_reflectance':out,meta=atmospheric_reflectance(v)
    elif kind=='robust_harmonization':out,meta=robust_harmonization(v,params)
    elif kind=='irmad':out,headers,rows,meta=irmad(v,params)
    elif kind=='cloud_buffer':out,meta=cloud_buffer(v['qa'],params['radius'])
    elif kind in {'lst_uncertainty','lst_correlated_uncertainty'}:out,meta=thermal_uncertainty(v,params)
    elif kind in {'sar_terrain_volume','sar_terrain_validity'}:out,meta=angular_sar(v,params,kind=='sar_terrain_validity')
    elif kind=='register_subpixel':out,meta=register_subpixel(v,params)
    elif kind=='register_translation':out,meta=register_translation(v,params)
    elif kind=='surface_temperature_rte':out,meta=surface_temperature(v,params)
    elif kind=='topographic_c':out,meta=c_correction(v,params)
    elif kind=='ndvi_uncertainty':out,meta=ndvi_uncertainty(v,params)
    elif kind in {'change_vector','change_mahalanobis'}:out,meta=change_vectors(v,kind=='change_mahalanobis')
    elif kind in {'spatial_rf_cv','spatial_svm_cv','spatial_lda_cv'}:out,headers,rows,meta=blocked_classifier(v,first,params,kind)
    elif kind=='spatial_nested_svm':out,headers,rows,meta=nested_svm(v,first,params)
    elif kind=='spatial_lda':out,headers,rows,meta=spatial_classifier(v,first,params)
    elif kind in {'fusion_two_anchor','fusion_anchor_disagreement'}:
        require(first.is_meter,'Support fusion requires a projected metre grid.')
        out,headers,rows,meta=two_anchor(v,params,kind)
    elif kind in {'cloud_calibrated_probability','shadow_calibrated_probability'}:out,headers,rows,meta=calibrated_cloud(v,first,params,kind)
    elif kind in LUT_IDS:
        if kind in JOINT_IDS:out,headers,rows,meta=joint_retrieval(v,body.library,params,kind)
        else:out,meta=library_retrieval(v,body.library,params,kind)
        meta['library_sha256']=hashlib.sha256(json.dumps(body.library,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        meta['library_inputs']={'columns':(['lai','cab','prior','blue','green','red','nir'] if kind in JOINT_IDS else ['lai','prior','blue','green','red','nir']),'rows':body.library}
    elif kind=='spectral_matched_filter':out,meta=matched_filter(v,params)
    elif kind in GLOBAL_HYPER_IDS:out,headers,rows,meta=spectral_covariance(np.stack(list(v.values())),body.times,kind,params)
    elif kind in HYPER_IDS:
        out,headers,rows,meta=continuum_features(np.stack(list(v.values())),body.times,kind,params)
    elif kind in SERIES_IDS:
        stack=np.stack(list(v.values()))
        if kind.startswith('season_'):out,meta=seasonal_metrics(stack,body.times,params,kind)
        elif kind.startswith('segmented_'):out,meta=segmented_means(stack,body.times,params,kind)
        elif kind.startswith('series_break_'):out,meta=series_break(stack,body.times,params['min_segment'],kind)
        else:out,meta=long_series(kind,stack,body.times,params.get('period',365))
        headers=['time','valid_cells','mean'];rows=[[t,int(np.isfinite(z).sum()),float(np.nanmean(z)) if np.isfinite(z).any() else None] for t,z in zip(body.times,v.values())]
    elif method.group=='Optical':
        out=optical(kind,v,params);out[~common]=np.nan
        meta['reflectance_outside_0_1']={r:int(np.count_nonzero(np.isfinite(z)&((z<0)|(z>1)))) for r,z in v.items()}
    elif kind in {'sentinel_clear','landsat_clear','landsat_unsaturated'}:out=quality_mask(v['qa'],kind)
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
    elif kind=='sar_calibrated_power':out,meta=calibrated_power(v)
    elif kind in {'insar_wrapped_phase','insar_coherence'}:out,meta=complex_products(v,params,kind)
    elif kind in {'cloud_shadow_candidates','cloud_shadow_clear'}:out,meta=cloud_shadow(v,first,params,kind=='cloud_shadow_clear')
    elif kind=='cloud_candidates':out,meta=cloud_candidates(v,params)
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
    if kind=='irmad':add('Canonical correlation convergence','multi_line',{'x':'iteration','columns':['rho1','rho2','rho3']})
    if kind in {'spatial_rf_cv','spatial_svm_cv','spatial_lda_cv'}:
        add('Spatial fold accuracy','basic_column',{'x':'fold','y':'accuracy'})
        add('Spatial fold balanced accuracy','basic_column',{'x':'fold','y':'balanced_accuracy'})
        add('Spatial fold sample support','basic_column',{'x':'fold','y':'validation_cells'})
    if kind=='spectral_endmembers':
        for i in range(params['endmembers']):
            add('Endmember '+str(i+1)+' candidate spectrum','basic_line',{'x':'wavelength_nm','y':'reflectance'},csv_text(headers,[r for r in rows if r[0]==i+1]))
    if kind=='spatial_nested_svm':
        add('Nested spatial outer-fold accuracy','basic_column',{'x':'fold','y':'accuracy'})
        add('Nested spatial selected C','basic_column',{'x':'fold','y':'selected_c'})
    if kind in {'spectral_kmeans','spectral_kmeans_distance'}:
        add('Spectral cluster population','basic_column',{'x':'cluster','y':'cells'})
        for i,row in enumerate(rows):add('Cluster '+str(i+1)+' mean spectrum','basic_line',{'x':'band','y':'reflectance'},csv_text(['band','reflectance'],[[j+1,z] for j,z in enumerate(row[2:])]))
    if kind=='continuous_reference_error':add('Reference residual quantiles','basic_line',{'x':'quantile','y':'residual'})
    if kind=='binary_reference_error':add('Reference error by outcome','basic_column',{'x':'outcome','y':'cells'})
    if kind in {'cloud_probability_model','shadow_probability_model'}:
        add('Spatial cloud probability Brier score','basic_column',{'x':'fold','y':'brier'})
        add('Spatial cloud probability log loss','basic_column',{'x':'fold','y':'log_loss'})
    if kind in JOINT_IDS:
        for label in ('LAI','Cab'):
            add(label+' scene-average posterior mass','remote_posterior_marginal',{'x':'value','y':'posterior_mass'},csv_text(headers,[r for r in rows if r[0]==label]))
        add('Joint LAI and chlorophyll posterior','remote_joint_posterior',{'x':'lai','y':'cab','z':'mass'},csv_text(['lai','cab','mass'],meta['joint_posterior']))
    if kind in {'fusion_two_anchor','fusion_anchor_disagreement'}:
        add('Signed anchor disagreement quantiles','remote_anchor_quantiles',{'x':'quantile','y':'anchor_difference'})
    if kind in {'cloud_calibrated_probability','shadow_calibrated_probability'}:
        add('Outer-fold probability reliability','remote_reliability',{'x':'predicted','y':'observed','z':'cells'},csv_text(['predicted','observed','cells'],meta['reliability']))
        add('Outer-fold ROC curve','remote_roc',{'x':'fpr','y':'tpr'},csv_text(['fpr','tpr'],meta['roc']))
        add('Outer-fold confusion matrix','basic_table_heatmap',{'x':'reference','columns':['clear','cloud','shadow']},csv_text(['reference','clear','cloud','shadow'],[[label,*r] for label,r in zip(('clear','cloud','shadow'),meta['oof_confusion_matrix'])]))
        add('Raw versus calibrated fold log loss','multi_line',{'x':'fold','columns':['raw_log_loss','calibrated_log_loss']})
    if kind=='spectral_mnf':add('MNF signal to noise variance ratio','basic_column',{'x':'component','y':'variance_ratio'})
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


class SceneCropInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    collection:Literal['sentinel-2-l2a','sentinel-2-c1-l2a']
    item_id:str=Field(min_length=8,max_length=140)
    bbox:tuple[float,float,float,float]
    roles:list[str]=Field(min_length=1,max_length=8)

@router.post('/scene-crop')
def scene_crop(body:SceneCropInput,request:Request,token:str|None=Header(default=None,alias='X-GeoFathom-Admin-Token')):
    from imagery.routes import require_raster_import
    from imagery.remote_scene import read_scene
    import httpx
    require_raster_import(request,token)
    try:return read_scene(body.collection,body.item_id,body.bbox,body.roles)
    except (ValueError,TypeError,RuntimeError,OSError,RasterioError,httpx.HTTPError) as e:raise HTTPException(422,detail=str(e)) from e
