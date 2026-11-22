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
