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
    a=rng.normal(size=(8,3,6));t=np.arange(8.)
    cfg={**p,'sample_limit':24,'seed':7,'holdout_dates':2,'buffer_cells':1}
    g=SimpleNamespace(is_meter=True,transform=AFF)
    original=kriging(a,t,g,cfg,'st_holdout_rmse')[3]
    b=a.copy();b[-2:]+=100;b[:,:,4:]+=100
    changed=kriging(b,t,g,cfg,'st_holdout_rmse')[3]
    for key in ('spatial_range','temporal_range','sill','training_indices','training_mean','reml_objective'):
        assert original[key]==changed[key]
    assert original['rmse']!=changed['rmse']
