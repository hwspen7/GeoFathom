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
    from terrain.studio_domain_catalog import IDS
    if recipe in IDS:
        body=domain_input(recipe,raster_fixture)
    elif BY_ID[recipe][3]=='table':
        body=table_input(recipe)
    else:
        rasters,classes=raster_fixture
        selected=[classes] if recipe=='raster_classes' else rasters[:3] if recipe=='raster_significant_change' else rasters[:2] if recipe in {'raster_difference','raster_uncertainty','raster_exceedance','raster_matrix'} else rasters[:1]
        extra=dict(csv='e,n\n500005,4499995\n500015,4499995\n500025,4499995',x='e',y='n') if recipe=='raster_profile' else {}
        body=StudioInput(recipe=recipe,rasters=selected,width_mm=115,height_mm=90,dpi=120,**extra)
    image,metadata,table=render(body)
    assert image[:8]==b'\x89PNG\r\n\x1a\n'
    assert len(image)>2000
    assert metadata['recipe']==recipe and metadata['used_count']>0
    assert metadata['family']==BY_ID[recipe][2]
    assert metadata['layout']['canvas_pixels'][0]>0
    assert metadata['plot_table_rows']==max(0,len(table)-1)
    import os,json
    from pathlib import Path
    target=os.environ.get('GEOFATHOM_FIGURE_REVIEW_DIR')
    if target:
        folder=Path(target);folder.mkdir(parents=True,exist_ok=True)
        (folder/(recipe+'.png')).write_bytes(image)
        (folder/(recipe+'.json')).write_text(json.dumps(metadata,indent=2,allow_nan=False),encoding='utf-8')
    # Verify vector output for each recipe, not only one representative plot.
    svg,_,_=render(body.model_copy(update={'format':'svg'}))
    assert svg.startswith(b'<?xml') and b'<svg' in svg
    pdf,_,_=render(body.model_copy(update={'format':'pdf'}))
    assert pdf.startswith(b'%PDF')
    from pypdf import PdfReader
    page=PdfReader(io.BytesIO(pdf)).pages[0]
    assert float(page.mediabox.width)==pytest.approx(body.width_mm/25.4*72,abs=.01)
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
    assert len(RECIPES)==len(BY_ID)==len(catalog())==180
    assert len({r['title'] for r in catalog()})==180


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
        assert response.json()['additional_recipe_count']+response.json()['legacy_recipe_count']==204
        assert response.json()['basic_recipe_count']==36 and response.json()['professional_recipe_count']==168
        response=client.post('/terrain/studio/render',json=table_input('pareto').model_dump())
        assert response.status_code==200,response.text
        result=response.json()
        assert len(result['metadata']['csv_sha256'])==64
        assert result['table'][0][-1]=='nondominated'
        assert base64.b64decode(result['figure']).startswith(b'\x89PNG')
        assert client.post('/terrain/studio/render',json={'recipe':'missing'}).status_code==422
        assert client.post('/terrain/studio/render',json={'recipe':'pie','csv':'a,b\nX,-2','x':'a','y':'b'}).status_code==422


def test_raster_table_exact_alignment_and_bounded_sampling(raster_fixture):
    from terrain.studio_data import raster_table
    rasters,_=raster_fixture
    out=raster_table(rasters[:2],limit=20)
    receipt=out['metadata']
    assert receipt['population_cells']==168 and receipt['sample_cells']<=20 and receipt['stride']==9
    data=Table(out['csv'])
    assert len(data.rows)==receipt['sample_cells']
    assert np.allclose(data.numeric(data.names[3])-data.numeric(data.names[2]),2)
    assert data.numeric('grid_x')[0]==500005
    assert data.numeric('grid_y')[0]==4499995
    full=raster_table(rasters[:1])
    assert full['metadata']['sampling']=='all_cells' and full['metadata']['sample_cells']==168


@pytest.mark.parametrize('style',['heatmap','filled','contour','surface'])
def test_response_views_use_identical_actual_design_and_mask_missing(style):
    rows=[(a,b,None if (a,b)==(4,5) else a+2*b) for b in [0,2,5] for a in [0,1,4]]
    body=StudioInput(recipe='response_surface',csv=csv_text(['a','b','response'],rows),x='a',y='b',z='response',response_style=style,optimum='max',width_mm=180,height_mm=130)
    png,meta,table=render(body)
    assert png.startswith(b'\x89PNG')
    assert meta['grid_positions']==9 and meta['missing_positions']==1 and meta['used_count']==8
    assert meta['observed_optimum']==[1.,5.,11.]
    assert table[-1]==[4.,5.,None]
    assert meta['interpolation']==('none' if style=='heatmap' else 'visual interpolation within complete evaluated cells only')
    assert meta['layout']['potentially_clipped_axes']==[]


def test_profile_gaps_delta_and_actual_raster_sampling(raster_fixture):
    body=StudioInput(recipe='multi_line',csv='distance,base,scenario\n0,1,3\n10,,4\n20,2,\n30,3,5',x='distance',columns=['base','scenario'],profile_style='delta')
    _,meta,table=render(body)
    assert table[1:]==[[0.,2.],[10.,None],[20.,None],[30.,2.]]
    assert meta['series_valid_counts']==[2]
    rasters,_=raster_fixture
    body=StudioInput(recipe='raster_profile',rasters=rasters[:2],csv='e,n\n500005,4499995\n500015,4499995\n500155,4499995',x='e',y='n',profile_style='delta')
    _,meta,table=render(body)
    assert table[1][1]==pytest.approx(2)
    assert table[2]==pytest.approx([10,2])
    assert table[3]==[150.,None]
    assert meta['used_count']==2


def test_profile_multiple_uncertainty_bands_preserve_missing_bounds():
    csv='distance,a,al,ah,b,bl,bh\n0,10,9,11,12,11,13\n5,11,,12,13,12,14\n10,12,11,13,14,13,15'
    _,meta,table=render(StudioInput(recipe='multi_line',csv=csv,x='distance',columns=['a','al','ah','b','bl','bh'],profile_style='bands'))
    assert table[2]==[5.,11.,None,12.,13.,12.,14.]
    assert meta['series_valid_counts']==[3,2,3,3,3,3]
    assert 'Supplied pointwise' in meta['interval_note']


def test_matrix_shared_classes_and_range(raster_fixture):
    rasters,classes=raster_fixture
    _,meta,_=render(StudioInput(recipe='raster_matrix',rasters=rasters[:2],map_style='diverging',map_columns=2,map_min=-150,map_max=150,map_common_mask=True,width_mm=230,height_mm=140))
    assert meta['display_min']==-150 and meta['display_max']==150
    assert meta['common_cells']==168 and meta['map_columns']==2
    assert meta['layout']['potentially_clipped_axes']==[]
    _,meta,_=render(StudioInput(recipe='raster_matrix',rasters=[classes,classes],map_style='categorical',width_mm=230,height_mm=140))
    assert meta['class_codes']==[0.,1.,2.,3.]
    _,meta,_=render(StudioInput(recipe='raster_matrix',rasters=rasters[:2],class_breaks=[90,110,130,150],width_mm=230,height_mm=140))
    assert meta['display_min']==90 and meta['display_max']==150


def test_publication_composer_vector_export_and_reproducible_raster(raster_fixture):
    from terrain.studio_routes import CompositionInput,render_composition
    from PIL import Image
    from pypdf import PdfReader
    rasters,_=raster_fixture
    panels=[StudioInput(recipe='raster_continuous',rasters=rasters[:1],title='Terrain map'),
            table_input('response_surface').model_copy(update={'response_style':'heatmap','title':'Response grid'}),
            table_input('multi_line').model_copy(update={'title':'Profile curves','profile_style':'overlay'}),
            table_input('pareto').model_copy(update={'title':'Tradeoffs'})]
    body=CompositionInput(panels=panels,title='Combined scientific figure',caption='Observed and computed quantities.',columns=2,width_mm=240,height_mm=200)
    png,meta=render_composition(body)
    assert meta['panel_count']==4 and [p['label'] for p in meta['panels']]==list('abcd')
    assert meta['layout']['potentially_clipped_axes']==[]
    image=Image.open(io.BytesIO(png))
    assert image.width==pytest.approx(240/25.4*120,abs=1)
    assert image.height==pytest.approx(200/25.4*120,abs=1)
    second,_=render_composition(body)
    assert np.array_equal(np.asarray(image),np.asarray(Image.open(io.BytesIO(second))))
    pdf,_=render_composition(body.model_copy(update={'format':'pdf'}))
    page=PdfReader(io.BytesIO(pdf)).pages[0]
    text=page.extract_text()
    assert all(title in text for title in ['Terrain map','Response grid','Profile curves','Tradeoffs','Combined scientific figure'])
    assert float(page.mediabox.width)==pytest.approx(240/25.4*72,abs=.01)
    svg,_=render_composition(body.model_copy(update={'format':'svg'}))
    assert b'Combined scientific figure' in svg and b'Response grid' in svg

def test_native_vector_panel_composes_with_extended_recipes():
    from terrain.studio_routes import CompositionInput,LegacyPanel,render_composition
    from terrain.figure_routes import FigurePDFInput
    from pypdf import PdfReader
    scene=FigurePDFInput(title='Native exact histogram',primitives=[
        {'kind':'rect','x':100,'y':150,'width':50,'height':200,'fill':'#24639b'},
        {'kind':'text','x':100,'y':100,'text':'Native histogram','font_size':22,'fill':'#222222'}])
    legacy=LegacyPanel(scene=scene,table=[['bin','count'],[1,3]],provenance={'source':'recorded'})
    body=CompositionInput(panels=[legacy,table_input('pareto')],format='pdf')
    pdf,meta=render_composition(body)
    assert meta['panels'][0]['table']==[['bin','count'],[1,3]]
    assert 'Native histogram' in PdfReader(io.BytesIO(pdf)).pages[0].extract_text()

def test_missing_global_design_and_regular_series_rejected():
    with pytest.raises(FigureInputError,match='complete aligned design'):
        render(StudioInput(recipe='sobol',csv='A,B,H\n1,2,3\n2,,4\n3,4,5',x='A',y='B',columns=['H']))
    with pytest.raises(FigureInputError,match='every observation'):
        render(StudioInput(recipe='rolling_mean',csv='x,y\n0,1\n1,\n2,3\n3,4',x='x',y='y',parameter=2))


def domain_input(recipe,raster_fixture):
    """Numerical inputs cover every new domain recipe without fabricated runtime data."""
    from terrain.studio_domain_catalog import MIN_RASTERS
    if BY_ID[recipe][3]=='raster':
        rasters,classes=raster_fixture
        yy,xx=np.indices((12,14))
        if recipe.startswith('spectral_'):
            bands=[grid('NIR',.42+.008*xx+.004*yy,unit='reflectance'),
                   grid('Red',.16+.004*xx+.001*yy,unit='reflectance'),
                   grid('Blue',.08+.001*xx+.003*yy,unit='reflectance')]
            selected=bands[:MIN_RASTERS.get(recipe,2)]
        elif recipe.startswith('land_'):
            selected=[classes,grid('Later classes',(xx+yy+(xx>6))%4,unit='class')][:MIN_RASTERS.get(recipe,1)]
        else:selected=rasters[:MIN_RASTERS.get(recipe,1)]
        return StudioInput(recipe=recipe,rasters=selected,width_mm=115,height_mm=90)
    values=[]
    for i in range(24):
        v=5+i*.2+math.sin(i*.8)
        values.append([i+1,'Scenario '+str(i),['North','South'][i%2],v,2+i*.3+math.cos(i*.47),1+i%5,
                       i%2,int(i%3==0),.15+.7*(i%2)+.03*math.sin(i),.2+.008*i,.3+.005*i+.015*math.sin(i)])
    headers=['time','name','group','value','other','size','truth','predicted','probability','reflectance_a','reflectance_b']
    args=dict(recipe=recipe,csv=csv_text(headers,values),x='time',y='value',z='other',group='group',
              columns=['value','other'],width_mm=115,height_mm=90)
    if recipe in {'basic_column','basic_waterfall','basic_paired_change','basic_pareto_frequency','basic_table_heatmap','opt_regret'}:args['x']='name'
    if recipe.startswith('spectral_'):
        args.update(y='reflectance_a',columns=['reflectance_a','reflectance_b'])
    if recipe in {'model_roc','model_pr','model_threshold','model_gain','model_lift','model_calibration'}:args.update(x='truth',y='probability')
    if recipe in {'model_confusion','model_class_metrics'}:args.update(x='truth',y='predicted')
    if recipe=='opt_interaction':
        args.update(csv=csv_text(['a','b','response'],[(i,j,i*i+j*i) for i in range(4) for j in range(3)]),x='a',y='b',z='response')
    if recipe=='hydro_flashiness':
        args.update(csv=csv_text(['time','discharge','period'],[(i,2+math.sin(i),j) for j in ['A','B'] for i in range(8)]),x='time',y='discharge',group='period')
    return StudioInput(**args)


def test_domain_numeric_oracles():
    from terrain.studio_domain_model import binary_curve,pca,domination_counts
    from terrain.studio_domain_raster import local_moments,patch_labels,safe_ratio
    from terrain.studio_domain_table import ranks
    y=np.array([0.,1.,0.,1.]);s=np.array([.1,.9,.2,.8])
    _,tp,fp,p,n=binary_curve(y,s)
    assert p==n==2 and tp.tolist()==[0,1,2,2,2] and fp.tolist()==[0,0,0,1,2]
    assert ranks(np.array([2.,1.,2.])).tolist()==[2.5,1.,2.5]
    m=np.array([[1.,2.],[2.,4.],[3.,6.]])
    score,eig,load=pca(m)
    assert eig[0]==pytest.approx(2.) and eig[1]==pytest.approx(0.,abs=1e-12)
    assert domination_counts(np.array([[1.,2.,3.],[2.,3.,4.],[0.,4.,2.],[1.,2.,3.]])).tolist()==[0,2,0,0]
    z=np.arange(9,dtype=float).reshape(3,3)
    mean,sd,span,rms,count=local_moments(z)
    assert mean[1,1]==4 and sd[1,1]==pytest.approx(np.sqrt(5))
    assert span[1,1]==6 and count[1,1]==4 and rms[1,1]==pytest.approx(np.sqrt(5))
    labels,sizes,codes=patch_labels(np.array([[1.,1.,2.],[2.,1.,2.],[2.,2.,np.nan]]))
    assert sorted(sizes.tolist())==[2,3,3]
    assert np.isnan(safe_ratio(np.array([1.]),np.array([0.]))[0])


def test_domain_actual_values(raster_fixture):
    ndvi=domain_input('spectral_ndvi',raster_fixture)
    _,meta,_=render(ndvi)
    yy,xx=np.indices((12,14))
    nir=(.42+.008*xx+.004*yy).astype(np.float32).astype(float)
    red=(.16+.004*xx+.001*yy).astype(np.float32).astype(float)
    assert meta['mean']==pytest.approx(float(np.mean((nir-red)/(nir+red))))
    _,meta,table=render(StudioInput(recipe='model_roc',csv='truth,score\n0,.1\n1,.8\n0,.2\n1,.9',x='truth',y='score'))
    assert meta['auc']==pytest.approx(1)
    _,_,table=render(StudioInput(recipe='hydro_mass',csv='seconds,flow\n0,2\n10,4\n20,4',x='seconds',y='flow'))
    assert table[-1]==[20.,70.]
    _,_,table=render(StudioInput(recipe='basic_waterfall',csv='step,value\nA,10\nB,-3\nC,1',x='step',y='value'))
    assert [r[-1] for r in table[1:]]==[10.,7.,8.]


def test_domain_recipe_counts_and_tiers():
    from terrain.studio_domain_catalog import BASIC,PROFESSIONAL
    assert len(BASIC)==12 and len(PROFESSIONAL)==116
    entries=catalog()
    assert sum(r['tier']=='professional' for r in entries)==168
    assert sum(r['tier']=='basic' for r in entries)==12
