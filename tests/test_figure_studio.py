"""Render every registered studio recipe, with independent numerical oracles."""
import base64
import csv
import io
import math
import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from terrain.studio_catalog import RECIPES, BY_ID, catalog
from terrain.studio_data import (Table, FigureInputError, pareto_mask, average_rank,
                                 sobol_indices, morris_effects, rectangular_grid)
from terrain.studio_routes import StudioInput, RasterInput
from terrain.studio_render import render


def csv_text(headers, rows):
    f=io.StringIO()
    writer=csv.writer(f)
    writer.writerow(headers)
    writer.writerows(rows)
    return f.getvalue()


def grid(name, values, x=500000, unit='m'):
    values=np.asarray(values,dtype=np.float32)
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',height=values.shape[0],width=values.shape[1],
                      count=1,dtype='float32',transform=from_origin(x,4500000,10,10),
                      crs='EPSG:32617',nodata=-9999) as ds:
            ds.write(values,1)
            ds.update_tags(TERRAIN_UNIT=unit)
        return RasterInput(name=name,data=base64.b64encode(mem.read()).decode(),unit=unit)


@pytest.fixture(scope='module')
def raster_fixture():
    yy,xx=np.indices((12,14))
    z=100+xx*2+yy+np.sin(xx/3)
    return [grid('Baseline',z),grid('Candidate',z+2),grid('Sigma',np.ones_like(z))],grid('Classes',(xx+yy)%4,unit='class')


def table_input(recipe):
    rows=[]
    for i in range(12):
        y=4+i*.8+math.sin(i)
        rows.append([i,'Scenario '+str(i),['North','South','East'][i%3],y,3+i*.4,
                     y-1,y+2,2+i%4])
    text=csv_text(['time','name','group','value','other','lower','upper','size'],rows)
    args=dict(recipe=recipe,csv=text,x='time',y='value',z='other',group='group',
              low='lower',high='upper',columns=['value','other'],width_mm=100,height_mm=80,dpi=120)
    if recipe in {'grouped_bar','stacked_bar','horizontal_bar','lollipop','pie','rank_change','tornado','radar'}:
        args['x']='name'
    if recipe=='bubble':args['z']='size'
    if recipe=='sobol':
        rng=np.random.default_rng(42);a,b=rng.random((2,128,2))
        f=lambda x: x[:,0]+2*x[:,1]
        hybrids=[np.column_stack((b[:,0],a[:,1])),np.column_stack((a[:,0],b[:,1]))]
        args.update(csv=csv_text(['A','B','factor1','factor2'],zip(f(a),f(b),f(hybrids[0]),f(hybrids[1]))),
                    x='A',y='B',columns=['factor1','factor2'])
    if recipe=='morris':
        points=[('t1',0,0,0),('t1',.5,0,1),('t1',.5,.5,2.5),
                ('t2',.5,.5,2.5),('t2',1,.5,3.5),('t2',1,1,5)]
        args.update(csv=csv_text(['trajectory','a','b','response'],points),x='trajectory',y='response',columns=['a','b'])
    if recipe=='response_surface':
        args.update(csv=csv_text(['a','b','response'],[(i,j,i*i+j) for i in range(3) for j in range(4)]),x='a',y='b',z='response')
    if recipe in {'autocorrelation','lag_scatter','rolling_mean','seasonal_cycle','seasonal_anomaly','seasonal_heatmap'}:args['parameter']=3
    return StudioInput(**args)


@pytest.mark.parametrize('recipe',list(BY_ID))
def test_every_recipe_renders_actual_data(recipe,raster_fixture):
    if BY_ID[recipe][3]=='table':
        body=table_input(recipe)
    else:
        rasters,classes=raster_fixture
        selected=[classes] if recipe=='raster_classes' else rasters[:3] if recipe=='raster_significant_change' else rasters[:2] if recipe in {'raster_difference','raster_uncertainty','raster_exceedance','raster_matrix'} else rasters[:1]
        body=StudioInput(recipe=recipe,rasters=selected,width_mm=115,height_mm=90,dpi=120)
    image,metadata,table=render(body)
    assert image[:8]==b'\x89PNG\r\n\x1a\n'
    assert len(image)>2000
    assert metadata['recipe']==recipe and metadata['used_count']>0
    if BY_ID[recipe][3]=='table':assert len(table)>=2
    if recipe=='raster_difference':
        assert metadata['mean']==pytest.approx(2)
    if recipe=='raster_uncertainty':
        assert metadata['mean']==pytest.approx(math.sqrt(2))
    if recipe=='raster_exceedance':assert metadata['mean']==1
    if recipe=='raster_significant_change':assert metadata['mean']==1
    if recipe=='morris':assert np.array([row[1:] for row in table[1:]])==pytest.approx(np.array([[2,0],[3,0]]))
    if recipe=='rank_change':assert table[1][1]==12
    if recipe=='pareto':assert table[1][-1] in (0,1)


def test_catalog_count_and_unique_recipes():
    assert len(RECIPES)==len(BY_ID)==len(catalog())==51
    assert len({r['title'] for r in catalog()})==51


@pytest.mark.parametrize('fmt,magic',[('svg',b'<?xml'),('pdf',b'%PDF'),('tiff',b'II*\x00')])
def test_publication_formats(fmt,magic):
    body=table_input('parallel_coordinates').model_copy(update={'format':fmt,'dpi':300})
    data,_,_=render(body)
    assert data.startswith(magic)


def test_numerical_pareto_matches_brute_force_including_ties():
    x=np.array([1.,1.,2.,2.,3.,4.,1.]);y=np.array([3.,3.,2.,4.,1.,5.,4.])
    for mx in (False,True):
        for my in (False,True):
            a=-x if mx else x;b=-y if my else y
            expected=[not any((a[j]<=a[i] and b[j]<=b[i]) and (a[j]<a[i] or b[j]<b[i]) for j in range(len(x))) for i in range(len(x))]
            assert pareto_mask(x,y,mx,my).tolist()==expected
    assert average_rank(np.array([5.,5.,1.])).tolist()==[1.5,1.5,3.]


def test_sobol_additive_model_and_morris_linear_effects():
    rng=np.random.default_rng(8);a,b=rng.random((2,30000,2))
    f=lambda x:x[:,0]+2*x[:,1]
    first,total=sobol_indices(f(a),f(b),[f(np.column_stack((b[:,0],a[:,1]))),f(np.column_stack((a[:,0],b[:,1])))])
    assert first==pytest.approx([.2,.8],abs=.03)
    assert total==pytest.approx([.2,.8],abs=.03)
    result=morris_effects(np.array(['a']*3+['b']*3),np.array([0,1,2.5,2.5,3.5,5.]),np.array([[0,0],[.5,0],[.5,.5],[.5,.5],[1,.5],[1,1]]))
    assert result[0]==pytest.approx([2,3]);assert result[1]==pytest.approx([0,0])


def test_strict_data_rejection_and_missing_values(raster_fixture):
    with pytest.raises(FigureInputError):Table('x,x\n1,2')
    with pytest.raises(FigureInputError):Table('x,y\n1')
    with pytest.raises(FigureInputError):Table('x\nNaN').numeric('x')
    a,_,n=Table('x,y\n1,2\n,3\n4,5').aligned(['x','y'])
    assert n==2 and a[0].tolist()==[1,4]
    with pytest.raises(FigureInputError):rectangular_grid(np.array([1,2,2]),np.array([1,2,3]),np.array([1,2,3]))
    with pytest.raises(FigureInputError):sobol_indices(np.ones(8),np.ones(8),[np.ones(8)])
    with pytest.raises(FigureInputError):morris_effects(np.array(['a']*3),np.ones(3),np.array([[0,0],[.5,.5],[1,1]]))
    rasters,_=raster_fixture
    with pytest.raises(FigureInputError,match='must match'):
        render(StudioInput(recipe='raster_difference',rasters=[rasters[0],grid('Shifted',np.ones((12,14)),x=500010)]))
    with pytest.raises(FigureInputError,match='contain'):
        render(StudioInput(recipe='uncertainty_band',csv='x,y,l,h\n1,2,3,4\n2,3,4,5',x='x',y='y',low='l',high='h'))
    with pytest.raises(FigureInputError,match='equally spaced'):
        render(StudioInput(recipe='rolling_mean',csv='x,y\n1,2\n2,3\n4,5',x='x',y='y',parameter=2))


def test_api_catalog_render_metadata_and_validation():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from terrain.studio_routes import router
    app=FastAPI();app.include_router(router)
    with TestClient(app) as client:
        response=client.get('/terrain/studio/catalog')
        assert response.status_code==200
        assert response.json()['additional_recipe_count']+response.json()['legacy_recipe_count']==75
        response=client.post('/terrain/studio/render',json=table_input('pareto').model_dump())
        assert response.status_code==200,response.text
        result=response.json()
        assert len(result['metadata']['csv_sha256'])==64
        assert result['table'][0][-1]=='nondominated'
        assert base64.b64decode(result['figure']).startswith(b'\x89PNG')
        assert client.post('/terrain/studio/render',json={'recipe':'missing'}).status_code==422
        assert client.post('/terrain/studio/render',json={'recipe':'pie','csv':'a,b\nX,-2','x':'a','y':'b'}).status_code==422
