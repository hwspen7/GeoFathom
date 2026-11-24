"""Independent spatiotemporal workbench with explicit dated raster bindings."""
import base64,hashlib,math,json
import numpy as np
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from rasterio.errors import RasterioError
from terrain.studio_data import FigureInputError
from imagery.remote_routes import Source,Binding,Quality,read_band
from imagery.remote_kernels import quality_mask
from imagery.remote_research import long_series
from imagery.remote_temporal_models import seasonal_metrics,segmented_means
from imagery.remote_inference import series_break
from .spacetime_state import kalman,permutation_lag
from .spacetime_modes import eof,block_trend
from .spacetime_kriging import kriging
from .spacetime_change import harmonic_break,events
from .spacetime_hotspots import hotspot
from .spacetime_panel import panel
from .spacetime_dynamic import dynamic
from .spacetime_multibreak import multi_break
from .spacetime_gtwr import gtwr
from .spacetime_extremes import extremes,track
from analysis.science_raster import require
from analysis.science_routes import raster_product,raster_preview
from analysis.science_figures import csv_text
from .spacetime_models import trend,temporal,forecast,spatial_lag,variogram

router=APIRouter(prefix='/analysis/spatiotemporal',tags=['spatiotemporal science'])
# parameter = (default,minimum,maximum,integer)
P={'minimum_observations':(6,3,64,True),'lag':(1,1,32,True),'threshold':(0,-1e50,1e50,False),'horizon':(30,.000001,1e7,False),'radius':(3,1,20,True),'period':(365,.000001,1e7,False),'fraction':(.5,.01,.99,False),'minimum_amplitude':(.01,0,1e50,False),'min_segment':(3,2,32,True),'penalty':(1,.000001,1e50,False),'process_variance':(.01,1e-20,1e50,False),'observation_variance':(.1,1e-20,1e50,False),'initial_velocity_variance':(1,1e-20,1e50,False),'permutations':(199,19,999,True),'seed':(42,0,2147483647,True),'mode':(1,1,64,True),'block_length':(3,2,21,True),'spatial_range':(100,1e-6,1e8,False),'temporal_range':(30,1e-6,1e8,False),'nugget_ratio':(.1,1e-6,10,False),'sample_limit':(128,12,256,True),'fit_covariance':(0,0,1,True),'holdout_dates':(2,2,32,True),'buffer_cells':(0,0,100,True),'bic_threshold':(6,0,1000,False),'maximum_gap':(30,.000001,1e9,False),'alpha':(.05,.001,.2,False),'block_cells':(2,1,1000,True),'interaction':(.5,.05,1,False),'target_date':(3,1,64,True),'trajectory_limit':(8,1,16,True),'max_breaks':(2,1,5,True),'effective_samples':(10,4,100,True),'local_sample_limit':(256,16,512,True),'coefficient_index':(1,1,3,True),'return_period':(20,1.01,10000,False),'minimum_voxels':(2,1,10000,True),'extreme_minimum':(10,8,64,True),'fit_interaction':(0,0,1,True),'auto_bandwidth':(0,0,1,True)}
KALMAN_P=('minimum_observations','horizon','process_variance','observation_variance','initial_velocity_variance')
KRIGING_P=('spatial_range','temporal_range','nugget_ratio','sample_limit','fit_covariance','seed')
BREAK_P=('period','min_segment','bic_threshold')
EVENT_P=('threshold','maximum_gap','minimum_observations')
HOT_P=('radius','permutations','seed','alpha')
UNIVERSAL_P=KRIGING_P+('interaction','fit_interaction')
RTS_P=('minimum_observations','process_variance','observation_variance','initial_velocity_variance','target_date')
FITTED_P=('minimum_observations','process_variance','observation_variance','initial_velocity_variance','holdout_dates','trajectory_limit','seed')
MULTI_P=('period','min_segment','max_breaks','bic_threshold')
GTWR_P=('spatial_range','temporal_range','effective_samples','local_sample_limit','seed','auto_bandwidth')
METHODS={
 'gev_shape':('Extreme value statistics','GEV block maxima shape',('block_length','extreme_minimum','return_period')),
 'gev_return_level':('Extreme value statistics','GEV block return level',('block_length','extreme_minimum','return_period')),
 'gpd_shape':('Extreme value statistics','GPD threshold excess shape',('threshold','extreme_minimum','return_period')),
 'gpd_return_level':('Extreme value statistics','GPD acquisition return level',('threshold','extreme_minimum','return_period')),
 'tracked_latest_id':('Space-time events','Latest observed event family ID',('threshold','maximum_gap','minimum_voxels')),
 'tracked_span':('Space-time events','Maximum connected event span',('threshold','maximum_gap','minimum_voxels')),
 'tracked_peak_area':('Space-time events','Maximum connected event peak area',('threshold','maximum_gap','minimum_voxels')),
 'gtwr_coefficient':('Space-time regression','GTWR local covariate coefficient',GTWR_P+('coefficient_index',)),
 'gtwr_support':('Space-time regression','GTWR effective local sample support',GTWR_P+('coefficient_index',)),
 'gtwr_holdout_rmse':('Joint validation','GTWR joint space-time holdout RMSE',GTWR_P+('holdout_dates','buffer_cells')),
 'rts_level':('State space','RTS smoothed latent level',RTS_P),
 'rts_velocity':('State space','RTS smoothed latent velocity',RTS_P),
 'rts_sd':('State space','RTS conditional latent SD',RTS_P),
 'fitted_state_rmse':('Prediction validation','Training-fitted state model holdout RMSE',FITTED_P),
 'fitted_state_skill':('Prediction validation','Training-fitted state model persistence skill',FITTED_P),
 'multi_harmonic_count':('Structural change','Multiple seasonal structural break count',MULTI_P),
 'multi_harmonic_bic':('Structural change','Multi-segment BIC improvement',MULTI_P),
 'multi_harmonic_first':('Structural change','First seasonal structural break',MULTI_P),
 'multi_harmonic_last':('Structural change','Last seasonal structural break',MULTI_P),
 'st_universal_mean':('Joint geostatistics','Nonseparable universal kriging forecast',UNIVERSAL_P+('horizon',)),
 'st_universal_sd':('Joint geostatistics','Nonseparable universal kriging observation SD',UNIVERSAL_P+('horizon',)),
 'st_universal_holdout_rmse':('Joint validation','Universal kriging joint holdout RMSE',UNIVERSAL_P+('holdout_dates','buffer_cells')),
 'st_universal_holdout_coverage':('Joint validation','Universal kriging joint holdout coverage',UNIVERSAL_P+('holdout_dates','buffer_cells')),
 'st_universal_holdout_bias':('Joint validation','Universal kriging joint holdout bias',UNIVERSAL_P+('holdout_dates','buffer_cells')),
 'hotspot_latest_z':('Space-time hotspots','Latest local Gi-star score',HOT_P),
 'hotspot_latest_p':('Space-time hotspots','Latest trajectory-permutation maxT probability',HOT_P),
 'hotspot_hot_fraction':('Space-time hotspots','Significant hot-date fraction',HOT_P),
 'hotspot_cold_fraction':('Space-time hotspots','Significant cold-date fraction',HOT_P),
 'hotspot_class':('Space-time hotspots','Hot and cold persistence classes',HOT_P),
 'panel_spatial_effect':('Space-time regression','Two-way panel spatial fixed effect',('block_cells',)),
 'panel_residual_rmse':('Space-time regression','Two-way panel residual RMSE',('block_cells',)),
 'panel_latest_residual':('Space-time regression','Two-way panel latest residual',('block_cells',)),
 'harmonic_break_bic':('Structural change','Seasonal structural break BIC improvement',BREAK_P),
 'harmonic_break_flag':('Structural change','Seasonally adjusted break selection',BREAK_P),
 'harmonic_break_time':('Structural change','Seasonal structural break time',BREAK_P),
 'harmonic_break_level':('Structural change','Deseasonalized break level shift',BREAK_P),
 'harmonic_break_amplitude':('Structural change','Seasonal amplitude change at break',BREAK_P),
 'event_count':('Temporal extremes','Observed exceedance run count',EVENT_P),
 'event_longest_span':('Temporal extremes','Longest observed exceedance span',EVENT_P),
 'event_total_span':('Temporal extremes','Total observed exceedance span',EVENT_P),
 'event_integrated_excess':('Temporal extremes','Integrated excess across observed runs',EVENT_P),
 'st_kriging_mean':('Joint geostatistics','Space-time ordinary kriging forecast',KRIGING_P+('horizon',)),
 'st_kriging_sd':('Joint geostatistics','Space-time kriging observation SD',KRIGING_P+('horizon',)),
 'st_holdout_rmse':('Joint validation','Joint space and future-time holdout RMSE',KRIGING_P+('holdout_dates','buffer_cells')),
 'st_holdout_coverage':('Joint validation','Joint holdout empirical 95% coverage',KRIGING_P+('holdout_dates','buffer_cells')),
 'st_holdout_bias':('Joint validation','Joint holdout signed prediction bias',KRIGING_P+('holdout_dates','buffer_cells')),
 'eof_mode':('Space-time modes','Empirical orthogonal spatial mode',('mode',)),
 'eof_reconstruction_rmse':('Space-time modes','EOF truncated reconstruction RMSE',('mode',)),
 'eof_local_skill':('Space-time modes','Local EOF reconstruction skill',('mode',)),
 'block_trend_p':('Trend inference','Circular block-bootstrap trend probability',('permutations','seed','block_length')),
 'block_trend_by':('Trend inference','Block-bootstrap trend BY adjustment',('permutations','seed','block_length')),
 'kalman_level':('State space','Filtered terminal level',KALMAN_P),
 'kalman_velocity':('State space','Filtered terminal rate',KALMAN_P),
 'kalman_forecast':('State space','Irregular-time state-space forecast',KALMAN_P),
 'kalman_forecast_sd':('State space','Conditional state-space observation SD',KALMAN_P),
 'kalman_hindcast_rmse':('Prediction validation','Prequential state-space RMSE',KALMAN_P),
 'kalman_hindcast_skill':('Prediction validation','Prequential state-space skill',KALMAN_P),
 'lag_permutation':('Space-time inference','Lagged spatial exchangeability test',('permutations','seed')),
 'season_peak':('Phenology','Harmonic peak phase',('period','fraction','minimum_amplitude')),
 'season_start':('Phenology','Harmonic seasonal start phase',('period','fraction','minimum_amplitude')),
 'season_end':('Phenology','Harmonic seasonal end phase',('period','fraction','minimum_amplitude')),
 'season_duration':('Phenology','Harmonic seasonal duration',('period','fraction','minimum_amplitude')),
 'segmented_count':('Change detection','Penalized multiple change count',('min_segment','penalty')),
 'segmented_first_break':('Change detection','First penalized break time',('min_segment','penalty')),
 'series_break_time':('Change detection','Single mean-shift time',('min_segment',)),
 'series_break_jump':('Change detection','Single mean-shift magnitude',('min_segment',)),
 'series_break_strength':('Change detection','Single mean-shift explained variance',('min_segment',)),
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
    covariates:list[Binding]=Field(default_factory=list,max_length=192)
    quality:list[Quality]=Field(default_factory=list,max_length=64)
    parameters:dict[str,float]=Field(default_factory=dict,max_length=12)
    time_unit:str=Field(default='day',min_length=1,max_length=24)
    time_origin:str=Field(default='',max_length=80)

@router.get('/catalog')
def catalog():
    return {'operations':[{'id':k,'group':g,'title':title,'requires_covariate':k.startswith(('panel_','gtwr_')),'parameters':[{'name':p,'label':p.replace('_',' '),'default':6 if p=='min_segment' and k.startswith(('harmonic_break_','multi_harmonic_')) else P[p][0],'minimum':P[p][1],'maximum':P[p][2],'integer':P[p][3]} for p in params]} for k,(g,title,params) in METHODS.items()],'operation_count':len(METHODS),'input_schema':CubeInput.model_json_schema()}

def execute(body):
    require(body.operation in METHODS,'Unknown space-time method.')
    kind=body.operation;n=len(body.times);t=np.asarray(body.times,float)
    require(n==len(body.observations) and np.isfinite(t).all() and np.all(np.diff(t)>0) and 1e-9<=t[-1]-t[0]<=1e9,'One strictly increasing finite time per observation, with bounded time span.')
    require(np.min(np.diff(t))>=1e-9,'Time increments too small; rescale time units.')
    params=METHODS[kind][2];require(set(body.parameters)<=set(params),'Unknown method parameter.')
    p={}
    for key in params:
        default,lo,hi,integer=P[key];default=6 if key=='min_segment' and kind.startswith(('harmonic_break_','multi_harmonic_')) else default;x=body.parameters.get(key,default)
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
    require(bool(body.covariates)==kind.startswith(('panel_','gtwr_')),'Provide covariate observations only for regression.')
    covariate=None;covariate_receipt=[]
    if body.covariates:
        groups=len(body.covariates)//n
        require(len(body.covariates)==groups*n and (groups==1 if kind.startswith('panel_') else 1<=groups<=3) and groups*n*first.values.size<=2_000_000,'Provide complete dated covariate groups within work budget.')
        cv=[];cu=None
        for index,b in enumerate(body.covariates):
            if index%n==0:cu=None
            quantity='reflectance' if b.encoding=='landsat_sr' else 'kelvin' if b.encoding=='landsat_st' else 'numeric'
            g=read(b,quantity);cu=cu or g.unit;require(g.unit==cu,'Covariate units must match across dates.')
            cv.append(g.values);covariate_receipt.append({'source_sha256':sha[b.source],'binding':b.model_dump(),'unit':g.unit,'scale':g.scale,'offset':g.offset})
        covariate=np.stack(cv).reshape(groups,n,*first.values.shape);require(np.isfinite(covariate).any() and np.max(np.abs(covariate[np.isfinite(covariate)]))<=1e50,'Invalid covariate values; rescale.')
    stack=np.stack(arrays);require(np.isfinite(stack).any(),'No valid cube observations.')
    require(np.max(np.abs(stack[np.isfinite(stack)]))<=1e50,'Rescale cube values to at most 1e50 before statistical analysis.')
    out=None;rows=[];cols=[];meta={};figures=[];unit=first.unit
    def plot(title,recipe,cols,rows,**bindings):
        figures.append({'title':title,'recipe':recipe,'bindings':bindings,'csv':csv_text(cols,rows),'raster':False})
    if kind in ('sen','mk_p','mk_by_q'):
        out,meta=trend(stack,t,kind);unit=unit+'/'+body.time_unit if kind=='sen' else 'probability'
    elif kind in ('coverage','exceedance','lag_correlation'):
        out,meta=temporal(stack,t,kind,p);unit='index' if kind=='lag_correlation' else 'fraction'
    elif kind.startswith(('forecast_','hindcast_')):
        out,cols,rows,meta=forecast(stack,t,kind,p);unit='index' if kind=='hindcast_skill' else unit
        if len(rows)>=2:plot('Expanding-window forecast versus persistence error','multi_line',cols,rows,x='time',columns=['trend_rmse','persistence_rmse'])
    elif kind.startswith(('gev_','gpd_')):
        out,meta=extremes(stack,t,{**p,'minimum_observations':p['extreme_minimum']},kind)
        if kind.endswith('_shape'):unit='index'
    elif kind.startswith('tracked_'):
        out,cols,rows,meta=track(stack,t,first,p,kind);unit='class' if kind.endswith('_id') else 'm2' if kind.endswith('_area') else body.time_unit
        if rows:
            # A bounded figure subset; full component inventory remains in CSV.
            top=sorted(rows,key=lambda r:(-r[6],r[0]))[:50]
            plot('Largest 50 observed event peak areas','basic_column',cols,top,x='event',y='peak_area_m2')
            plot('Observed event span versus peak area','basic_scatter',cols,rows[:2000],x='span',y='peak_area_m2')
    elif kind.startswith(('rts_','fitted_state_')):
        out,cols,rows,meta=dynamic(stack,t,p,kind)
        if kind=='rts_velocity':unit=unit+'/'+body.time_unit
        if kind=='fitted_state_skill':unit='index'
        if len(rows)>=2:plot('Fixed-origin holdout versus persistence','multi_line',cols,rows,x='time',columns=['state_rmse','persistence_rmse'])
        if kind.startswith('fitted_'):plot('Training conditional likelihood fit','basic_column',['stage','nll'],[['initial',meta['initial_nll_per_observation']],['fitted',meta['fitted_nll_per_observation']]],x='stage',y='nll')
    elif kind.startswith('multi_harmonic_'):
        out,cols,rows,meta=multi_break(stack,t,p,kind);unit='count' if kind.endswith('_count') else 'index' if kind.endswith('_bic') else body.time_unit
        plot('Selected seasonal breakpoint count','basic_column',cols,rows,x='break_count',y='cells')
    elif kind.startswith('hotspot_'):
        out,cols,rows,meta=hotspot(stack,t,p,kind)
        unit='class' if kind=='hotspot_class' else 'probability' if kind.endswith('_p') else 'fraction' if kind.endswith('_fraction') else 'index'
        plot('Significant hot and cold cells through time','multi_line',cols,rows,x='acquisition',columns=['hot_cells','cold_cells'])
        plot('Trajectory permutation maximum statistic quantiles','basic_line',['quantile','maximum'],meta['null_maximum_quantiles'],x='quantile',y='maximum')
    elif kind.startswith('gtwr_'):
        out,cols,rows,meta=gtwr(stack,covariate,t,first,p,kind)
        if kind=='gtwr_support':unit='count'
        elif kind=='gtwr_coefficient':unit=unit+'/'+covariate_receipt[(p['coefficient_index']-1)*n]['unit']
        plot('GTWR effective local sample quantiles','basic_line',cols,rows,x='quantile',y='effective_samples')
        if meta.get('bandwidth_candidates'):
            candidates=[[f'{r[0]:g} / {r[1]:g}',r[-1]] for r in meta['bandwidth_candidates'] if r[-1] is not None]
            plot('Nested bandwidth validation RMSE','basic_column',['bandwidth','rmse'],candidates,x='bandwidth',y='rmse')
        if kind=='gtwr_holdout_rmse':plot('Joint holdout error against training mean','basic_column',['model','rmse'],[['GTWR',meta['rmse']],['training mean',meta['training_mean_rmse']]],x='model',y='rmse')
    elif kind.startswith('panel_'):
        out,cols,rows,meta=panel(stack,covariate[0],p,kind)
        plot('Time fixed effects','basic_line',cols,rows,x='acquisition',y='time_effect')
        plot('Panel residual RMSE through time','basic_line',cols,rows,x='acquisition',y='residual_rmse')
    elif kind.startswith('harmonic_break_'):
        out,meta=harmonic_break(stack,t,p,kind)
        if kind=='harmonic_break_time':unit=body.time_unit
        elif kind in ('harmonic_break_bic','harmonic_break_flag'):unit='index' if kind.endswith('_bic') else 'class'
    elif kind.startswith('event_'):
        out,cols,rows,meta=events(stack,t,p,kind)
        unit='count' if kind=='event_count' else unit+'*'+body.time_unit if kind=='event_integrated_excess' else body.time_unit
        plot('Observed event starts and active cells','multi_line',cols,rows,x='time',columns=['event_starts','active_cells'])
    elif kind.startswith(('st_kriging_','st_holdout_','st_universal_')):
        out,cols,rows,meta=kriging(stack,t,first,{**p,'universal':1} if kind.startswith('st_universal_') else p,kind)
        if kind.endswith('_coverage'):unit='fraction'
        if len(rows)>=2:plot('Joint holdout kriging versus training mean','multi_line',cols,rows,x='time',columns=['kriging_rmse','training_mean_rmse'])
        if rows:plot('Joint holdout empirical prediction coverage','basic_column',cols,rows,x='time',y='coverage_95')
    elif kind.startswith('eof_'):
        require(first.is_meter,'EOF requires a projected metre grid and equal native cell weights.')
        out,cols,rows,meta=eof(stack,p,kind);unit='index' if kind in ('eof_mode','eof_local_skill') else unit
        plot('EOF explained variance spectrum','basic_column',cols,rows,x='mode',y='explained_fraction')
        plot('EOF principal component time series','basic_line',['time','score'],list(zip(body.times,meta['temporal_scores'])),x='time',y='score')
    elif kind.startswith('block_trend_'):
        out,meta=block_trend(stack,t,p,kind);unit='probability'
    elif kind.startswith('kalman_'):
        out,cols,rows,meta=kalman(stack,t,p,kind)
        if kind=='kalman_velocity':unit=unit+'/'+body.time_unit
        if kind=='kalman_hindcast_skill':unit='index'
        if len(rows)>=2:plot('Prequential model versus persistence RMSE','multi_line',cols,rows,x='time',columns=['model_rmse','persistence_rmse'])
        if rows:plot('Normalized innovation diagnostic','basic_column',cols,rows,x='time',y='mean_normalized_innovation_squared')
    elif kind=='lag_permutation':
        cols,rows,meta=permutation_lag(stack,p)
        if len(rows)>=2:plot('Raw and multiplicity-adjusted randomization probabilities','multi_line',cols,rows,x='acquisition',columns=['p_value','by_q'])
    elif kind.startswith('season_'):
        out,meta=seasonal_metrics(stack,body.times,{'period':p['period'],'min_amplitude':p['minimum_amplitude'],'season_fraction':p['fraction']},kind);unit=body.time_unit
    elif kind.startswith('segmented_'):
        out,meta=segmented_means(stack,body.times,p,kind);unit='count' if kind=='segmented_count' else body.time_unit
    elif kind.startswith('series_break_'):
        out,meta=series_break(stack,body.times,p['min_segment'],kind)
        if kind=='series_break_time':unit=body.time_unit
        if kind=='series_break_strength':unit='fraction'
    elif kind=='space_time_lag':
        out,cols,rows,meta=spatial_lag(stack,kind,p);unit='index'
        if sum(r[-1] is not None for r in rows)>=2:plot('Lagged neighborhood association by acquisition','basic_line',cols,[r for r in rows if r[-1] is not None],x='acquisition',y='lag_product')
    elif kind=='space_time_variogram':
        cols,rows,meta=variogram(stack,t,first,p)
        for direction in ('east','south','temporal'):
            sub=[r for r in rows if r[0]==direction]
            if direction=='temporal':
                if sub:plot('Pure temporal semivariance','basic_scatter',cols,sub,x='time_lag',y='semivariance')
                continue
            # Preserve the temporal dimension, not overlapping unrelated
            # distances on a single scatter. Heatmap uses only complete bins.
            distances=sorted({r[1] for r in sub});lags=sorted({r[2] for r in sub})
            values={(r[1],r[2]):r[4] for r in sub}
            for lag in lags:
                group=[r for r in sub if r[2]==lag]
                if len(group)>=2:plot(f'{direction} semivariance at time lag {lag:g}','basic_line',cols,group,x='space_m',y='semivariance')
            if len(distances)>=2 and len(lags)>=2:
                for start in range(0,len(distances),12):
                    ds=distances[start:start+12];names=[f'{d:g} m' for d in ds]
                    matrix=[[str(lag),*[values[d,lag] for d in ds]] for lag in lags if all((d,lag) in values for d in ds)]
                    if len(matrix)>=2:plot(direction+' space-time semivariance matrix','basic_table_heatmap',['time_lag',*names],matrix,x='time_lag',columns=names)
    else:
        out,meta=long_series(kind,stack,body.times,p.get('period',365))
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
    if out is not None and not np.isfinite(out).any():require(False,'No valid output cells meet the model assumptions.')
    product=raster_product(kind,out,first.transform,first.crs,unit) if out is not None else None
    if product:
        figures.insert(0,{'title':METHODS[kind][1]+' map','recipe':'raster_classes' if unit=='class' else 'raster_continuous','bindings':{},'csv':None,'raster':True})
        if not rows:cols=['quantile','value'];rows=product['summary']['quantiles']
    csv=csv_text(cols,rows)
    receipt={'table_sha256':hashlib.sha256(csv.encode()).hexdigest(),'raster_sha256':product['sha256'] if product else None,'schema':'geofathom-spatiotemporal','operation':kind,'crs':str(first.crs),'unit':unit,'times':body.times,'time_unit':body.time_unit,'time_origin':body.time_origin,'parameters':p,'covariate_quality_policy':'Covariate data must be independently quality-masked before import; response QA is applied only to response dates.' if body.covariates else None,'observations':bindings,'covariates':covariate_receipt,'quality':quality_receipt,'metrics':meta}
    result={'operation':kind,'receipt':receipt,'features':None,'raster':product,'preview':raster_preview(product) if product else None,'figures':figures,'columns':cols,'rows':rows,'csv':csv}
    json.dumps(result,allow_nan=False)
    return result

@router.post('/run')
def run(body:CubeInput):
    try:return execute(body)
    except (FigureInputError,ValueError,TypeError,OverflowError,RasterioError,np.linalg.LinAlgError) as e:raise HTTPException(422,detail=str(e)) from e
