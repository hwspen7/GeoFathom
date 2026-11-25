"""Independent analytic references for every spatial science method.

The fixtures use a known projected grid and metric geometry. No reference
value is computed by the production spatial operator under test.
"""
import base64
import hashlib
import json
import math
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import box,Point,mapping,shape
from shapely.ops import transform
from analysis.science_catalog import BY_ID
from analysis.science_routes import SpatialInput,execute
from core.main import app

CRS='EPSG:32617'
X,Y=500000,4500000
WORLD=Transformer.from_crs(CRS,4326,always_xy=True).transform
LOCAL=Transformer.from_crs(4326,CRS,always_xy=True).transform
Z=np.arange(1.,17.).reshape(4,4)

def raster(z=Z,unit='m',x=X):
    z=np.asarray(z,float)
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',width=z.shape[1],height=z.shape[0],count=1,dtype='float64',
                      crs=CRS,transform=from_origin(x,Y,10,10),nodata=float('nan')) as ds:
            ds.write(z,1);ds.update_tags(TERRAIN_UNIT=unit)
        return {'name':'fixture','data':base64.b64encode(mem.read()).decode(),'unit':unit,'band':1}

def vectors(*gs):
    return {'type':'FeatureCollection','features':[{'type':'Feature','geometry':mapping(transform(WORLD,g)),'properties':{}} for g in gs]}

def result_grid(result):
    product=result['raster'];raw=base64.b64decode(product['data'])
    assert hashlib.sha256(raw).hexdigest()==product['sha256']==result['receipt']['raster_sha256']
    with MemoryFile(raw) as mem,mem.open() as ds:
        assert ds.crs.to_epsg()==32617
        return ds.read(1),ds.transform

def run(kind,**kwargs):
    result=execute(SpatialInput(operation=kind,**kwargs))
    json.dumps(result,allow_nan=False)
    assert result['receipt']['operation']==kind and result['receipt']['assumption']
    assert result['operation']==kind
    return result

VECTOR_EXPECTED={'intersection':5000,'union':15000,'difference':5000,'symmetric_difference':10000,'convex_hull':10000}
@pytest.mark.parametrize('kind',list(VECTOR_EXPECTED))
def test_vector_area_oracles(kind):
    a=vectors(box(X,Y-100,X+100,Y));b=vectors(box(X+50,Y-100,X+150,Y))
    result=run(kind,vectors=[a] if kind=='convex_hull' else [a,b])
    assert result['receipt']['metrics']['area_m2']==pytest.approx(VECTOR_EXPECTED[kind],rel=1e-7)
    assert sum(transform(LOCAL,shape(f['geometry'])).area for f in result['features']['features'])==pytest.approx(VECTOR_EXPECTED[kind],rel=1e-7)

@pytest.mark.parametrize('kind',['buffer','centroid','simplify','spatial_join','nearest_join','point_centers','point_nearest_neighbor','sample_polygon'])
def test_vector_metric_oracles(kind):
    a=vectors(box(X,Y-100,X+100,Y));points=vectors(Point(X+5,Y-5),Point(X+15,Y-5),Point(X+35,Y-5))
    if kind=='buffer':
        result=run(kind,vectors=[vectors(Point(X,Y))],parameters={'distance_m':10})
        area=transform(LOCAL,shape(result['features']['features'][0]['geometry'])).area
        assert area==pytest.approx(math.pi*100,rel=.002)
    elif kind=='centroid':
        result=run(kind,vectors=[a]);p=transform(LOCAL,shape(result['features']['features'][0]['geometry']))
        assert p.distance(Point(X+50,Y-50))<1e-6
    elif kind=='simplify':
        result=run(kind,vectors=[a],parameters={'distance_m':1})
        assert transform(LOCAL,shape(result['features']['features'][0]['geometry'])).area==pytest.approx(10000,rel=1e-7)
    elif kind=='spatial_join':
        result=run(kind,vectors=[points,vectors(box(X,Y-10,X+20,Y))]);assert result['rows']==[[0,0,0.],[1,0,0.]]
    elif kind=='nearest_join':
        result=run(kind,vectors=[vectors(Point(X+5,Y-5)),vectors(Point(X+15,Y-5),Point(X+35,Y-5))])
        assert result['rows'][0][:2]==[0,0] and result['rows'][0][2]==pytest.approx(10,abs=1e-6)
    elif kind=='point_centers':
        result=run(kind,vectors=[points]);assert result['receipt']['metrics']['standard_distance_m']==pytest.approx(np.std([5,15,35]),abs=1e-6)
    elif kind=='point_nearest_neighbor':
        result=run(kind,vectors=[points]);assert [r[2] for r in result['rows']]==pytest.approx([10,10,20],abs=1e-6)
    else:
        result=run(kind,vectors=[a],parameters={'count':50,'seed':7})
        assert len(result['features']['features'])==50
        assert all(box(X,Y-100,X+100,Y).covers(transform(LOCAL,shape(f['geometry']))) for f in result['features']['features'])
        assert sum(f['properties']['area_weight_m2'] for f in result['features']['features'])==pytest.approx(10000,rel=1e-7)

@pytest.mark.parametrize('kind,expected',[('raster_sum',3*Z),('raster_difference',-Z),('raster_ratio',np.full_like(Z,.5)),('raster_mean',1.5*Z),('raster_sd',.5*Z),('raster_min',Z),('raster_max',2*Z)],ids=['raster_sum','raster_difference','raster_ratio','raster_mean','raster_sd','raster_min','raster_max'])
def test_cell_arithmetic_oracles(kind,expected):
    result=run(kind,rasters=[raster(),raster(2*Z)])
    out,aff=result_grid(result)
    np.testing.assert_allclose(out,expected)
    assert aff==from_origin(X,Y,10,10)

@pytest.mark.parametrize('kind',['focal_mean','focal_sd','focal_min','focal_max','focal_range'])
def test_focal_against_independent_window_reduction(kind):
    z=Z.copy();z[1,1]=np.nan
    # Large offset checks cancellation in variance.
    z=z+1e9
    result=run(kind,rasters=[raster(z)],parameters={'radius':1});out,_=result_grid(result)
    expected=np.full_like(z,np.nan)
    for row,col in zip(*np.nonzero(np.isfinite(z))):
        v=z[max(0,row-1):row+2,max(0,col-1):col+2];v=v[np.isfinite(v)]
        expected[row,col]={'focal_mean':np.mean(v),'focal_sd':np.std(v),'focal_min':np.min(v),'focal_max':np.max(v),'focal_range':np.ptp(v)}[kind]
    np.testing.assert_allclose(out,expected,atol=2e-7,rtol=1e-9,equal_nan=True)

@pytest.mark.parametrize('kind',['raster_threshold','aggregate_mean','aggregate_sum'])
def test_threshold_and_grid_aggregation(kind):
    params={'threshold':8} if kind=='raster_threshold' else {'factor':2}
    out,aff=result_grid(run(kind,rasters=[raster()],parameters=params))
    expected=(Z>=8).astype(float) if kind=='raster_threshold' else np.array([[3.5,5.5],[11.5,13.5]])*(4 if kind=='aggregate_sum' else 1)
    np.testing.assert_allclose(out,expected)
    assert aff.a==(10 if kind=='raster_threshold' else 20)

@pytest.mark.parametrize('kind',['sample_random','sample_systematic','sample_stratified','sample_spatial_balanced'])
def test_sample_design_conserves_population(kind):
    z=np.where(Z<=8,0.,1.) if kind=='sample_stratified' else Z
    args={'rasters':[raster(z)],'parameters':{'count':6,'seed':12}}
    result=run(kind,**args);second=run(kind,**args)
    assert result['rows']==second['rows'] and len(result['rows'])==6
    assert len({tuple(row[:2]) for row in result['rows']})==6
    assert sum(row[-1] for row in result['rows'])==pytest.approx(16)
    assert all(row[4]==z[row[0],row[1]] for row in result['rows'])
    if kind=='sample_stratified':
        assert {row[4] for row in result['rows']}=={0,1}
        assert sum(row[-1] for row in result['rows'] if row[4]==0)==pytest.approx(8)

@pytest.mark.parametrize('kind',['global_moran','global_geary','join_count','raster_quantile'])
def test_spatial_statistics_oracles(kind):
    z=(Z>8).astype(float) if kind=='join_count' else Z
    result=run(kind,rasters=[raster(z)],parameters={'quantile':.25} if kind=='raster_quantile' else {'permutations':99,'seed':42})
    m=result['receipt']['metrics']
    if kind=='raster_quantile':assert m['value']==4.75;return
    # Enumerate each unordered rook edge independently.
    pairs=[(z[r,c],z[r2,c2]) for r in range(4) for c in range(4) for r2,c2 in [(r+1,c),(r,c+1)] if r2<4 and c2<4]
    if kind=='join_count':expected=4
    else:
        mean=8.5;ss=sum((v-mean)**2 for v in Z.flat)
        expected=16*sum((a-mean)*(b-mean) for a,b in pairs)/(24*ss) if kind=='global_moran' else 15*sum((a-b)**2 for a,b in pairs)/(48*ss)
    assert m['observed']==pytest.approx(expected) and m['undirected_edges']==24 and .01<=m['p_two_sided']<=1

@pytest.mark.parametrize('kind',['weighted_overlay','topsis','ahp_overlay','constraint_mask','pareto_cells'])
def test_decision_methods_known_dominance_and_consistency(kind):
    a=np.array([[1.,2.],[3.,4.]])
    b=np.array([[4.,3.],[2.,1.]])
    if kind=='constraint_mask':
        result=run(kind,rasters=[raster(a),raster(np.array([[0.,1.],[1.,0.]]),'class')])
        out,_=result_grid(result);np.testing.assert_allclose(out,[[np.nan,2],[3,np.nan]],equal_nan=True);return
    result=run(kind,rasters=[raster(a),raster(b)],directions=['benefit','cost'],
               weights=[1,1] if kind in {'weighted_overlay','topsis'} else [],pairwise=[[1,2],[.5,1]] if kind=='ahp_overlay' else [])
    out,_=result_grid(result)
    if kind=='pareto_cells':np.testing.assert_array_equal(out,[[0,0],[0,1]])
    else:
        assert out[0,0]==pytest.approx(0) and out[1,1]==pytest.approx(1)
        assert np.all(np.diff(out.ravel())>0)
        if kind=='ahp_overlay':assert result['receipt']['metrics']['consistency_ratio']==0

@pytest.mark.parametrize('kind',['zonal_statistics','zonal_classes','clip_raster','rasterize','extract_points','point_kernel_density','polygonize'])
def test_integrated_operators_analytic_spatial_fixture(kind):
    area=vectors(box(X,Y-10,X+15,Y));pts=vectors(Point(X+5,Y-5))
    if kind=='polygonize':
        result=run(kind,rasters=[raster()]);assert len(result['features']['features'])==16
        assert sum(transform(LOCAL,shape(f['geometry'])).area for f in result['features']['features'])==pytest.approx(1600,rel=1e-7)
        return
    result=run(kind,rasters=[raster()],vectors=[pts if kind in {'extract_points','point_kernel_density'} else area],
               parameters={'bandwidth_m':10} if kind=='point_kernel_density' else {})
    if kind=='zonal_statistics':
        row=result['rows'][0];assert row[1:4]==pytest.approx([150,150,150],abs=1e-5);assert row[4]==pytest.approx(4/3,abs=1e-7)
    elif kind=='zonal_classes':
        assert len(result['rows'])==2
        assert [r[2] for r in result['rows']]==pytest.approx([100,50],abs=1e-5)
        assert sum(r[3] for r in result['rows'])==pytest.approx(1)
    elif kind=='extract_points':assert result['rows'][0][-1]==1
    else:
        out,_=result_grid(result)
        if kind=='point_kernel_density':assert out[0,0]==pytest.approx(1/(200*math.pi),rel=1e-7)
        elif kind=='rasterize':assert out[0,0]==1 and out[-1,-1]==0
        else:assert out[0,0]==1 and np.isnan(out[-1,-1])

def test_contract_count_and_invalid_input_rejections():
    client=TestClient(app);response=client.get('/analysis/science/catalog')
    assert response.status_code==200 and response.json()['operation_count']==len(BY_ID)==73
    assert set(m['group'] for m in response.json()['operations'])=={'Vector','Raster','Sampling','Statistics','Decision','Integrated'}
    assert response.json()['ai_tool']['input_schema']['properties']['operation']
    bad=[
        {'operation':'raster_sum','rasters':[raster(),raster(x=X+1)]},
        {'operation':'raster_sum','rasters':[raster(),raster(unit='s')]},
        {'operation':'focal_mean','rasters':[raster()],'parameters':{'radius':1.5}},
        {'operation':'sample_random','rasters':[raster()],'parameters':{'count':17}},
        {'operation':'global_moran','rasters':[raster(np.ones_like(Z))]},
        {'operation':'ahp_overlay','rasters':[raster(),raster(),raster()],'directions':['benefit']*3,'pairwise':[[1,9,1],[1/9,1,9],[1,1/9,1]]},
        {'operation':'buffer','vectors':[vectors(Point(X,Y))],'epsg':4326},
        {'operation':'no_such_method'},
    ]
    for body in bad:
        assert client.post('/analysis/science/run',json=body).status_code==422,body['operation']
    r=client.post('/analysis/science/run',json={'operation':'raster_difference','rasters':[raster(),raster()]})
    assert r.status_code==200 and r.json()['receipt']['metrics']['mean']==0


@pytest.mark.parametrize('kind',['resample_grid','reclassify'])
def test_explicit_resampling_and_class_breaks(kind):
    if kind=='resample_grid':
        z,aff=result_grid(run(kind,rasters=[raster(),raster(Z,x=X+10)]))
        assert np.isnan(z[:,0]).all()
        np.testing.assert_allclose(z[:,1:],Z[:,:3]);assert aff==from_origin(X,Y,10,10)
    else:
        z,_=result_grid(run(kind,rasters=[raster()],breaks=[1,5,9,16]))
        np.testing.assert_array_equal(z,np.array([[0]*4,[1]*4,[2]*4,[2]*4]))
        response=TestClient(app).post('/analysis/science/run',json={'operation':kind,'rasters':[raster()],'breaks':[1,1,2]})
        assert response.status_code==422


@pytest.mark.parametrize('kind',['local_moran','getis_ord_gi_star'])
def test_local_statistics_and_multiplicity(kind):
    r=run(kind,rasters=[raster()],parameters={'permutations':99})
    z,_=result_grid(r)
    u=(Z-8.5)/Z.std()
    expected=u[0,0]*(u[0,1]+u[1,0])/2 if kind=='local_moran' else (u[0,0]+u[0,1]+u[1,0])/np.sqrt(3*13/15)
    assert z[0,0]==pytest.approx(expected)
    p,_=result_grid(run(kind,rasters=[raster()],local_view='p',parameters={'permutations':99,'seed':7}))
    q,_=result_grid(run(kind,rasters=[raster()],local_view='q',parameters={'permutations':99,'seed':7}))
    assert np.isfinite(p).all() and np.all((p>=.01)&(p<=1)) and np.all(q>=p-1e-12)
    assert r['preview']['png'].startswith('data:image/png;base64,')
    assert r['preview']['corners'][0][1]>r['preview']['corners'][3][1]


def test_spatial_gdal_cli_alignment_reference(tmp_path):
    import shutil,subprocess,os
    executable=shutil.which('gdalwarp')
    if executable is None:
        if os.environ.get('GEOFATHOM_REQUIRE_SPATIAL_GDAL')=='1':pytest.fail('GDAL CLI is required for scientific acceptance.')
        pytest.skip('GDAL CLI not installed.')
    import rasterio
    src=tmp_path/'input.tif';dst=tmp_path/'reference.tif'
    input_raster=raster(Z,x=X+10);src.write_bytes(base64.b64decode(input_raster['data']))
    call=subprocess.run([executable,'-overwrite','-t_srs',CRS,'-te',str(X),str(Y-40),str(X+40),str(Y),'-ts','4','4',
                         '-r','near','-srcnodata','nan','-dstnodata','nan','-ot','Float64',str(src),str(dst)],
                        capture_output=True,text=True,timeout=45)
    assert call.returncode==0,call.stderr
    with rasterio.open(dst) as ds:expected=ds.read(1)
    actual,_=result_grid(run('resample_grid',rasters=[raster(),input_raster]))
    np.testing.assert_allclose(actual,expected,rtol=0,atol=1e-10,equal_nan=True)


def test_spatial_medium_grid_mass_and_mask_conservation():
    rng=np.random.default_rng(8);z=rng.normal(100,5,(512,512));z[50:80,100:150]=np.nan
    src=raster(z)
    result=run('aggregate_sum',rasters=[src],parameters={'factor':4});out,aff=result_grid(result)
    assert aff.a==40 and out.shape==(128,128)
    assert np.nansum(out)==pytest.approx(np.nansum(z),rel=1e-12)
    a,_=result_grid(run('focal_mean',rasters=[src],parameters={'radius':2}))
    assert np.array_equal(np.isfinite(a),np.isfinite(z))
    assert a[200,200]==pytest.approx(np.mean(z[198:203,198:203]))
    result=run('sample_spatial_balanced',rasters=[src],parameters={'count':100,'seed':5})
    assert result['receipt']['metrics']['weight_sum']==int(np.isfinite(z).sum())


def test_spatial_gate_rejects_missing_or_skipped_method_evidence(tmp_path):
    from scripts.spatial_science_gate import expected_tests,required_tests,evaluate
    from xml.etree import ElementTree as ET
    root=ET.Element('testsuite')
    names=expected_tests()
    for method,name in names.items():ET.SubElement(root,'testcase',name=name)
    for name in required_tests():
        ET.SubElement(root,'testcase',name=name)
    path=tmp_path/'junit.xml';ET.ElementTree(root).write(path)
    assert evaluate(path)['passed']
    ET.SubElement(root[0],'skipped')
    ET.ElementTree(root).write(path)
    assert not evaluate(path)['passed']


@pytest.mark.parametrize('kind',['raster_distance','focal_quantile','directional_lag_scan','bivariate_moran','robust_overlay','blocked_regression','point_ellipse','zonal_quantiles'])
def test_advanced_spatial_oracles(kind):
    if kind=='raster_distance':
        z=np.zeros((4,4));z[0,0]=1;z[1,1]=np.nan
        result,_=result_grid(run(kind,rasters=[raster(z)]))
        yy,xx=np.indices(z.shape);expected=10*np.sqrt(yy*yy+xx*xx);expected[1,1]=np.nan
        np.testing.assert_allclose(result,expected,equal_nan=True)
    elif kind=='focal_quantile':
        result,_=result_grid(run(kind,rasters=[raster()],parameters={'radius':1,'quantile':.5}))
        assert result[0,0]==3.5 and result[1,1]==6
    elif kind=='directional_lag_scan':
        r=run(kind,rasters=[raster()],parameters={'max_lag':1})
        assert r['rows'][0][:4]==['E-W',1,10.,12] and r['rows'][0][4]==pytest.approx(.5)
        assert r['rows'][1][4]==pytest.approx(8.)
    elif kind=='bivariate_moran':
        r=run(kind,rasters=[raster(),raster(Z*2)],parameters={'permutations':99,'seed':2})
        u=(Z-Z.mean())/Z.std();terms=[]
        for i,j in np.ndindex(Z.shape):
            vals=[u[y,x] for y,x in [(i-1,j),(i+1,j),(i,j-1),(i,j+1)] if 0<=y<4 and 0<=x<4]
            terms.append(u[i,j]*np.mean(vals))
        assert r['receipt']['metrics']['observed']==pytest.approx(np.mean(terms)) and len(r['rows'])==99
    elif kind=='robust_overlay':
        inputs=[raster(),raster(2*Z)]
        args={'rasters':inputs,'weights':[1,3],'directions':['benefit','benefit'],'parameters':{'draws':40,'seed':7,'concentration':10,'threshold':.5}}
        mean,_=result_grid(run(kind,**args));sd,_=result_grid(run(kind,robust_view='sd',**args));prob,_=result_grid(run(kind,robust_view='probability',**args))
        np.testing.assert_allclose(mean,(Z-1)/15,atol=1e-12);assert np.max(sd)<1e-12
        np.testing.assert_array_equal(prob,((Z-1)/15>=.5).astype(float))
    elif kind=='blocked_regression':
        yy,xx=np.indices((8,8));predictor=xx+2*yy;target=3+2*predictor
        result=run(kind,rasters=[raster(target),raster(predictor)],parameters={'block_size_m':20,'folds':4,'ridge_penalty':0,'buffer_m':1})
        out,_=result_grid(result);np.testing.assert_allclose(out,target,atol=1e-10);assert result['receipt']['metrics']['rmse']<1e-10 and len(result['rows'])==64
    elif kind=='point_ellipse':
        points=vectors(Point(X-10,Y),Point(X+10,Y),Point(X,Y-5),Point(X,Y+5))
        r=run(kind,vectors=[points]);m=r['receipt']['metrics']
        assert m['major_sd_m']==pytest.approx(10/np.sqrt(2),abs=1e-6)
        assert m['minor_sd_m']==pytest.approx(5/np.sqrt(2),abs=1e-6)
        assert len(r['rows'])==129
    else:
        r=run(kind,rasters=[raster()],vectors=[vectors(box(X,Y-10,X+15,Y))],parameters={'quantile':.5})
        assert r['rows'][0][-1]==1


def test_overlay_shared_edges_preserve_area_and_valid_inverse_projection():
    # Shared projected boundaries survive WGS84 round trips and all overlays.
    a=vectors(box(X,Y-100,X+100,Y));b=vectors(box(X+50,Y-100,X+150,Y))
    results={kind:run(kind,vectors=[a,b]) for kind in ('intersection','union','difference','symmetric_difference')}
    for result in results.values():
        assert result['receipt']['metrics']['overlay_precision_m']==1e-6
        assert all(shape(f['geometry']).is_valid for f in result['features']['features'])
    areas={k:v['receipt']['metrics']['area_m2'] for k,v in results.items()}
    assert areas['difference']+areas['intersection']==pytest.approx(10000,abs=1e-6)
    assert areas['symmetric_difference']+areas['intersection']==pytest.approx(areas['union'],abs=1e-6)


def test_queen_weights_and_permutation_table():
    r=run('global_moran',rasters=[raster()],neighborhood='queen',parameters={'permutations':99,'seed':3})
    m=r['receipt']['metrics'];assert m['undirected_edges']==42 and len(r['rows'])==99
    u=Z-Z.mean();pairs=[(u[i,j],u[y,x]) for i,j in np.ndindex(u.shape) for y,x in [(i,j+1),(i+1,j-1),(i+1,j),(i+1,j+1)] if 0<=y<4 and 0<=x<4]
    assert m['observed']==pytest.approx(16*sum(a*b for a,b in pairs)/(42*np.sum(u*u)))
    assert all(row[2]==m['observed'] for row in r['rows'])

def test_dirichlet_analytic_uncertainty_opposed_criteria():
    z=np.array([[0.,1.],[0.,1.]])
    args={'rasters':[raster(z),raster(1-z)],'weights':[1,1],'directions':['benefit','benefit'],'parameters':{'draws':40,'seed':7,'concentration':9,'threshold':.5}}
    mean,_=result_grid(run('robust_overlay',**args));sd,_=result_grid(run('robust_overlay',robust_view='sd',**args))
    np.testing.assert_allclose(mean,.5);np.testing.assert_allclose(sd,np.sqrt(.025))
    prob,_=result_grid(run('robust_overlay',robust_view='probability',**args));se,_=result_grid(run('robust_overlay',robust_view='mc_se',**args))
    np.testing.assert_allclose(se,np.sqrt(prob*(1-prob)/40))


@pytest.mark.parametrize('kind,inputs,parameters,recipe',[
    ('global_moran',lambda:{'rasters':[raster()]},{'permutations':99},'spatial_null_distribution'),
    ('directional_lag_scan',lambda:{'rasters':[raster()]},{'max_lag':2},'spatial_directional_lag'),
    ('sample_polygon',lambda:{'vectors':[vectors(box(X,Y-100,X+100,Y))]},{'count':10},'spatial_sample_design'),
    ('blocked_regression',lambda:{'rasters':[raster(3+2*np.arange(64).reshape(8,8)),raster(np.arange(64).reshape(8,8))]},{'block_size_m':20,'folds':4,'ridge_penalty':0,'buffer_m':1},'spatial_oof_agreement'),
    ('zonal_statistics',lambda:{'rasters':[raster()],'vectors':[vectors(box(X,Y-10,X+15,Y))]},{},'spatial_zonal_coverage'),
],ids=['null','lag','sample','prediction','coverage'])
def test_spatial_actual_result_figure_pipeline(kind,inputs,parameters,recipe):
    from terrain.studio_routes import StudioInput
    from terrain.studio_render import render
    result=run(kind,parameters=parameters,**inputs())
    plot=next(p for p in result['figures'] if p['recipe']==recipe)
    image,metadata,table=render(StudioInput(recipe=plot['recipe'],csv=plot['csv'],**plot['bindings']))
    assert image.startswith(b'\x89PNG') and len(table)>1 and metadata['recipe']==recipe
    svg,_,svg_table=render(StudioInput(recipe=plot['recipe'],csv=plot['csv'],format='svg',**plot['bindings']))
    assert b'<svg' in svg and svg_table==table


def test_independent_distance_reference_with_nodata():
    from analysis.science_advanced import euclidean_distance
    z=np.zeros((13,17));z[1,3]=1;z[10,11]=1;z[4:7,5:8]=np.nan
    actual=euclidean_distance(z,7,13)
    targets=np.argwhere(z==1)
    expected=np.array([[min(np.hypot((c-tc)*7,(r-tr)*13) for tr,tc in targets) for c in range(z.shape[1])] for r in range(z.shape[0])])
    expected[~np.isfinite(z)]=np.nan
    np.testing.assert_allclose(actual,expected,atol=1e-10,equal_nan=True)

def test_spatial_randomization_exact_reference():
    from itertools import permutations
    from analysis.science_raster import permutation_stat
    z=np.arange(6,dtype=float).reshape(2,3);n=z.size
    edges=[(i,j) for i in range(n) for j in range(i+1,n) if abs(i//3-j//3)+abs(i%3-j%3)==1]
    u=z.ravel()-z.mean();ss=u@u
    def independent(v):return n*sum(v[i]*v[j] for i,j in edges)/(len(edges)*ss)
    observed=independent(u);expectation=-1/(n-1)
    exact=np.mean([abs(independent(v)-expectation)>=abs(observed-expectation)-1e-14 for v in permutations(u)])
    m,null=permutation_stat(z,'global_moran',999,314,return_null=True)
    assert m['observed']==pytest.approx(observed) and abs(m['p_two_sided']-exact)<.06
    assert len(null)==999 and abs(null.mean()-expectation)<.06

def test_integrated_coverage_with_nodata():
    z=Z.copy();z[0,1]=np.nan
    result=run('zonal_statistics',rasters=[raster(z)],vectors=[vectors(box(X,Y-10,X+15,Y))])
    row=result['rows'][0]
    assert row[1]==pytest.approx(150,abs=1e-6)
    assert row[2]==pytest.approx(150,abs=1e-6)
    assert row[3]==pytest.approx(100,abs=1e-6)
    assert row[4]==pytest.approx(1)

def test_decision_extreme_weight_normalization():
    z=np.array([[0.,1.],[0.,1.]])
    result=run('weighted_overlay',rasters=[raster(z),raster(1-z)],weights=[1e308,1e308],directions=['benefit','benefit'])
    out,_=result_grid(result);np.testing.assert_allclose(out,.5)
    assert result['receipt']['metrics']['normalized_weights']==[.5,.5]

def test_sampling_design_expected_totals():
    from analysis.science_raster import sample_cells
    z=np.arange(30,dtype=float).reshape(5,6);z[1,1]=np.nan
    actual=np.nansum(z);n=np.isfinite(z).sum()
    for kind in ('sample_random','sample_systematic','sample_spatial_balanced'):
        estimates=[]
        for seed in range(200):
            idx,w=sample_cells(z,kind,7,seed)
            assert w.sum()==pytest.approx(n) and len(set(idx))==7
            estimates.append(np.sum(z.flat[idx]*w))
        assert np.mean(estimates)==pytest.approx(actual,rel=.06)


def test_sparse_permutation_population_budget():
    from analysis.science_raster import permutation_stat
    from terrain.studio_data import FigureInputError
    # Many isolated valid observations still incur full-population shuffles.
    z=np.full((1000,1000),np.nan)
    z[::2,::2]=1
    z[0,1]=2
    with pytest.raises(FigureInputError,match='population and edge work budget'):
        permutation_stat(z,'global_moran',199,7)


def test_full_grid_figure_and_output_provenance():
    import csv,io
    from terrain.studio_routes import StudioInput
    from terrain.studio_render import render
    z=np.arange(16,dtype=float).reshape(4,4);z[0,0]=np.nan
    result=run('raster_sum',rasters=[raster(z),raster(z)])
    summary=result['receipt']['raster_summary']
    assert summary['valid_cells']==15 and summary['nodata_cells']==1
    assert summary['quantiles'][0]==[0.,2.] and summary['quantiles'][10]==[.5,16.] and summary['quantiles'][-1]==[1.,30.]
    plot=next(p for p in result['figures'] if p['recipe']=='basic_scatter')
    assert len(list(csv.DictReader(io.StringIO(plot['csv']))))==21
    image,_,_=render(StudioInput(recipe=plot['recipe'],csv=plot['csv'],**plot['bindings']))
    assert image.startswith(b'\x89PNG')
    classified=run('reclassify',rasters=[raster(z)],breaks=[0,5,16])
    assert classified['receipt']['raster_summary']['class_counts']==[[0.,4],[1.,11]]
    plot=next(p for p in classified['figures'] if p['title'].startswith('Class frequency'))
    image,_,_=render(StudioInput(recipe=plot['recipe'],csv=plot['csv'],**plot['bindings']))
    assert image.startswith(b'\x89PNG')
    sample=run('sample_random',rasters=[raster(z)],parameters={'count':3})
    assert sample['receipt']['table_sha256']==hashlib.sha256(sample['csv'].encode()).hexdigest()
    vector=run('centroid',vectors=[vectors(box(X,Y-10,X+10,Y))])
    canonical=json.dumps(vector['features'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    assert vector['receipt']['vector_output_sha256']==hashlib.sha256(canonical).hexdigest()


@pytest.mark.parametrize('kind',['distance_moran','knn_moran','multiscale_moran','empirical_variogram','difference_uncertainty','spatial_lag_regression','geographically_weighted_regression'])
def test_research_depth_oracles(kind):
    if kind in ('distance_moran','knn_moran'):
        # Independent dense row-standardized rook graph for a regular grid.
        u=Z.ravel()-Z.mean();coords=np.indices(Z.shape).reshape(2,-1).T
        d=np.linalg.norm(coords[:,None]-coords[None,:],axis=2)
        if kind=='distance_moran':
            w=(d==1).astype(float);parameters={'distance_m':10.1,'power':1,'permutations':99}
        else:
            np.fill_diagonal(d,np.inf);w=np.zeros_like(d)
            w[np.arange(len(d))[:,None],np.argsort(d,axis=1,kind='stable')[:,:2]]=1
            parameters={'k':2,'power':0,'permutations':99}
        w/=w.sum(axis=1,keepdims=True)
        r=run(kind,rasters=[raster()],parameters=parameters)
        assert r['receipt']['metrics']['observed']==pytest.approx(u@w@u/(u@u))
        assert len(r['rows'])==99 and r['receipt']['metrics']['isolated_cells']==0
    elif kind=='multiscale_moran':
        r=run(kind,rasters=[raster()],parameters={'max_factor':2})
        assert len(r['rows'])==2 and r['rows'][1][:5]==[2,20.,20.,4,1.]
        assert r['rows'][1][5]==pytest.approx(8.5)
        assert r['rows'][1][6]==pytest.approx(np.std([3.5,5.5,11.5,13.5]))
        assert r['rows'][1][7]==pytest.approx(0)
    elif kind=='empirical_variogram':
        r=run(kind,rasters=[raster()],parameters={'distance_m':10.1,'bins':2})
        assert len(r['rows'])==1 and r['rows'][0][3]==24
        assert r['rows'][0][4]==pytest.approx(10)
        assert r['rows'][0][5]==pytest.approx(4.25)
    elif kind=='difference_uncertainty':
        args={'rasters':[raster(Z),raster(Z-5),raster(np.full_like(Z,3)),raster(np.full_like(Z,4))]}
        for rho,expected in [(0,5),(1,1),(-1,7)]:
            r=run(kind,parameters={'correlation':rho},**args);out,_=result_grid(r)
            np.testing.assert_allclose(out,expected)
            assert r['receipt']['metrics']['mean_difference']==5
    elif kind=='spatial_lag_regression':
        rng=np.random.default_rng(22);x=rng.normal(size=(6,6));n=x.size
        coords=np.indices(x.shape).reshape(2,-1).T;w=(np.abs(coords[:,None]-coords[None,:]).sum(axis=2)==1).astype(float)
        w/=w.sum(axis=1,keepdims=True)
        y=np.linalg.solve(np.eye(n)-.35*w,3+2*x.ravel()).reshape(x.shape)
        r=run(kind,rasters=[raster(y),raster(x)])
        m=r['receipt']['metrics'];assert m['rho']==pytest.approx(.35,abs=1e-9)
        assert m['coefficients']==pytest.approx([2],abs=1e-9)
        assert m['intercept']==pytest.approx(3,abs=1e-9)
        assert m['rmse']<1e-9
    else:
        rng=np.random.default_rng(3);x=rng.normal(size=(6,6));y=4+2*x
        r=run(kind,rasters=[raster(y),raster(x)],parameters={'bandwidth_m':30})
        out,_=result_grid(r);np.testing.assert_allclose(out,y,atol=1e-9)
        assert r['receipt']['metrics']['rmse']<1e-9
        assert [row[-1] for row in r['rows']]==pytest.approx([2]*36,abs=1e-9)


def test_large_separable_neighborhood_against_brute_force():
    from analysis.science_raster import focal
    rng=np.random.default_rng(17);z=rng.normal(size=(512,512));z[4:30,4:30]=np.nan
    for kind,fn in [('focal_min',np.nanmin),('focal_max',np.nanmax),('focal_range',lambda a:np.nanmax(a)-np.nanmin(a))]:
        out=focal(z,20,kind)
        assert np.array_equal(np.isfinite(out),np.isfinite(z))
        for i,j in [(0,0),(20,31),(200,200),(511,511)]:
            window=z[max(0,i-20):i+21,max(0,j-20):j+21]
            assert out[i,j]==pytest.approx(fn(window))


def test_research_depth_invalid_and_model_figure():
    from terrain.studio_routes import StudioInput
    from terrain.studio_render import render
    from terrain.studio_data import FigureInputError
    with pytest.raises(FigureInputError,match='nonnegative'):
        run('difference_uncertainty',rasters=[raster(),raster(),raster(-Z),raster()])
    with pytest.raises(FigureInputError,match='fewer neighbors'):
        run('knn_moran',rasters=[raster()],parameters={'k':16})
    with pytest.raises(FigureInputError,match='collinear'):
        run('spatial_lag_regression',rasters=[raster(),raster(Z*2),raster(Z*3)])
    r=run('empirical_variogram',rasters=[raster()],parameters={'distance_m':35,'bins':4})
    plot=next(p for p in r['figures'] if p['title']=='Empirical semivariogram')
    image,_,_=render(StudioInput(recipe=plot['recipe'],csv=plot['csv'],**plot['bindings']))
    assert image.startswith(b'\x89PNG')


def test_large_stable_neighborhood_moments():
    from analysis.science_raster import focal
    rng=np.random.default_rng(13);z=1e9+rng.normal(size=(384,384));z[8:45,2:20]=np.nan
    for kind,fn in [('focal_mean',np.nanmean),('focal_sd',np.nanstd)]:
        out=focal(z,20,kind)
        assert np.array_equal(np.isfinite(out),np.isfinite(z))
        for i,j in [(0,0),(8,21),(200,200),(383,383)]:
            win=z[max(0,i-20):i+21,max(0,j-20):j+21]
            assert out[i,j]==pytest.approx(fn(win),rel=0,abs=2e-6)


def test_geographically_weighted_multiple_coefficients():
    rng=np.random.default_rng(71);x=rng.normal(size=(6,6));z=rng.normal(size=(6,6));y=7+2*x-3*z
    r=run('geographically_weighted_regression',rasters=[raster(y),raster(x),raster(z)],parameters={'bandwidth_m':30})
    assert r['columns'][-2:]==['local_coefficient_first_predictor','local_coefficient_predictor_2']
    np.testing.assert_allclose(np.array(r['rows'])[:,-2:],np.tile([2,-3],(36,1)),atol=1e-9)


@pytest.mark.parametrize('kind',['ordinary_kriging','kriging_uncertainty','spatial_error_regression','difference_probability','sample_srs_estimation','fit_exponential_variogram'])
def test_geostatistical_oracles(kind):
    if kind=='fit_exponential_variogram':
        test_exponential_variogram_calibration_oracle()
        return
    if kind in ('ordinary_kriging','kriging_uncertainty'):
        # Independent augmented ordinary kriging linear system for each target.
        z=np.full((4,4),np.nan);z[0,0]=2;z[0,3]=5;z[3,0]=7;z[3,3]=11
        mask=np.ones_like(z);range_m=17.;sill=4.;nugget=.2
        r=run(kind,rasters=[raster(mask),raster(z)],parameters={'range_m':range_m,'sill':sill,'nugget_ratio':nugget})
        out,_=result_grid(r);xy=np.argwhere(np.isfinite(z))*10;v=z[np.isfinite(z)]
        c=sill*np.exp(-np.linalg.norm(xy[:,None]-xy[None,:],axis=2)/range_m)+nugget*sill*np.eye(4)
        aug=np.block([[c,np.ones((4,1))],[np.ones((1,4)),np.zeros((1,1))]])
        for q in np.ndindex(z.shape):
            k=sill*np.exp(-np.linalg.norm(xy-np.array(q)*10,axis=1)/range_m)
            weights=np.linalg.solve(aug,np.r_[k,1.]);w=weights[:-1]
            expected=w@v if kind=='ordinary_kriging' else np.sqrt(sill-2*w@k+w@c@w)
            assert out[q]==pytest.approx(expected,abs=1e-9)
        for i,row in enumerate(r['rows']):
            keep=np.arange(4)!=i;cc=c[np.ix_(keep,keep)]
            system=np.block([[cc,np.ones((3,1))],[np.ones((1,3)),np.zeros((1,1))]])
            w=np.linalg.solve(system,np.r_[c[keep,i],1.])[:-1]
            assert row[3]==pytest.approx(w@v[keep],abs=1e-9)
    elif kind=='spatial_error_regression':
        rng=np.random.default_rng(74);x=rng.normal(size=(6,6));n=x.size
        coords=np.indices(x.shape).reshape(2,-1).T
        w=(np.abs(coords[:,None]-coords[None,:]).sum(axis=2)==1).astype(float);w/=w.sum(axis=1,keepdims=True)
        y=3+2*x.ravel()+np.linalg.solve(np.eye(n)-.6*w,rng.normal(size=n))
        r=run(kind,rasters=[raster(y.reshape(x.shape)),raster(x)])
        m=r['receipt']['metrics'];design=np.column_stack((np.ones(n),x.ravel()))
        def reference(lam):
            a=np.eye(n)-lam*w;coef=np.linalg.lstsq(a@design,a@y,rcond=None)[0];e=a@(y-design@coef)
            return np.linalg.slogdet(a)[1]-n/2*(np.log(2*np.pi)+1+np.log(e@e/n))
        candidates=np.linspace(-.95,.95,301)
        assert m['log_likelihood']>=max(reference(lam) for lam in candidates)-1e-8
        assert m['log_likelihood']==pytest.approx(reference(m['lambda']),abs=1e-9)
        assert len(m['conditional_coefficient_se'])==1
    elif kind=='difference_probability':
        a=np.full((4,4),5.);b=np.full((4,4),3.);sa=np.full((4,4),3.);sb=np.full((4,4),4.)
        r=run(kind,rasters=[raster(a),raster(b),raster(sa),raster(sb)],parameters={'threshold':2})
        out,_=result_grid(r);np.testing.assert_allclose(out,.5)
        r=run(kind,rasters=[raster(a),raster(b),raster(sa*0),raster(sb*0)],parameters={'threshold':2})
        out,_=result_grid(r);np.testing.assert_allclose(out,0)
    else:
        r=run(kind,rasters=[raster()],parameters={'count':8,'seed':4})
        values=np.array([row[4] for row in r['rows']]);m=r['receipt']['metrics']
        assert m['mean_estimate']==pytest.approx(values.mean())
        assert m['mean_standard_error']==pytest.approx(values.std(ddof=1)*np.sqrt(.5/8))
        census=run(kind,rasters=[raster()],parameters={'count':16})
        assert census['receipt']['metrics']['mean_standard_error']==0


def test_kriging_exactness_mask_and_actual_figure():
    from terrain.studio_routes import StudioInput
    from terrain.studio_render import render
    z=np.full((4,4),np.nan);z[0,0]=2;z[0,3]=5;z[3,0]=7;z[3,3]=11
    mask=np.ones_like(z);mask[2,2]=np.nan
    args={'rasters':[raster(mask),raster(z)],'parameters':{'range_m':20,'sill':3,'nugget_ratio':0}}
    r=run('ordinary_kriging',**args);p,_=result_grid(r)
    np.testing.assert_allclose(p[np.isfinite(z)],z[np.isfinite(z)],atol=1e-9)
    assert np.isnan(p[2,2])
    s,_=result_grid(run('kriging_uncertainty',**args))
    assert np.max(s[np.isfinite(z)])<1e-6 and np.nanmax(s)>0
    plot=next(p for p in r['figures'] if p['title']=='Kriging leave-one-out agreement')
    image,_,_=render(StudioInput(recipe=plot['recipe'],csv=plot['csv'],**plot['bindings']))
    assert image.startswith(b'\x89PNG')


def test_exponential_variogram_calibration_oracle():
    from analysis.science_geostatistics import fit_exponential_variogram
    d=np.linspace(5,100,20);v=1.5+3*(-np.expm1(-d/25))
    fitted,meta=fit_exponential_variogram(d,v,np.arange(1,21),1,100)
    assert meta['range_m']==pytest.approx(25,rel=1e-5)
    assert meta['sill']==pytest.approx(3,rel=1e-5)
    assert meta['nugget_variance']==pytest.approx(1.5,rel=1e-5)
    np.testing.assert_allclose(fitted,v,atol=1e-6)
    # API contract and real empirical bin data, not a synthetic chart.
    z=np.arange(100,dtype=float).reshape(10,10)
    r=run('fit_exponential_variogram',rasters=[raster(z)],parameters={'distance_m':85,'bins':8,'min_range_m':2,'max_range_m':200})
    assert len(r['rows'])>=4 and r['receipt']['metrics']['sill']>0
    assert all(row[2]>=0 for row in r['rows'])


def test_robust_overlay_wilson_endpoints():
    a=np.arange(16,dtype=float).reshape(4,4)
    args={'rasters':[raster(a),raster(a)],'weights':[1,1],'directions':['benefit','benefit'],
          'parameters':{'draws':100,'concentration':10,'threshold':.5,'seed':2}}
    lo,_=result_grid(run('robust_overlay',robust_view='mc_lower',**args))
    hi,_=result_grid(run('robust_overlay',robust_view='mc_upper',**args))
    expected=1.95996398454**2/(100+1.95996398454**2)
    assert lo[0,0]==pytest.approx(0,abs=1e-12) and hi[0,0]==pytest.approx(expected)
    assert hi[-1,-1]==pytest.approx(1) and lo[-1,-1]==pytest.approx(1-expected)
