"""Cross-module scientific acceptance over real GeoTIFFs and HTTP contracts.

Every workflow uses the previous output as the next input. Independent
analytical invariants, not screenshots or successful status codes alone,
determine acceptance. Fixtures are synthetic and require no network services.
"""
import base64
import csv
import hashlib
import io
import json

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import transform

from core.main import app
from terrain.advanced import run_terrain

CRS='EPSG:32617'
X,Y=500000,4500000
AFFINE=from_origin(X,Y,10,10)
TO_WORLD=Transformer.from_crs(CRS,4326,always_xy=True).transform
TO_LOCAL=Transformer.from_crs(4326,CRS,always_xy=True).transform


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def raster(z,unit='m',affine=AFFINE,name='synthetic study grid'):
    z=np.asarray(z,float)
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',width=z.shape[1],height=z.shape[0],count=1,dtype='float64',
                      crs=CRS,transform=affine,nodata=np.nan) as ds:
            ds.write(z,1);ds.update_tags(TERRAIN_UNIT=unit)
        raw=mem.read()
    return {'name':name,'data':base64.b64encode(raw).decode(),'unit':unit,'band':1}


def as_input(product):
    # Match the public RasterInput contract; result metadata is not an input.
    return {key:product[key] for key in ('name','data','unit','band')}


def collection(*geometries):
    return {'type':'FeatureCollection','features':[
        {'type':'Feature','geometry':mapping(transform(TO_WORLD,g)),'properties':{}}
        for g in geometries]}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def values(item):
    with MemoryFile(base64.b64decode(item['data'])) as mem,mem.open() as ds:
        assert ds.crs.to_string()==CRS
        return ds.read(1),ds.transform


def run(client,operation,**kwargs):
    response=client.post('/analysis/science/run',json={'operation':operation,**kwargs})
    assert response.status_code==200,(operation,response.text[:1500])
    r=response.json();receipt=r['receipt']
    json.dumps(r,allow_nan=False)
    assert r['operation']==receipt['operation']==operation
    assert receipt['table_sha256']==sha(r['csv'].encode())
    if r['columns']:
        table=list(csv.reader(io.StringIO(r['csv'])))
        assert table[0]==r['columns'] and len(table)==len(r['rows'])+1
    else:
        assert r['csv']==''
    if r['features'] is not None:
        canonical=json.dumps(r['features'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        assert receipt['vector_output_sha256']==sha(canonical)
    if r['raster']:
        product=r['raster'];raw=base64.b64decode(product['data'])
        assert product['sha256']==receipt['raster_sha256']==sha(raw)
        z,_=values(product);summary=receipt['raster_summary']
        assert summary['valid_cells']==int(np.isfinite(z).sum())
        assert summary['nodata_cells']==int(np.isnan(z).sum())
        assert summary['minimum']==float(np.nanmin(z)) and summary['maximum']==float(np.nanmax(z))
    return r


def figure(client,result,title,format='png'):
    p=next(item for item in result['figures'] if item['title']==title)
    body={'recipe':p['recipe'],'format':format,**p['bindings']}
    if p['raster']:
        body['rasters']=[as_input(result['raster'])]
    else:
        body['csv']=p['csv']
    response=client.post('/terrain/studio/render',json=body)
    assert response.status_code==200,(title,response.text[:1500])
    plot=response.json();raw=base64.b64decode(plot['figure'])
    assert len(raw)>100 and plot['metadata']['recipe']==p['recipe']
    if format=='png':assert raw.startswith(b'\x89PNG')
    elif format=='svg':assert b'<svg' in raw
    else:assert raw.startswith(b'%PDF')
    if not p['raster']:assert plot['metadata']['csv_sha256']==sha(p['csv'].encode())
    return plot


def test_workflow_terrain_to_zonal_science(client,tmp_path):
    # Actual Terrain computation and GeoTIFF export, not a fabricated result.
    yy,xx=np.indices((25,25));dem=100.+xx+2*yy
    path=tmp_path/'study-dem.tif'
    with rasterio.open(path,'w',driver='GTiff',height=25,width=25,count=1,dtype='float32',
                       crs=CRS,transform=AFFINE,nodata=-9999) as ds:
        ds.write(dem.astype('float32'),1)
    study=box(X+20,Y-230,X+230,Y-20)
    geom=mapping(transform(TO_WORLD,study))
    terrain=run_terrain(path,geom,'elevation')['raster']
    source={'name':'Terrain elevation','data':terrain['geotiff'],'unit':terrain['unit'],'band':1}
    z,aff=values(source);valid=np.isfinite(z);assert valid.sum()>100
    rr,cc=np.indices(z.shape);east=aff.c+(cc+.5)*aff.a;north=aff.f+(rr+.5)*aff.e
    expected=100+(east-X)/10-.5+2*((Y-north)/10-.5)
    np.testing.assert_allclose(z[valid],expected[valid],atol=1e-4)
    threshold=float(np.nanmedian(z))
    binary=run(client,'raster_threshold',rasters=[source],parameters={'threshold':threshold})
    b,ba=values(binary['raster']);assert ba==aff
    np.testing.assert_array_equal(b[valid],(z[valid]>=threshold).astype(float))
    np.testing.assert_array_equal(np.isfinite(b),valid)
    derived=as_input(binary['raster'])
    zones=run(client,'polygonize',rasters=[derived])
    polygons=zones['features'];assert polygons['features']
    area=sum(transform(TO_LOCAL,shape(f['geometry'])).area for f in polygons['features'])
    assert area==pytest.approx(valid.sum()*abs(aff.a*aff.e),rel=1e-7)
    result=run(client,'zonal_classes',rasters=[derived],vectors=[polygons])
    assert sum(row[2] for row in result['rows'])==pytest.approx(area,rel=1e-7)
    assert binary['receipt']['raster_sources'][0]['sha256']==sha(base64.b64decode(source['data']))
    figure(client,binary,'Class frequency (full valid grid)','svg')


def test_workflow_vector_sampling_density_join(client):
    region=box(X,Y-100,X+100,Y)
    study=collection(region)
    sample=run(client,'sample_polygon',vectors=[study],parameters={'count':24,'seed':123})
    points=sample['features'];assert len(points['features'])==24
    projected=[transform(TO_LOCAL,shape(f['geometry'])) for f in points['features']]
    assert all(region.covers(p) for p in projected)
    join=run(client,'spatial_join',vectors=[points,study])
    assert len(join['rows'])==24 and {r[0] for r in join['rows']}==set(range(24))
    template=raster(np.ones((10,10)))
    density=run(client,'point_kernel_density',rasters=[template],vectors=[points],parameters={'bandwidth_m':10})
    z,_=values(density['raster']);target=Point(X+55,Y-55)
    expected=sum(np.exp(-target.distance(p)**2/200)/(200*np.pi)
                 for p in projected if target.distance(p)<=40)
    assert z[5,5]==pytest.approx(expected,rel=1e-8,abs=1e-12)
    assert np.nanmin(z)>=0
    figure(client,sample,'Polygon sample distribution')


def test_workflow_multicriteria_constraint_and_uncertainty(client):
    a=np.arange(64,dtype=float).reshape(8,8);b=63-a
    a[0,0]=np.nan;b[0,0]=np.nan
    sources=[raster(a),raster(b)];valid=np.isfinite(a)
    score=run(client,'weighted_overlay',rasters=sources,weights=[3,1],directions=['benefit','cost'])
    z,_=values(score['raster'])
    expected=(a-1)/62
    np.testing.assert_allclose(z,expected,equal_nan=True,atol=1e-12)
    mask=run(client,'raster_threshold',rasters=[as_input(score['raster'])],parameters={'threshold':.5})
    restricted=run(client,'constraint_mask',rasters=[as_input(score['raster']),as_input(mask['raster'])])
    out,_=values(restricted['raster'])
    np.testing.assert_allclose(out,np.where(expected>=.5,expected,np.nan),equal_nan=True,atol=1e-12)
    robust=run(client,'robust_overlay',rasters=sources,weights=[3,1],directions=['benefit','cost'],
               robust_view='mean',parameters={'draws':40,'seed':12})
    mean,_=values(robust['raster']);np.testing.assert_allclose(mean,z,equal_nan=True,atol=1e-12)
    uncertain=run(client,'robust_overlay',rasters=sources,weights=[3,1],directions=['benefit','cost'],
                  robust_view='sd',parameters={'draws':40,'seed':12})
    sd,_=values(uncertain['raster']);assert np.nanmax(sd)<1e-12
    assert np.count_nonzero(np.isfinite(out))==np.count_nonzero(valid&(expected>=.5))
    figure(client,score,'Criterion weights','pdf')


def test_workflow_spatial_models_and_geostatistics(client):
    rng=np.random.default_rng(617);x=rng.normal(size=(8,8));y=4+3*x
    oof=run(client,'blocked_regression',rasters=[raster(y),raster(x)],
            parameters={'block_size_m':20,'folds':4,'ridge_penalty':0,'buffer_m':1})
    prediction,_=values(oof['raster']);np.testing.assert_allclose(prediction,y,atol=1e-9)
    assert oof['receipt']['metrics']['rmse']<1e-9
    residual=run(client,'raster_difference',rasters=[raster(y),as_input(oof['raster'])])
    e,_=values(residual['raster']);assert np.nanmax(abs(e))<1e-9
    figure(client,oof,'Held-out observations versus prediction')
    # Reuse sparse field observations, and check kriging exactness, uncertainty,
    # and the actual leave-one-out table passed to the publication renderer.
    sparse=np.full((8,8),np.nan);sparse[::3,::3]=y[::3,::3]
    args={'rasters':[raster(np.ones_like(y)),raster(sparse)],
          'parameters':{'range_m':20,'sill':4,'nugget_ratio':0}}
    p=run(client,'ordinary_kriging',**args);s=run(client,'kriging_uncertainty',**args)
    pz,_=values(p['raster']);sz,_=values(s['raster']);known=np.isfinite(sparse)
    np.testing.assert_allclose(pz[known],sparse[known],atol=1e-9)
    assert np.max(sz[known])<1e-6 and np.max(sz[~known])>0
    assert p['rows']==s['rows'] and len(p['rows'])==int(known.sum())
    figure(client,p,'Kriging leave-one-out agreement','svg')


def test_workflow_reproducibility_and_error_recovery(client):
    z=np.arange(36,dtype=float).reshape(6,6);z[0,0]=np.nan
    source=raster(z);before=json.dumps(source,sort_keys=True)
    args={'rasters':[source],'parameters':{'permutations':99,'seed':29}}
    first=run(client,'global_moran',**args)
    assert first['rows']==run(client,'global_moran',**args)['rows']
    changed=run(client,'global_moran',rasters=[source],parameters={'permutations':99,'seed':30})
    assert changed['rows']!=first['rows']
    # A bad request must not poison the next request or silently align grids.
    invalid=[
      {'operation':'raster_sum','rasters':[source,raster(z,affine=from_origin(X+1,Y,10,10))]},
      {'operation':'raster_sum','rasters':[source,raster(z,unit='s')]},
      {'operation':'sample_random','rasters':[source],'parameters':{'count':36}},
      {'operation':'knn_moran','rasters':[source],'parameters':{'k':1.5}},
      {'operation':'not_an_operation','rasters':[source]},
    ]
    for body in invalid:
        response=client.post('/analysis/science/run',json=body)
        assert response.status_code==422,(body['operation'],response.text[:300])
        assert response.json().get('detail')
    last=run(client,'global_moran',**args)
    assert first['receipt']==last['receipt'] and first['csv']==last['csv']
    assert before==json.dumps(source,sort_keys=True)
    figure(client,last,'Random-label permutation distribution')


def test_workflow_medium_grid_mass_and_reuse(client):
    rng=np.random.default_rng(19);z=rng.uniform(0,100,(512,512));z[4:24,7:39]=np.nan
    source=raster(z)
    coarse=run(client,'aggregate_sum',rasters=[source],parameters={'factor':4})
    v,aff=values(coarse['raster'])
    assert v.shape==(128,128) and aff.a==40 and aff.e==-40
    assert np.nansum(v)==pytest.approx(np.nansum(z),rel=1e-12)
    second=run(client,'aggregate_sum',rasters=[as_input(coarse['raster'])],parameters={'factor':4})
    w,aff=values(second['raster'])
    assert w.shape==(32,32) and aff.a==160
    assert np.nansum(w)==pytest.approx(np.nansum(z),rel=1e-12)
    assert second['receipt']['raster_sources'][0]['sha256']==coarse['raster']['sha256']
    assert second['preview'] is not None
