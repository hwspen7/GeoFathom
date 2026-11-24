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

@pytest.mark.parametrize('kind,expected',[('raster_sum',3*Z),('raster_difference',-Z),('raster_ratio',np.full_like(Z,.5)),('raster_mean',1.5*Z),('raster_sd',.5*Z),('raster_min',Z),('raster_max',2*Z)])
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
    assert response.status_code==200 and response.json()['operation_count']==len(BY_ID)==52
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


def test_explicit_resampling_and_class_breaks():
    z,aff=result_grid(run('resample_grid',rasters=[raster(),raster(Z,x=X+10)]))
    assert np.isnan(z[:,0]).all()
    np.testing.assert_allclose(z[:,1:],Z[:,:3]);assert aff==from_origin(X,Y,10,10)
    z,_=result_grid(run('reclassify',rasters=[raster()],breaks=[1,5,9,16]))
    np.testing.assert_array_equal(z,np.array([[0]*4,[1]*4,[2]*4,[2]*4]))
    response=TestClient(app).post('/analysis/science/run',json={'operation':'reclassify','rasters':[raster()],'breaks':[1,1,2]})
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
