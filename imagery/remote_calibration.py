"""Strict per-asset radiometric interpretation of analysis-ready STAC products."""
import math
import numpy as np
from imagery.raster import RasterError

def stac_reflectance_calibration(asset,dataset,properties,provider):
    # STAC raster extension v1 and v2 band-level calibration conventions.
    bands=asset.get('raster:bands',asset.get('bands',[]))
    if not isinstance(bands,list) or (bands and (len(bands)!=1 or not isinstance(bands[0],dict))):
        raise RasterError('Expected explicit single-band STAC reflectance metadata.')
    b=bands[0] if bands else {}
    def numeric(x):
        if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x):
            raise RasterError('Invalid STAC radiometric metadata.')
        return float(x)
    native=(numeric(dataset.scales[0]),numeric(dataset.offsets[0]))
    scale=b.get('scale',b.get('raster:scale'));offset=b.get('offset',b.get('raster:offset'))
    if scale is None and offset is None:
        if native==(1.,0.):
            raise RasterError('No explicit reflectance scale/offset in STAC or GeoTIFF; refusing uncalibrated NDVI.')
        result=native;source='geotiff'
    else:
        if scale is None:
            raise RasterError('STAC reflectance offset requires explicit scale.')
        result=(numeric(scale),numeric(0 if offset is None else offset));source='stac'
        if native!=(1.,0.) and not all(math.isclose(a,b,rel_tol=1e-6,abs_tol=1e-8) for a,b in zip(native,result)):
            raise RasterError('STAC and GeoTIFF calibration disagree.')
    if result[0]<=0:raise RasterError('Reflectance scale must be positive.')
    # Provider flags may establish that a radiometric offset was already
    # applied during COG generation. Reject inconsistent records, never guess.
    if provider=='earth-search' and properties.get('earthsearch:boa_offset_applied') is True and abs(result[1])>1e-10:
        raise RasterError('Earth Search reports an applied BOA offset but nonzero metadata offset; verify product calibration.')
    return {'scale':result[0],'offset':result[1],'source':source}

def apply_reflectance(values,calibration):
    out=np.asarray(values,dtype=np.float64)*calibration['scale']+calibration['offset']
    valid=np.isfinite(out)
    if np.isinf(out).any() or np.any((out[valid]<-.2-1e-9)|(out[valid]>1.6+1e-9)):
        raise RasterError('Calibrated reflectance outside supported range; verify source metadata.')
    return out
