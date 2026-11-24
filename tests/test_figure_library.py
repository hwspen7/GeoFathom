"""Plot tables are numerical products, not reconstructions of map colors."""
import base64
import io
import math
from threading import Event
from uuid import uuid4

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from pypdf import PdfReader
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.warp import transform_geom
from shapely.geometry import mapping,box
from terrain.cancellation import TerrainCancelled
from terrain.figure_data import continuous_data,figure_data_from_result,joint_elevation_data
from terrain.figure_routes import FigurePDFInput,make_vector_pdf
from terrain.professional import raster_product


def test_histogram_counts_density_quantiles_and_moments_match_independent_arithmetic():
    values=np.array([0,1,1,2,3,5,np.nan,np.inf],dtype=np.float32)
    data=continuous_data(values,'Slope','deg',25,domain=(0,90))
    expected=np.array([0,1,1,2,3,5],dtype=np.float64)
    assert data['valid_cells']==6
    assert data['summary']['mean']==pytest.approx(sum(expected)/6)
    assert data['summary']['population_std']==pytest.approx(math.sqrt(sum((expected-expected.mean())**2)/6))
    for q in data['quantiles']:
        assert q['value']==pytest.approx(np.quantile(expected,q['probability'],method='linear'),abs=1e-12)
    for bins in data['histograms'].values():
        assert sum(b['cells'] for b in bins)==6
        assert sum(b['area_m2'] for b in bins)==150
        assert sum(b['percent'] for b in bins)==pytest.approx(100)
        assert sum(b['density']*(b['upper']-b['lower']) for b in bins)==pytest.approx(1)
    for knot in data['cdf']:
        count=sum(x<=knot['value'] for x in expected)
        assert knot['cells_le']==count
        assert knot['percent_le']==pytest.approx(100*count/6)


def test_bin_edge_policy_box_whiskers_and_constant_populations():
    values=np.array([0.,9.,18.,90.])
    data=continuous_data(values,'Slope','deg',domain=(0,90))
    bins=data['histograms']['10']
    assert bins[0]['cells']==1 and bins[1]['cells']==1 and bins[2]['cells']==1 and bins[-1]['cells']==1
    constant=continuous_data(np.ones(8)*100,'Elevation','m')
    assert constant['summary']['population_std']==0
    assert constant['box']['whisker_low']==constant['box']['whisker_high']==100
    assert all(math.isfinite(b['density']) for b in constant['histograms']['40'])
    assert continuous_data(np.array([np.nan,np.inf]),'None','') is None
    outlier=continuous_data(np.array([0.,1.,2.,3.,100.]),'Elevation','m')
    assert outlier['box']['whisker_high']==3
    assert outlier['box']['upper_outliers']==1


def test_joint_density_uses_all_cells_and_scatter_sampling_is_explicit():
    x=np.arange(10000,dtype=np.float64).reshape(100,100)
    y=2*x+5;y[4,5]=np.nan
    data=joint_elevation_data(x,y,'Slope','deg',9)
    assert data['population_cells']==9999
    assert data['sample_cells']<=2000
    assert sum(b['cells'] for b in data['density_cells'])==9999
    assert sum(b['area_m2'] for b in data['density_cells'])==9999*9
    assert data['pearson_r']==pytest.approx(1)
    assert all(p['y']==2*p['x']+5 for p in data['samples'])
    assert joint_elevation_data(x,np.full_like(x,np.nan),'None','',1) is None
    constant=joint_elevation_data(np.ones((3,3)),np.ones((3,3)),'Constant','m',1)
    assert constant['pearson_r'] is None
    assert sum(b['cells'] for b in constant['density_cells'])==9


def test_directional_rose_excludes_flat_cells_and_wraps_north():
    values=np.array([[359.,1.,90.],[-1.,180.,np.nan]])
    affine=from_origin(500000,4500000,10,10)
    raster=raster_product(values,'aspect_map',affine,'EPSG:32617')
    result=figure_data_from_result({'operation':'aspect_map','raster':raster,'cell_area_m2':100,'valid_cells':5})
    assert result['kind']=='directional'
    assert result['valid_cells']==5 and result['directional_cells']==4 and result['flat_cells']==1
    assert result['roses']['8'][0]['cells']==2
    assert sum(row['percent'] for row in result['roses']['16'])==pytest.approx(100)
    assert 'histograms' not in result and 'normal_qq' not in result


@pytest.fixture
def source(tmp_path,monkeypatch):
    monkeypatch.setenv('GEOFATHOM_IMAGERY_DIR',str(tmp_path))
    uid=str(uuid4());path=tmp_path/(uid+'.tif')
    yy,xx=np.indices((20,20));values=100+xx*.7+yy*.3
    with rasterio.open(path,'w',driver='GTiff',width=20,height=20,count=1,dtype='float64',
        crs='EPSG:32617',transform=from_origin(500000,4500000,10,10),nodata=float('nan')) as ds:ds.write(values,1)
    geometry=transform_geom('EPSG:32617','EPSG:4326',mapping(box(500000,4499800,500200,4500000)))
    return path,{'image_id':uid,'geometry':geometry,'operation':'slope_map'}


def test_real_slope_result_carries_exact_plot_tables_and_regenerates_old_receipts(source):
    from terrain.advanced import run_terrain
    from core.main import app
    from imagery.store import file_sha256
    path,base=source
    result=run_terrain(path,base['geometry'],'slope_map')
    data=result['plot_data']
    with MemoryFile(base64.b64decode(result['raster']['geotiff'])) as memory,memory.open() as ds:values=ds.read(1)
    finite=values[np.isfinite(values)]
    assert data['valid_cells']==finite.size
    assert data['summary']['median']==pytest.approx(np.median(finite))
    assert data['thresholds'][-1]['percent_le']==100
    assert data['joint']['population_cells']==finite.size
    checksum=file_sha256(path)
    with TestClient(app) as client:
        response=client.post('/terrain/figures/data',json={'base':base,'expected_source_sha256':checksum})
        assert response.status_code==200,response.text
        assert response.json()['source_sha256']==checksum
        assert response.json()['histograms']==data['histograms']
        invalid=client.post('/terrain/figures/data',json={'base':base,'expected_source_sha256':'0'*64})
        assert invalid.status_code==422
    assert file_sha256(path)==checksum


def test_summary_and_legacy_binned_data_do_not_invent_exact_quantiles():
    binned=figure_data_from_result({'operation':'distribution','valid_cells':2,'metrics':{},'distribution':[
        {'lower_m':100,'upper_m':100,'cells':2,'area_m2':50,'cumulative_pct':100}]})
    assert binned['kind']=='binned' and binned['histograms']['20'][0]['density'] is None
    assert 'box' not in binned and 'normal_qq' not in binned
    summary=figure_data_from_result({'operation':'volume','metrics':{'cut_m3':42},'valid_cells':2})
    assert summary['kind']=='summary' and summary['metrics']['cut_m3']==42


def test_categorical_products_do_not_treat_codes_as_continuous_data():
    raster=raster_product(np.array([[0,1],[1,0]],float),'suitability',from_origin(500000,4500000,10,10),'EPSG:32617')
    result=figure_data_from_result({'operation':'suitability','valid_cells':4,'raster':raster,'cell_area_m2':100})
    assert result['kind']=='categorical' and sum(c['area_m2'] for c in result['classes'])==400
    assert 'normal_qq' not in result


def test_cancelled_table_generation_stops_before_sorting():
    cancel=Event();cancel.set()
    with pytest.raises(TerrainCancelled):continuous_data(np.arange(10),'Slope','deg',cancel=cancel)


def test_pdf_exports_vector_paths_and_text_at_requested_physical_size():
    from core.main import app
    scene={'width':900,'height':600,'width_mm':160,'height_mm':110,'title':'Slope distribution',
        'primitives':[
            {'kind':'rect','x':0,'y':0,'width':900,'height':600,'fill':'#ffffff','line_width':0},
            {'kind':'line','x':100,'y':500,'x2':800,'y2':500},
            {'kind':'polygon','points':[[100,500],[200,300],[200,500]],'fill':'#cccccc'},
            {'kind':'polyline','points':[[100,500],[200,300],[300,400]],'stroke':'#222222','dashed':True},
            {'kind':'circle','x':200,'y':300,'radius':3,'fill':'#000000'},
            {'kind':'text','x':450,'y':40,'text':'Slope angle (deg)','font':'serif','anchor':'middle'},
            {'kind':'text','x':20,'y':300,'text':'Area share (%)','angle':-90,'anchor':'end'},
        ]}
    raw=make_vector_pdf(FigurePDFInput(**scene))
    reader=PdfReader(io.BytesIO(raw));page=reader.pages[0]
    assert float(page.mediabox.width)==pytest.approx(160*72/25.4,abs=1e-4)
    assert float(page.mediabox.height)==pytest.approx(110*72/25.4,abs=1e-4)
    assert 'Slope angle (deg)' in page.extract_text()
    assert '/XObject' not in page['/Resources'] # No embedded bitmap pretending to be vector output.
    with TestClient(app) as client:
        response=client.post('/terrain/figures/pdf',json=scene)
        assert response.status_code==200 and response.headers['content-type']=='application/pdf'
        invalid={**scene,'primitives':[{'kind':'line','points':[[float('inf'),0]]}]}
        assert client.post('/terrain/figures/pdf',content=__import__('json').dumps(invalid),headers={'Content-Type':'application/json'}).status_code==422


def test_vector_pdf_rejects_unbounded_point_budgets():
    with pytest.raises(ValueError):FigurePDFInput(primitives=[{'kind':'polyline','points':[(1,1)]*5000}]*5)
