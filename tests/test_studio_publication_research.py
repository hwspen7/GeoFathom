"""Independent analytical and publication-format checks for new research recipes."""
import base64,hashlib,io,json,zipfile
import numpy as np
import pytest
from PIL import Image
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from terrain.studio_routes import StudioInput,CompositionInput,ArchiveInput,render_composition,render_archive,reopen_studio
from terrain.studio_render import render
from terrain.studio_research import IDS,agreement,matrix_lags
from terrain.studio_data import FigureInputError

def raster(z,name,unit='index'):
    z=np.asarray(z,dtype=float)
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',height=z.shape[0],width=z.shape[1],count=1,dtype='float64',crs='EPSG:32617',transform=from_origin(500000,4500000,10,10),nodata=np.nan) as ds:
            ds.write(z,1);ds.update_tags(TERRAIN_UNIT=unit)
        return {'name':name,'unit':unit,'data':base64.b64encode(mem.read()).decode()}

def req(kind):
    z=np.arange(20.,dtype=float).reshape(4,5);z[0,0]=np.nan
    a=raster(z,'Reference');b=raster(2*z+1,'Candidate')
    cfg={'research_agreement':dict(csv='x,y\n1,2\n2,3\n3,5\n4,5\n',x='x',y='y'),
         'research_ecdf':dict(csv='group,y\na,1\na,2\na,2\nb,4\nb,5\n',group='group',y='y'),
         'research_qq':dict(csv='x,y\n1,2\n2,4\n3,6\n4,8\n',x='x',y='y'),
         'research_forest':dict(csv='name,y,lo,hi\na,1,0,2\nb,2,1,3\n',x='name',y='y',low='lo',high='hi'),
         'research_taylor':dict(csv='x,a,b\n1,2,4\n2,4,3\n3,6,2\n4,8,1\n',x='x',columns=['a','b']),
         'research_time_fan':dict(csv='t,y,l,u,il,iu\n1,2,0,4,1,3\n2,3,1,5,2,4\n3,4,2,6,3,5\n',x='t',y='y',columns=['l','u','il','iu']),
         'research_spacetime_lag':dict(csv='space,time,value,pairs\n0,1,2,10\n2,1,4,8\n5,1,6,6\n0,3,3,9\n5,3,7,3\n',x='space',y='time',z='value',columns=['pairs']),
         'research_map_distribution':dict(rasters=[a]),'research_map_agreement':dict(rasters=[a,b]),
         'research_map_bivariate':dict(rasters=[a,b]),'research_map_change':dict(rasters=[a,b])}
    return StudioInput(recipe=kind,width_mm=250,height_mm=140,**cfg[kind])

@pytest.mark.parametrize('kind',sorted(IDS))
def test_publication_recipe_reference(kind):
    input=req(kind)
    png,meta,table=render(input)
    assert png.startswith(b'\x89PNG') and table and meta['recipe']==kind
    with Image.open(io.BytesIO(png)) as im:
        assert abs(im.width-250/25.4*120)<2 and abs(im.height-140/25.4*120)<2
        assert np.asarray(im.convert('RGB')).std()>1
    svg,_,_=render(input.model_copy(update={'format':'svg'}))
    assert b'<svg' in svg and b'<text' in svg and b'<path' in svg
    pdf,_,_=render(input.model_copy(update={'format':'pdf'}))
    assert pdf.startswith(b'%PDF')
    json.dumps(meta,allow_nan=False)
    if kind=='research_taylor':
        assert table[1][1]==pytest.approx(1) and table[2][1]==pytest.approx(-1)
        assert table[1][2]==pytest.approx(2*np.std([1,2,3,4],ddof=1))
    if kind=='research_map_bivariate':assert sum(row[2] for row in table[1:])==19
    if kind in ('research_map_agreement','research_map_change'):assert meta['bias']==pytest.approx(11)
    if kind=='research_spacetime_lag':assert meta['missing_bins']==1

def test_independent_agreement_and_lag_masks():
    m,d,s=agreement(np.array([1.,2.,3.]),np.array([2.,4.,6.]))
    np.testing.assert_allclose(m,[1.5,3,4.5]);np.testing.assert_allclose(d,[1,2,3])
    assert s['bias']==2 and s['difference_sd']==1 and s['rmse']==pytest.approx(np.sqrt(14/3))
    x,y,a,b=matrix_lags(np.array([0,1,1]),np.array([1,1,2]),np.array([2,3,4]),np.array([4,5,6]))
    np.testing.assert_allclose(a,[[2,3],[np.nan,4]],equal_nan=True)
    with pytest.raises(FigureInputError,match='Duplicate'):matrix_lags(np.array([0,0]),np.array([1,1]),np.array([2,3]),np.array([4,5]))

def test_spanning_vector_composition_and_rejection():
    panel=StudioInput(recipe='basic_line',csv='x,y\n0,1\n1,3\n2,2\n',x='x',y='y')
    slots=[{'row':0,'column':0,'column_span':2},{'row':1,'column':0},{'row':1,'column':1}]
    body=CompositionInput(panels=[panel]*3,slots=slots,row_weights=[1.5,1],column_weights=[1,1],width_mm=240,height_mm=180,format='svg',caption='Observed values only.')
    data,meta=render_composition(body);assert b'<text' in data and b'<image' not in data
    assert meta['panel_count']==3 and meta['slots'][0]['column_span']==2
    with pytest.raises(ValueError,match='overlap'):CompositionInput(panels=[panel]*2,slots=[slots[0],slots[0]])
    with pytest.raises(ValueError,match='weights'):CompositionInput(panels=[panel]*3,slots=slots,row_weights=[1])
    many=CompositionInput(panels=[panel]*12,columns=3,width_mm=270,height_mm=240)
    data,meta=render_composition(many);assert data.startswith(b'\x89PNG') and meta['panel_count']==12

def test_archive_reopen_and_integrity():
    body=ArchiveInput(input=req('research_taylor').model_copy(update={'format':'pdf'}),provenance={'experiment':'reference'})
    out=render_archive(body)
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(out['archive']))) as z:
        manifest=json.loads(z.read('manifest.json'));assert manifest==out['manifest']
        for name,record in manifest['files'].items():
            data=z.read(name);assert record['sha256']==hashlib.sha256(data).hexdigest() and record['bytes']==len(data)
        restored=json.loads(z.read('reproduction.json'))
        verified=reopen_studio(ArchiveInput(input=restored['input'],provenance=restored['provenance']))
        assert verified==body.model_dump()
        assert z.read('figure.pdf').startswith(b'%PDF')

def test_fixed_display_range_records_out_of_range_without_changing_source():
    z=np.array([[-2,0,1],[2,4,6]],float)
    body=StudioInput(recipe='raster_continuous',rasters=[raster(z,'Native')],map_min=0,map_max=4,sequential_cmap='cividis')
    _,meta,_=render(body)
    assert meta['display_below']==1 and meta['display_above']==1 and meta['display_min']==0 and meta['display_max']==4
    assert meta['raster_sources'][0]['sha256']==hashlib.sha256(base64.b64decode(body.rasters[0].data)).hexdigest()


def test_research_lag_uses_observed_ticks_and_nonnegative_extent():
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from terrain.studio_data import Table
    from terrain.studio_research import render_table
    q=req('research_spacetime_lag');table=Table(q.csv)
    fig=Figure(figsize=(10,5));FigureCanvasAgg(fig);ax=fig.add_subplot(111)
    def rows(names,labels=()):
        a,b,_=table.aligned(names,labels);return a,b
    render_table(q.recipe,q,fig,ax,table,{},['#0072B2'],rows)
    np.testing.assert_array_equal(fig.axes[0].get_xticks(),[0,2,5])
    assert fig.axes[0].get_xlim()[0]==0


@pytest.mark.parametrize('kind',['research_vector_map','research_vector_overlay'])
def test_native_vector_publication_reference(kind):
    from pyproj import Transformer
    from terrain.studio_vector import vector_inputs
    # Construct known native coordinates by inverse projection; rendering
    # must recover these coordinates rather than approximate a bounding box.
    xy=Transformer.from_crs(32617,4326,always_xy=True)
    def coord(x,y):return list(xy.transform(x,y))
    ring=[coord(x,y) for x,y in [(500002,4499962),(500030,4499962),(500030,4499995),(500002,4499995),(500002,4499962)]]
    hole=[coord(x,y) for x,y in [(500005,4499970),(500009,4499970),(500009,4499974),(500005,4499974),(500005,4499970)]]
    def feat(typ,c,val):return {'type':'Feature','geometry':{'type':typ,'coordinates':c},'properties':{'risk':val}}
    features={'type':'FeatureCollection','features':[feat('Polygon',[ring,hole],2),feat('LineString',[coord(499990,4499980),coord(500060,4499980)],3),feat('Point',coord(500020,4499985),None)]}
    rows,meta=vector_inputs(features,32617,'risk')
    assert len(rows[0][1].interiors)==1
    assert rows[0][1].area==pytest.approx(28*33-16,abs=1e-5)
    assert rows[1][1].length==pytest.approx(70,abs=1e-5)
    body=StudioInput(recipe=kind,vector_geojson=features,vector_attribute='risk',vector_epsg=32617,rasters=[raster(np.arange(20.).reshape(4,5),'Risk')] if kind.endswith('overlay') else [])
    for fmt in ('png','svg','pdf'):
        data,m,t=render(body.model_copy(update={'format':fmt}));assert data and m['used_count']==3 and m['missing_attribute_count']==1
        assert m['display_crs']=='EPSG:32617'
        assert t[1:]==[[1,'Polygon',2.],[2,'LineString',3.],[3,'Point',None]]
        if fmt=='svg':
            assert b'<path' in data and b'<text' in data
            if kind.endswith('overlay'):assert b'<image' in data
            else:assert b'<image' not in data
    bad={'type':'FeatureCollection','features':[feat('Point',[999,50],2)]}
    with pytest.raises(FigureInputError,match='longitude'):vector_inputs(bad,32617,'risk')
