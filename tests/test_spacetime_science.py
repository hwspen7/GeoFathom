"""Independent analytical references for the dated-cube workbench."""
import base64,hashlib,json,math
import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from scipy.special import ndtr
from terrain.studio_data import FigureInputError
from analysis.spacetime_routes import CubeInput,execute,METHODS
from analysis.spacetime_state import kalman
from analysis.spacetime_models import forecast

AFF=from_origin(500000,4500000,10,10)
CRS='EPSG:32617'
def source(a,aff=AFF,unit='index',scales=None,offsets=None):
    a=np.asarray(a,float)
    if a.ndim==2:a=a[None]
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',count=len(a),height=a.shape[1],width=a.shape[2],dtype='float64',crs=CRS,transform=aff,nodata=np.nan) as ds:
            ds.write(a)
            if unit:ds.update_tags(TERRAIN_UNIT=unit)
            if scales is not None:ds.scales=scales
            if offsets is not None:ds.offsets=offsets
        return {'name':'fixture','data':base64.b64encode(mem.read()).decode()}
def run(kind,a,t=None,p=None,**extra):
    n=len(a);body={'operation':kind,'sources':[source(a)],'observations':[{'source':0,'band':i+1,'unit':'index'} for i in range(n)],
        'times':list(range(n)) if t is None else list(t),'parameters':p or {},**extra}
    result=execute(CubeInput(**body))
    json.dumps(result,allow_nan=False)
    assert hashlib.sha256(result['csv'].encode()).hexdigest()==result['receipt']['table_sha256']
    return result
def grid(r):
    raw=base64.b64decode(r['raster']['data']);assert hashlib.sha256(raw).hexdigest()==r['receipt']['raster_sha256']
    with MemoryFile(raw) as mem,mem.open() as ds:
        assert ds.crs.to_string()==CRS and ds.transform==AFF
        return ds.read(1)

@pytest.mark.parametrize('kind',sorted(METHODS))
def test_every_spacetime_method_reference(kind):
    t=np.arange(18,dtype=float);space=np.arange(1,13,dtype=float).reshape(3,4);linear=5+t[:,None,None]*space
    params={};a=linear.copy()
    if kind.startswith('season_') or kind in ('series_amplitude','series_harmonic_rmse'):
        a=5+.1*t[:,None,None]+2*np.cos(2*np.pi*(t[:,None,None]-2)/6)+np.zeros_like(linear);params={'period':6}
    elif kind.startswith(('segmented_','series_break_')):
        a=np.broadcast_to(np.repeat([2.,9.,9.],6)[:,None,None],linear.shape).copy()
        if kind.startswith('segmented_'):params={'penalty':1}
    elif kind.startswith('block_trend_'):params={'permutations':99,'block_length':3,'seed':11}
    elif kind=='lag_permutation':params={'permutations':19,'seed':11}
    elif kind.startswith('kalman_'):params={'horizon':2,'process_variance':.01,'observation_variance':.1,'initial_velocity_variance':1}
    elif kind.startswith('forecast_'):params={'horizon':2}
    elif kind=='exceedance':params={'threshold':10}
    if '_interval_' in kind:
        from scipy.stats import genextreme,genpareto
        prob=(np.arange(30)+.5)/30
        if kind.startswith('gev_'):a=np.repeat(genextreme.ppf(prob,0,loc=4,scale=2),2)[:,None,None];params={'block_length':2}
        else:a=np.r_[np.full(30,-1),genpareto.ppf(prob,0,scale=2)][:,None,None];params={'threshold':0}
        params.update(bootstrap_replicates=39,seed=12,return_period=20,extreme_minimum=8)
        r=run(kind,a,None,params);z=grid(r)
        assert np.isfinite(z).all() and r['receipt']['metrics']['minimum_successful_refits']>=32
        return
    if kind.startswith(('gev_','gpd_')):
        from scipy.stats import genextreme,genpareto
        prob=(np.arange(30)+.5)/30
        if kind.startswith('gev_'):
            vals=genextreme.ppf(prob,c=0,loc=4,scale=2);a=np.broadcast_to(np.repeat(vals,2)[:,None,None],(60,3,4)).copy();params={'block_length':2,'return_period':10}
        else:
            vals=genpareto.ppf(prob,c=0,scale=2);a=np.broadcast_to(np.r_[np.full(30,-1),vals][:,None,None],(60,3,4)).copy();params={'threshold':0,'return_period':20}
        z=grid(run(kind,a,None,params));assert np.isfinite(z).all()
        if kind.endswith('_shape'):assert np.max(abs(z))<.4
        else:assert np.min(z)>2
        return
    if kind.startswith('tracked_'):
        a=np.zeros((8,3,4));a[1:4,0,0:2]=4;a[6:,2,3]=5
        r=run(kind,a,None,{'threshold':2,'maximum_gap':2});z=grid(r);assert r['receipt']['metrics']['events']==2
        assert r['rows'][0][5:]==[2.,200.,200.] and r['rows'][1][5:]==[1.,100.,100.]
        if kind.endswith('_id'):assert z[2,3]==2 and z[0,0]==0
        elif kind.endswith('_span'):assert z[0,0]==2 and z[2,3]==1
        else:assert z[0,0]==200 and z[2,3]==100
        return
    if kind.startswith('multi_harmonic_'):
        t=np.arange(48.);y=2+np.where(t>=16,7,0)-np.where(t>=32,4,0)+2*np.cos(2*np.pi*t/6)
        a=np.broadcast_to(y[:,None,None],(48,3,4)).copy();r=run(kind,a,t,{'period':6,'min_segment':8,'max_breaks':2});z=grid(r)
        if kind.endswith('_bic'):assert np.min(z)>0
        else:np.testing.assert_allclose(z,{'multi_harmonic_count':2,'multi_harmonic_first':15.5,'multi_harmonic_last':31.5}[kind],atol=1e-9)
        return
    if kind.startswith(('rts_','fitted_state_')):
        rng=np.random.default_rng(7);a=a+rng.normal(0,.3,a.shape);r=run(kind,a,t,{'trajectory_limit':2} if kind.startswith('fitted_') else {})
        assert np.isfinite(grid(r)).all()
        if kind.startswith('fitted_'):assert r['receipt']['metrics']['fitted_nll_per_observation']<=r['receipt']['metrics']['initial_nll_per_observation']+1e-8
        if kind=='rts_sd':assert np.min(grid(r))>=0
        return
    if kind.startswith('gtwr_'):
        rng=np.random.default_rng(22);t=np.arange(12.);x=rng.normal(size=(12,4,6));v=rng.normal(size=x.shape);y=4+2*x-3*v
        r=run(kind,y,t,{'local_sample_limit':256,'spatial_range':100,'temporal_range':20},sources=[source(y),source(x),source(v)],covariates=[{'source':j,'band':i+1,'unit':'index'} for j in (1,2) for i in range(len(t))]);z=grid(r)
        if kind=='gtwr_coefficient':np.testing.assert_allclose(z,2,atol=1e-9)
        elif kind=='gtwr_holdout_rmse':np.testing.assert_allclose(z[np.isfinite(z)],0,atol=1e-9);assert np.isnan(z[:,:4]).all()
        else:assert np.min(z)>=10
        return
    if kind.startswith('panel_'):
        t=np.arange(8.);rng=np.random.default_rng(19);x=rng.normal(size=(8,4,4));spatial=np.arange(16).reshape(4,4);y=2*x+spatial+t[:,None,None]
        r=run(kind,y,t,{'block_cells':2},sources=[source(y),source(x)],covariates=[{'source':1,'band':i+1,'unit':'index'} for i in range(8)])
        assert r['receipt']['metrics']['coefficient']==pytest.approx(2)
        np.testing.assert_allclose(grid(r),spatial-spatial.mean() if kind=='panel_spatial_effect' else 0,atol=1e-10);return
    if kind.startswith('hotspot_'):
        r=run(kind,a+space,t,{'radius':1,'permutations':19})
        z=grid(r);assert np.isfinite(z).all()
        if kind.endswith('_p'):assert np.min(z)>=1/20 and np.max(z)<=1
        if kind.endswith('_fraction'):assert np.min(z)>=0 and np.max(z)<=1
        if kind=='hotspot_class':assert set(np.unique(z))<={0,1,2,3,4,5,6,7}
        return
    if kind.startswith('harmonic_break_'):
        t=np.arange(36.);a=(2+np.where(t>=18,7,0)+(2+np.where(t>=18,1,0))*np.cos(2*np.pi*t/6))[:,None,None]+np.zeros((36,3,4))
        r=run(kind,a,t,{'period':6,'min_segment':8});z=grid(r)
        if kind.endswith('_bic'):assert np.min(z)>6
        else:np.testing.assert_allclose(z,{'harmonic_break_flag':1,'harmonic_break_time':17.5,'harmonic_break_level':7,'harmonic_break_amplitude':1}[kind],atol=1e-8)
        return
    if kind.startswith('event_'):
        t=np.array([0.,1.,2.,3.,4.,10.,11.,12.]);a=np.broadcast_to(np.array([0,3,5,np.nan,4,4,6,0])[:,None,None],(8,3,4)).copy()
        r=run(kind,a,t,{'threshold':2,'maximum_gap':2});np.testing.assert_allclose(grid(r),{'event_count':3,'event_longest_span':1,'event_total_span':2,'event_integrated_excess':5}[kind]);return
    if kind.startswith('st_universal_'):
        rng=np.random.default_rng(42);a=a+rng.normal(0,.4,a.shape)
        r=run(kind,a,t,{'sample_limit':24});z=grid(r)
        assert np.isfinite(z).any() and r['receipt']['metrics']['drift_rank']==4
        if 'holdout' in kind:assert np.isnan(z[:,:3]).all()
        if kind.endswith('_sd'):assert np.min(z)>0
        return
    if kind.startswith(('st_kriging_','st_holdout_')):
        r=run(kind,a,t,{'sample_limit':24});z=grid(r)
        assert np.isfinite(z).any()
        if kind.startswith('st_holdout_'):assert np.isnan(z[:,:3]).all() and r['receipt']['metrics']['validation_pairs']==6
        if kind.endswith('_sd'):assert np.min(z)>0
        return
    r=run(kind,a,t,params)
    if kind=='space_time_variogram':
        row=next(q for q in r['rows'] if q[:3]==['temporal',0.,1.])
        assert row[3]==17*12 and row[4]==pytest.approx(.5*np.mean(space**2));return
    if kind=='lag_permutation':
        assert len(r['rows'])==16 and all(0<q[3]<=q[-1]<=1 for q in r['rows'])
        assert r['rows']==run(kind,a,t,params)['rows'];return
    z=grid(r)
    expected={'series_slope':space,'sen':space,'coverage':1.,'series_count':18.,'series_median':5+8.5*space,
        'exceedance':np.mean(a>10,axis=0),'lag_correlation':1.,'forecast_mean':5+19*space,'forecast_sd':0.,'hindcast_rmse':0.,'hindcast_skill':1.,
        'series_amplitude':2.,'series_harmonic_rmse':0.,'season_peak':2.,'season_start':.5,'season_end':3.5,'season_duration':3.,
        'segmented_count':1.,'segmented_first_break':5.5,'series_break_time':5.5,'series_break_jump':7.,'series_break_strength':1.,
        'eof_mode':space/np.linalg.norm(space),'eof_reconstruction_rmse':0.,'eof_local_skill':1.,'block_trend_p':.01,
        'block_trend_by':min(1.,.01*sum(1/i for i in range(1,13)))}
    if kind in expected:np.testing.assert_allclose(z,expected[kind],atol=1e-9)
    elif kind in ('mk_p','mk_by_q'):
        n=18;s=n*(n-1)/2;var=n*(n-1)*(2*n+5)/18;p=2*ndtr(-(s-1)/np.sqrt(var))
        np.testing.assert_allclose(z,p if kind=='mk_p' else min(1.,p*sum(1/i for i in range(1,13))),rtol=1e-9)
    elif kind=='space_time_lag':
        # Date zero is constant; remaining standardized fields are identical.
        standardized=(space-space.mean())/space.std();oracle=np.zeros_like(space)
        for i,j in np.ndindex(space.shape):
            neighbors=[standardized[u,v] for u,v in ((i-1,j),(i+1,j),(i,j-1),(i,j+1)) if 0<=u<3 and 0<=v<4]
            oracle[i,j]=standardized[i,j]*np.mean(neighbors)
        np.testing.assert_allclose(z,oracle)
    elif kind.startswith('kalman_'):
        assert np.isfinite(z).all()
        if kind.endswith('_sd'):assert np.min(z)>0
    else:pytest.fail('No numerical reference for '+kind)

def test_irregular_time_qa_calibration_and_alignment():
    t=np.array([0.,1.,4.,7.,9.,15.,21.,30.]);z=3+2*t[:,None,None]+np.zeros((len(t),3,4))
    mask=np.ones((3,4));mask[0,0]=0
    s=source(z/2,scales=[2.]*len(t));q=source(mask,unit=None)
    r=run('sen',z,t,sources=[s,q],quality=[{'source':1,'scheme':'binary','roles':['3']}])
    np.testing.assert_allclose(grid(r),2)
    r=run('coverage',z,t,sources=[s,q],quality=[{'source':1,'scheme':'binary','roles':['3']}])
    assert grid(r)[0,0]==7/8
    with pytest.raises(FigureInputError,match='align'):
        run('sen',z,t,sources=[s,source(mask,aff=from_origin(500001,4500000,10,10))],quality=[{'source':1,'scheme':'binary'}])
    with pytest.raises(FigureInputError,match='regular'):run('lag_correlation',z,t)
    with pytest.raises(FigureInputError,match='increasing'):run('sen',z,[0,1,2,3,4,5,5,6])

def test_state_space_against_batch_gaussian_conditioning():
    # Independent batch Gaussian conditioning on the same stated first-observation prior.
    t=np.array([0.,.5,2.,4.,4.5,7.,10.,11.]);y=np.array([2.,2.4,np.nan,4.1,4.4,5.8,8.,8.7]);a=y[:,None,None]
    p={'minimum_observations':3,'horizon':2.,'process_variance':.03,'observation_variance':.2,'initial_velocity_variance':.4}
    def cov(a,b):
        m=min(a,b);return .2+.4*a*b+.03*(a*b*m-(a+b)*m*m/2+m**3/3)
    ids=np.flatnonzero(np.isfinite(y)&(t>0));u=t[ids];future=t[-1]+2
    C=np.array([[cov(x,z) for z in u] for x in u])+.2*np.eye(len(u));k=np.array([cov(future,x) for x in u])
    mu=y[0]+k@np.linalg.solve(C,y[ids]-y[0]);sd=np.sqrt(cov(future,future)+.2-k@np.linalg.solve(C,k))
    np.testing.assert_allclose(kalman(a,t,p,'kalman_forecast')[0],mu,atol=1e-9)
    np.testing.assert_allclose(kalman(a,t,p,'kalman_forecast_sd')[0],sd,atol=1e-9)
    # Future measurement changes must not alter earlier validation rows.
    changed=a.copy();changed[-1]+=100
    for fn,kind in [(kalman,'kalman_hindcast_rmse'),(forecast,'hindcast_rmse')]:
        original=fn(a,t,kind,p)[2] if fn==forecast else fn(a,t,p,kind)[2]
        later=fn(changed,t,kind,p)[2] if fn==forecast else fn(changed,t,p,kind)[2]
        assert original[:-1]==later[:-1]

def test_actual_science_figures_render():
    from terrain.studio_routes import StudioInput
    from terrain.studio_render import render
    t=np.arange(18.);a=t[:,None,None]*np.arange(1,13).reshape(3,4)+2
    for kind,p in [('eof_mode',{}),('hindcast_rmse',{}),('space_time_variogram',{}),('kalman_hindcast_rmse',{})]:
        r=run(kind,a,t,p)
        for figure in r['figures']:
            rasters=[{k:r['raster'][k] for k in ('name','data','unit','band')}] if figure['raster'] else []
            req=StudioInput(recipe=figure['recipe'],csv=figure['csv'] or '',rasters=rasters,**figure['bindings'])
            png,_,_=render(req);assert png.startswith(b'\x89PNG')
            svg,_,_=render(req.model_copy(update={'format':'svg'}));assert svg.startswith(b'<?xml')


def test_kriging_independent_dense_reference_and_holdout_isolation():
    from analysis.spacetime_kriging import fit,kriging
    from types import SimpleNamespace
    from scipy.spatial.distance import cdist
    rng=np.random.default_rng(5);x=rng.uniform(0,10,(18,3));y=rng.normal(size=18);target=rng.uniform(0,10,(4,3))
    p={'spatial_range':4.,'temporal_range':3.,'nugget_ratio':.2,'fit_covariance':0}
    predict,meta=fit(x,y,p);mu,sd=predict(target)
    K=np.exp(-cdist(x[:,:2],x[:,:2])/4-abs(x[:,2,None]-x[:,2])/3)+.2*np.eye(len(x))
    cross=np.exp(-cdist(x[:,:2],target[:,:2])/4-abs(x[:,2,None]-target[:,2])/3)
    A=np.block([[K,np.ones((len(x),1))],[np.ones((1,len(x))),np.zeros((1,1))]])
    weights=np.linalg.solve(A,np.vstack([cross,np.ones(len(target))]))
    np.testing.assert_allclose(mu,y@weights[:-1],atol=1e-10)
    var=1.2-np.sum(weights[:-1]*cross,axis=0)-weights[-1]
    np.testing.assert_allclose(sd,np.sqrt(meta['sill']*var),atol=1e-10)
    _,fitted=fit(x,y,{**p,'fit_covariance':1});assert fitted['reml_objective']<=meta['reml_objective']+1e-8
    a=rng.normal(size=(8,3,6));t=np.arange(8.)
    cfg={**p,'sample_limit':24,'seed':7,'holdout_dates':2,'buffer_cells':1}
    g=SimpleNamespace(is_meter=True,transform=AFF)
    original=kriging(a,t,g,cfg,'st_holdout_rmse')[3]
    b=a.copy();b[-2:]+=100;b[:,:,4:]+=100
    changed=kriging(b,t,g,cfg,'st_holdout_rmse')[3]
    for key in ('spatial_range','temporal_range','sill','training_indices','training_mean','reml_objective'):
        assert original[key]==changed[key]
    assert original['rmse']!=changed['rmse']


def test_harmonic_no_change_and_gap_boundary():
    t=np.arange(36.);a=(2+.05*t+2*np.cos(2*np.pi*t/6))[:,None,None]+np.zeros((36,3,4))
    r=run('harmonic_break_flag',a,t,{'period':6,'min_segment':8});np.testing.assert_allclose(grid(r),0)
    t=np.array([0,1,2,3,9,10,11,12],float);a=np.full((8,3,4),4.)
    r=run('event_total_span',a,t,{'threshold':2,'maximum_gap':2});np.testing.assert_allclose(grid(r),6)


def test_hotspot_independent_score_and_panel_absorbed_covariate():
    from analysis.spacetime_hotspots import hotspot
    from analysis.spacetime_panel import panel
    space=np.arange(16.).reshape(4,4);a=np.stack([space+i for i in range(8)])
    p={'radius':1,'permutations':39,'seed':7,'alpha':.05}
    out,_,_,meta=hotspot(a,np.arange(8.),p,'hotspot_latest_z')
    vals=space.ravel();neighbors=[space[1,1],space[0,1],space[2,1],space[1,0],space[1,2]]
    oracle=(sum(neighbors)-5*vals.mean())/(vals.std()*np.sqrt((16*5-25)/15))
    assert out[1,1]==pytest.approx(oracle)
    q=hotspot(a,np.arange(8.),p,'hotspot_latest_p')[0]
    np.testing.assert_array_equal(q,hotspot(a,np.arange(8.),p,'hotspot_latest_p')[0])
    with pytest.raises(FigureInputError,match='absorbed'):
        panel(a,a,{'block_cells':2},'panel_spatial_effect')


def test_panel_against_full_dummy_regression():
    from analysis.spacetime_panel import panel
    rng=np.random.default_rng(19);x=rng.normal(size=(8,4,4));spatial=np.arange(16).reshape(4,4)
    y=2*x+spatial+np.arange(8.)[:,None,None]+rng.normal(0,.3,x.shape)
    z,_,_,m=panel(y,x,{'block_cells':2},'panel_latest_residual')
    t=np.repeat(np.arange(8),16);s=np.tile(np.arange(16),8)
    A=np.column_stack([np.ones(128),x.ravel(),np.eye(8)[t,1:],np.eye(16)[s,1:]])
    b=np.linalg.lstsq(A,y.ravel(),rcond=None)[0];e=y.ravel()-A@b
    np.testing.assert_allclose(m['coefficient'],b[1],atol=1e-12)
    np.testing.assert_allclose(z,e[-16:].reshape(4,4),atol=1e-12)
    block=(s//4//2)*2+(s%4//2);bread=np.linalg.inv(A.T@A)
    scores=np.array([A[block==i].T@e[block==i] for i in range(4)])
    cov=bread@(scores.T@scores)@bread*(4/3)*(127/(128-A.shape[1]))
    np.testing.assert_allclose(m['cluster_robust_se'],np.sqrt(cov[1,1]),atol=1e-12)

def test_advanced_figures_actual_products():
    from terrain.studio_routes import StudioInput
    from terrain.studio_render import render
    t=np.arange(18.);space=np.arange(1,17).reshape(4,4);a=(t[:,None,None]+1)*space
    rng=np.random.default_rng(7);x=rng.normal(size=a.shape);y=2*x+a+rng.normal(0,.1,a.shape)
    results=[run('st_holdout_rmse',a,t,{'sample_limit':24}),run('hotspot_class',a,t,{'radius':1,'permutations':39}),
      run('panel_spatial_effect',y,t,sources=[source(y),source(x)],covariates=[{'source':1,'band':i+1,'unit':'index'} for i in range(len(t))]),
      run('space_time_variogram',a,t,{'lag':2,'radius':2})]
    assert any(f['recipe']=='basic_table_heatmap' for f in results[-1]['figures'])
    for r in results:
        for figure in r['figures']:
            rasters=[{k:r['raster'][k] for k in ('name','data','unit','band')}] if figure['raster'] else []
            req=StudioInput(recipe=figure['recipe'],csv=figure['csv'] or '',rasters=rasters,**figure['bindings'])
            for fmt,magic in [('png',b'\x89PNG'),('svg',b'<?xml')]:
                data,_,_=render(req.model_copy(update={'format':fmt}));assert data.startswith(magic)


def test_universal_kriging_augmented_reference():
    from analysis.spacetime_kriging import fit
    from scipy.spatial.distance import cdist
    rng=np.random.default_rng(15);x=rng.uniform(0,8,(25,3));target=rng.uniform(0,8,(5,3));y=3+x@np.array([.2,-.3,.7])+rng.normal(0,.4,len(x))
    p={'spatial_range':4.,'temporal_range':3.,'nugget_ratio':.15,'fit_covariance':0,'interaction':.7,'universal':1}
    prediction,meta=fit(x,y,p);mu,sd=prediction(target)
    def corr(a,b):
        u=1+cdist(a[:,2:],b[:,2:])/3
        return np.exp(-cdist(a[:,:2],b[:,:2])/4/u**.35)/u**.7
    K=corr(x,x)+.15*np.eye(len(x));cross=corr(x,target)
    assert np.linalg.eigvalsh(K).min()>0
    H=np.column_stack((np.ones(len(x)),x));D=np.column_stack((np.ones(len(target)),target))
    aug=np.block([[K,H],[H.T,np.zeros((4,4))]])
    sol=np.linalg.solve(aug,np.vstack((cross,D.T)))
    np.testing.assert_allclose(mu,y@sol[:len(x)],atol=1e-10)
    var=1.15-np.sum(sol[:len(x)]*cross,axis=0)-np.sum(sol[len(x):]*D.T,axis=0)
    np.testing.assert_allclose(sd,np.sqrt(meta['sill']*var),atol=1e-10)
    np.testing.assert_allclose(H.T@sol[:len(x)],D.T,atol=1e-10)


def test_rts_batch_gaussian_and_fitted_holdout_isolation():
    from analysis.spacetime_dynamic import smooth,estimate
    t=np.array([0.,.5,2.,4.,4.5,7.,10.,11.,13.,15.]);y=np.array([2.,2.4,np.nan,4.1,4.4,5.8,8.,8.7,9.4,11.])
    q,r,v=.03,.2,.4
    def cov(a,b):
        m=min(a,b);return r+v*a*b+q*(a*b*m-(a+b)*m*m/2+m**3/3)
    ids=np.flatnonzero(np.isfinite(y)&(t>0));u=t[ids]
    C=np.array([[cov(x,z) for z in u] for x in u])+r*np.eye(len(u));cross=np.array([[cov(x,z) for z in u] for x in t])
    mu=y[0]+cross@np.linalg.solve(C,y[ids]-y[0])
    var=np.array([cov(x,x) for x in t])-np.sum(cross*np.linalg.solve(C,cross.T).T,axis=1)
    m,P=smooth(y,t,q,r,v);np.testing.assert_allclose(m[:,0],mu,atol=1e-9);np.testing.assert_allclose(P[:,0,0],var,atol=1e-9)
    a=y[:,None,None];p={'minimum_observations':4,'holdout_dates':2,'trajectory_limit':1,'seed':2,'process_variance':q,'observation_variance':r,'initial_velocity_variance':v}
    before=estimate(a,t,p);b=a.copy();b[-2:]+=200;assert before==estimate(b,t,p)


def test_gtwr_direct_weighted_reference_and_holdout():
    from analysis.spacetime_gtwr import local_fit,gtwr
    from types import SimpleNamespace
    rng=np.random.default_rng(33);coords=rng.uniform(0,10,(30,3));X=np.column_stack([np.ones(30),rng.normal(size=(30,2))]);y=rng.normal(size=30);target=np.array([3,4,5])
    p={'spatial_range':6.,'temporal_range':4.,'effective_samples':5}
    beta,eff=local_fit(coords,X,y,target,p)
    W=np.diag(np.exp(-.5*(np.sum((coords[:,:2]-target[:2])**2,axis=1)/36+(coords[:,2]-5)**2/16)))
    np.testing.assert_allclose(beta,np.linalg.solve(X.T@W@X,X.T@W@y),atol=1e-12)
    a=rng.normal(size=(8,4,6));b=rng.normal(size=a.shape);v=2*a-b+1;g=SimpleNamespace(is_meter=True,transform=AFF)
    cfg={**p,'spatial_range':100,'temporal_range':30,'local_sample_limit':128,'seed':2,'holdout_dates':2,'buffer_cells':1}
    original=gtwr(v,[a,b],np.arange(8.),g,cfg,'gtwr_holdout_rmse')[3]
    changed=v.copy();changed[-2:]+=100;changed[:,:,4:]+=100
    result=gtwr(changed,[a,b],np.arange(8.),g,cfg,'gtwr_holdout_rmse')[3]
    assert original['training_indices']==result['training_indices'] and original['rmse']<1e-10 and result['rmse']>100


def test_extreme_likelihood_and_event_gap_reference():
    from analysis.spacetime_extremes import fit_gpd,fit_gev,track
    from scipy.stats import genpareto,genextreme
    from types import SimpleNamespace
    p=(np.arange(120)+.5)/120
    a=fit_gpd(genpareto.ppf(p,c=.15,scale=2))
    assert a is not None and abs(a[0]-.15)<.12 and abs(a[1]-2)<.25
    b=fit_gev(genextreme.ppf(p,c=-.15,loc=4,scale=2))
    assert b is not None and abs(b[0]-.15)<.12 and abs(b[1]-4)<.25 and abs(b[2]-2)<.25
    cube=np.zeros((6,2,2));cube[:,0,0]=5
    _,_,rows,meta=track(cube,np.array([0,1,2,10,11,12.]),SimpleNamespace(is_meter=True,transform=AFF),{'threshold':2,'maximum_gap':2,'minimum_voxels':1},'tracked_span')
    assert meta['events']==2 and [r[5] for r in rows]==[2.,2.]


def test_disk_cube_window_reference_and_global_fit(tmp_path):
    import rasterio
    from analysis.spacetime_disk import execute as disk
    from analysis.spacetime_kriging import fit
    rng=np.random.default_rng(24);t=np.arange(8.);rr,cc=np.indices((19,21));a=3+rr*.1+cc*.2+t[:,None,None]*2+rng.normal(0,.1,(8,19,21));a[:,0,0]=np.nan
    src=tmp_path/'cube.tif';out=tmp_path/'sen.tif'
    with rasterio.open(src,'w',driver='GTiff',width=21,height=19,count=8,dtype='float64',crs=CRS,transform=AFF,nodata=np.nan) as ds:
        ds.write(a);ds.update_tags(TERRAIN_UNIT='index')
    receipt=disk(src,out,t,'sen',{},tile=16)
    with rasterio.open(out) as ds:z=ds.read(1)
    np.testing.assert_allclose(z,grid(run('sen',a,t)),equal_nan=True,atol=1e-9)
    assert receipt['output_sha256']==hashlib.sha256(out.read_bytes()).hexdigest()
    with pytest.raises(FigureInputError,match='new file'):disk(src,out,t,'sen',{},tile=16)
    p={'sample_limit':24,'seed':12,'horizon':1,'spatial_range':100,'temporal_range':10,'interaction':.5}
    out=tmp_path/'global.tif';receipt=disk(src,out,t,'st_universal_mean',p,tile=16)
    coords=np.array(receipt['metrics']['global_training_coordinates'])
    ids=np.column_stack((coords[:,2],coords[:,1]/10-.5,coords[:,0]/10-.5)).astype(int)
    predict,_=fit(coords,a[tuple(ids.T)],{**p,'fit_covariance':0,'universal':1,'nugget_ratio':.1})
    xyz=np.column_stack(((cc.ravel()+.5)*10,(rr.ravel()+.5)*10,np.full(rr.size,8.)))
    expected=predict(xyz)[0].reshape(rr.shape)
    with rasterio.open(out) as ds:np.testing.assert_allclose(ds.read(1),expected,atol=1e-10)


def test_multibreak_no_change_and_extreme_shape_independence():
    t=np.arange(48.);a=(2+2*np.cos(2*np.pi*t/6))[:,None,None]+np.zeros((48,3,4))
    np.testing.assert_allclose(grid(run('multi_harmonic_count',a,t,{'period':6,'min_segment':8})),0)
    from scipy.stats import genpareto
    x=np.r_[np.full(30,-1),genpareto.ppf((np.arange(30)+.5)/30,c=.1,scale=2)]
    a=np.broadcast_to(x[:,None,None],(60,3,4)).copy()
    r1=run('gpd_shape',a,None,{'threshold':0,'return_period':1.1})
    r2=run('gpd_shape',a,None,{'threshold':0,'return_period':20})
    np.testing.assert_allclose(grid(r1),grid(r2),atol=1e-12)


def test_joint_parameter_selection_and_nested_validation():
    from analysis.spacetime_kriging import fit
    from analysis.spacetime_gtwr import gtwr
    from types import SimpleNamespace
    rng=np.random.default_rng(52);coords=rng.uniform(0,8,(24,3));y=coords@np.array([.2,-.3,.7])+rng.normal(0,.5,len(coords))
    p={'spatial_range':4.,'temporal_range':3.,'nugget_ratio':.2,'interaction':.5,'universal':1,'fit_covariance':1,'fit_interaction':1}
    predict,m=fit(coords,y,p)
    assert m['interaction_fitted'] and .05<=m['interaction']<=1 and m['optimization_starts']==3
    assert m['reml_objective']<=m['initial_reml_objective']+1e-7
    from scipy.spatial.distance import cdist
    target=rng.uniform(0,8,(5,3));mu,sd=predict(target)
    def corr(a,b):
        u=1+cdist(a[:,2:],b[:,2:])/m['temporal_range'];q=m['interaction']
        return np.exp(-cdist(a[:,:2],b[:,:2])/m['spatial_range']/u**(q/2))/u**q
    ratio=m['nugget_ratio'];K=corr(coords,coords)+ratio*np.eye(len(coords));C=corr(coords,target)
    H=np.column_stack((np.ones(len(coords)),coords));D=np.column_stack((np.ones(len(target)),target))
    sol=np.linalg.solve(np.block([[K,H],[H.T,np.zeros((4,4))]]),np.vstack((C,D.T)))
    np.testing.assert_allclose(mu,y@sol[:len(coords)],atol=1e-10)
    variance=1+ratio-np.sum(sol[:len(coords)]*C,axis=0)-np.sum(sol[len(coords):]*D.T,axis=0)
    np.testing.assert_allclose(sd,np.sqrt(m['sill']*variance),atol=1e-10)
    x=rng.normal(size=(12,6,9));z=2*x+rng.normal(0,.1,x.shape)
    cfg={'spatial_range':100.,'temporal_range':20.,'local_sample_limit':512,'effective_samples':5,'seed':3,'holdout_dates':2,'buffer_cells':1,'auto_bandwidth':1}
    g=SimpleNamespace(is_meter=True,transform=AFF)
    m=gtwr(z,[x],np.arange(12.),g,cfg,'gtwr_holdout_rmse')[3]
    changed=z.copy();changed[-2:]+=100;changed[:,:,6:]+=100
    n=gtwr(changed,[x],np.arange(12.),g,cfg,'gtwr_holdout_rmse')[3]
    for key in ('bandwidth_candidates','inner_split','selected_spatial_range','selected_temporal_range','training_indices'):assert m[key]==n[key]
    assert n['rmse']>100 and m['rmse']<1


def test_extreme_bootstrap_seed_and_order():
    from analysis.spacetime_extremes import bootstrap_interval
    from scipy.stats import genextreme,genpareto
    q=(np.arange(40)+.5)/40
    for x,gev in [(genextreme.ppf(q,0,loc=4,scale=2),True),(np.r_[np.full(40,-1),genpareto.ppf(q,0,scale=2)],False)]:
        a=bootstrap_interval(x,gev,0,20,8,39,17)
        assert a is not None and a[0]<a[1] and a[2]>=32
        assert a==bootstrap_interval(x,gev,0,20,8,39,17)


@pytest.mark.parametrize('kind',['coverage','sen','mk_p','exceedance','lag_correlation','series_median','series_count','series_slope','series_amplitude','series_harmonic_rmse','season_peak','season_start','season_end','season_duration','forecast_mean','forecast_sd','hindcast_rmse','hindcast_skill','rts_level','rts_velocity','rts_sd','event_count','event_longest_span','event_total_span','event_integrated_excess'])
def test_disk_pixel_method_parity(kind,tmp_path):
    import rasterio
    from analysis.spacetime_disk import execute as disk
    t=np.arange(18.);r,c=np.indices((17,19));a=2+.1*t[:,None,None]+2*np.cos(2*np.pi*(t[:,None,None]-2)/6)+.1*r+.1*c
    a[:,0,0]=np.nan;a[4,15,15]=np.nan
    p={'period':6} if kind.startswith('season_') or kind in ('series_amplitude','series_harmonic_rmse') else {'threshold':3} if kind=='exceedance' or kind.startswith('event_') else {}
    src=tmp_path/'cube.tif';dst=tmp_path/'result.tif'
    with rasterio.open(src,'w',driver='GTiff',width=19,height=17,count=18,dtype='float64',crs=CRS,transform=AFF,nodata=np.nan) as ds:
        ds.write(a);ds.update_tags(TERRAIN_UNIT='index')
    disk(src,dst,t,kind,p,tile=16)
    with rasterio.open(dst) as ds:np.testing.assert_allclose(ds.read(1),grid(run(kind,a,t,p)),equal_nan=True,atol=1e-9)

@pytest.mark.parametrize('kind',['st_universal_mean','st_universal_sd'])
def test_global_disk_priority_tile_invariance(kind,tmp_path):
    import rasterio
    from analysis.spacetime_disk import execute as disk
    rng=np.random.default_rng(23);a=rng.normal(size=(8,17,19));src=tmp_path/'cube.tif'
    with rasterio.open(src,'w',driver='GTiff',width=19,height=17,count=8,dtype='float64',crs=CRS,transform=AFF,nodata=np.nan) as ds:
        ds.write(a);ds.update_tags(TERRAIN_UNIT='index')
    p={'sample_limit':24,'seed':42,'horizon':1}
    m=disk(src,tmp_path/'a.tif',np.arange(8.),kind,p,tile=16)
    n=disk(src,tmp_path/'b.tif',np.arange(8.),kind,p,tile=32)
    assert m['metrics']['global_training_coordinates']==n['metrics']['global_training_coordinates']
    with rasterio.open(tmp_path/'a.tif') as a,rasterio.open(tmp_path/'b.tif') as b:np.testing.assert_allclose(a.read(),b.read(),atol=1e-10)
