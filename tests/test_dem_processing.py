"""Real raster regression tests for local DEM preparation."""
import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from imagery.raster import RasterError
from terrain import dem_processing


@pytest.fixture
def source_dems(tmp_path,monkeypatch):
    t=from_origin(500000,4500000,10,10)
    a=np.full((5,5),100.,dtype=np.float32)
    b=np.full((5,5),200.,dtype=np.float32)
    a[2,2]=-9999.
    paths=[]
    for name,values in [('a',a),('b',b)]:
        path=tmp_path/(name+'.tif')
        with rasterio.open(path,'w',driver='GTiff',count=1,width=5,height=5,
                           crs='EPSG:32617',transform=t,dtype='float32',nodata=-9999) as ds:
            ds.write(values,1)
            ds.update_tags(VERTICAL_UNIT='meter')
        paths.append(path)
    saved=[]
    def capture(path,name,provenance):
        with rasterio.open(path) as ds:
            saved.append((ds.read(1),ds.transform,ds.nodata))
            return {'name':name,'width':ds.width,'height':ds.height,'crs':str(ds.crs)}
    monkeypatch.setattr(dem_processing,'imagery_dir',lambda:tmp_path)
    monkeypatch.setattr(dem_processing,'store_upload',capture)
    return paths,saved


def test_mosaic_keeps_first_source_and_fills_nodata(source_dems):
    paths,saved=source_dems
    result=dem_processing.prepare_dem(paths,'mosaic',resolution_m=10)
    assert result['valid_cells']==25
    values,_,nodata=saved[-1]
    assert values[0,0]==100 and values[2,2]==200
    assert np.isnan(nodata)


def test_resample_does_not_invent_source_accuracy(source_dems):
    paths,saved=source_dems
    result=dem_processing.prepare_dem([paths[0]],'resample',resolution_m=5)
    assert result['asset']['width']==10
    assert result['asset']['height']==10
    assert 'not a certificate' in result['warning']
    assert np.isnan(saved[-1][0]).any()


def test_clip_wgs84_polygon_and_validates_requests(source_dems):
    paths,saved=source_dems
    t=Transformer.from_crs('EPSG:32617','EPSG:4326',always_xy=True)
    ring=[t.transform(x,y) for x,y in [(500010,4499990),(500030,4499990),
         (500030,4499970),(500010,4499970),(500010,4499990)]]
    polygon={'type':'Polygon','coordinates':[ring]}
    result=dem_processing.prepare_dem([paths[1]],'clip',geometry=polygon,resolution_m=10)
    assert 1 <= result['valid_cells'] < 25
    assert result['asset']['width']<=3
    with pytest.raises(RasterError,match='requires an explicit polygon'):
        dem_processing.prepare_dem([paths[0]],'clip',resolution_m=10)
    with pytest.raises(RasterError,match='2–4 DEMs'):
        dem_processing.prepare_dem([paths[0]],'mosaic',resolution_m=10)
    with pytest.raises(RasterError,match='resolution'):
        dem_processing.prepare_dem([paths[0]],'resample',resolution_m=0.5)



def test_dem_mosaic_refuses_conflicting_datum_metadata(source_dems):
    paths,_=source_dems
    with rasterio.open(paths[0],'r+') as ds:ds.update_tags(VERTICAL_DATUM='NAVD88')
    with rasterio.open(paths[1],'r+') as ds:ds.update_tags(VERTICAL_DATUM='EGM96')
    with pytest.raises(RasterError,match='vertical datum mismatch'):
        dem_processing.prepare_dem(paths,'mosaic',resolution_m=10)


def test_dem_resample_reports_declared_datum_quality(source_dems):
    paths,saved=source_dems
    with rasterio.open(paths[0],'r+') as ds:ds.update_tags(VERTICAL_DATUM='NAVD88')
    result=dem_processing.prepare_dem([paths[0]],'resample',resolution_m=10)
    assert result['valid_cells']==24
    assert 'labels match' in result['warning']



def test_resample_preserves_exact_source_grid_origin(tmp_path,monkeypatch):
    # The source starts at an intentionally non-rounded UTM easting/northing.
    # Same-grid processing must NOT introduce a 3–7 m interpolation shift.
    affine=from_origin(500003,4500007,10,10)
    values=np.arange(25,dtype=np.float32).reshape(5,5)+100
    source=tmp_path/'offset-grid.tif'
    with rasterio.open(source,'w',driver='GTiff',width=5,height=5,count=1,
                       crs='EPSG:32617',transform=affine,dtype='float32',
                       nodata=-9999) as ds:
        ds.write(values,1)
    captured={}
    def capture(path,name,provenance):
        with rasterio.open(path) as ds:
            captured['heights']=ds.read(1)
            captured['grid']=ds.transform
            return {'name':name}
    monkeypatch.setattr(dem_processing,'imagery_dir',lambda:tmp_path)
    monkeypatch.setattr(dem_processing,'store_upload',capture)
    result=dem_processing.prepare_dem([source],'resample',resolution_m=10)
    assert result['valid_cells']==25
    assert captured['grid']==affine
    np.testing.assert_array_equal(captured['heights'],values)


def test_mosaic_tiled_working_set_and_overlap_priority(tmp_path,monkeypatch):
    """Chunk seams cannot alter first-source priority or create false NoData."""
    affine=from_origin(500003,4500007,10,10)
    first=np.full((9,9),100,dtype=np.float32)
    second=np.full((9,9),200,dtype=np.float32)
    first[4,4]=-9999
    a=tmp_path/'first.tif'
    b=tmp_path/'second.tif'
    make=lambda path,data,grid: _write_dem_fixture(path,data,grid)
    make(a,first,affine)
    make(b,second,from_origin(500033,4500007,10,10))
    monkeypatch.setattr(dem_processing,'_BLOCK',3)
    monkeypatch.setattr(dem_processing,'imagery_dir',lambda:tmp_path)
    original_reproject=dem_processing.reproject
    tile_shapes=[]
    def watched_reproject(**kwargs):
        tile_shapes.append(kwargs['destination'].shape)
        return original_reproject(**kwargs)
    monkeypatch.setattr(dem_processing,'reproject',watched_reproject)
    observed={}
    def retain(path,name,provenance):
        with rasterio.open(path) as source:
            observed['values']=source.read(1)
            observed['transform']=source.transform
            observed['nodata']=source.nodata
        return {'width':observed['values'].shape[1],'height':observed['values'].shape[0]}
    monkeypatch.setattr(dem_processing,'store_upload',retain)
    outcome=dem_processing.prepare_dem([a,b],'mosaic',resolution_m=10)
    values=observed['values']
    assert values.shape==(9,12)
    assert observed['transform']==affine
    assert values[4,4]==200  # Filled by the second source
    assert values[0,4]==100  # Original source wins on overlap
    assert values[0,9]==200  # Outside the first source
    assert np.all(np.isfinite(values))
    assert outcome['valid_cells']==108
    assert len(tile_shapes)>4
    assert all(h<=3 and w<=3 for h,w in tile_shapes)
    assert np.isnan(observed['nodata'])


def _write_dem_fixture(path,values,affine):
    with rasterio.open(path,'w',driver='GTiff',width=values.shape[1],
                       height=values.shape[0],count=1,dtype='float32',
                       crs='EPSG:32617',transform=affine,nodata=-9999) as sink:
        sink.write(values,1)


def test_resample_cancel_cleans_partial_output(source_dems,tmp_path,monkeypatch):
    """Cancelled runs must leave no half-filled raster or library receipt."""
    from threading import Event
    from terrain.cancellation import TerrainCancelled
    sources,_=source_dems
    monkeypatch.setattr(dem_processing,'_BLOCK',2)
    marker=Event()
    original_reproject=dem_processing.reproject
    def interrupt(**kwargs):
        result=original_reproject(**kwargs)
        marker.set()
        return result
    monkeypatch.setattr(dem_processing,'reproject',interrupt)
    with pytest.raises(TerrainCancelled):
        dem_processing.prepare_dem([sources[0]],'resample',resolution_m=5,cancel=marker)
    assert not list(tmp_path.glob('.dem-work-*.tif'))


def test_dem_clip_with_multiple_tiles_and_no_data_outside_polygon(source_dems,tmp_path,monkeypatch):
    sources,_=source_dems
    monkeypatch.setattr(dem_processing,'_BLOCK',2)
    transform=Transformer.from_crs('EPSG:32617','EPSG:4326',always_xy=True)
    ring=[transform.transform(x,y) for x,y in [
        (500000,4500000),(500030,4500000),(500030,4499970),
        (500000,4499970),(500000,4500000)]]
    polygon={'type':'Polygon','coordinates':[ring]}
    snapshot={}
    def retain(path,name,provenance):
        with rasterio.open(path) as src:
            snapshot['array']=src.read(1)
            snapshot['nodata']=src.nodata
        return {'width':snapshot['array'].shape[1]}
    monkeypatch.setattr(dem_processing,'store_upload',retain)
    processed=dem_processing.prepare_dem([sources[1]],'clip',polygon,10)
    assert 1<=processed['valid_cells']<=9
    assert np.all(np.isfinite(snapshot['array'][0:2,0:2]))
    assert np.isnan(snapshot['nodata'])
