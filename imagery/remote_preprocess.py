"""Explicit inline calibration, native quality screening and common-grid preparation."""
import base64
import hashlib
import json
from types import SimpleNamespace

import numpy as np
from rasterio.io import MemoryFile
from rasterio.warp import reproject, Resampling

from analysis.science_raster import require
from analysis.science_routes import raster_product
from .remote_kernels import quality_mask


def prepare(body):
    from .remote_routes import read_band, Binding
    require(set(body.bindings) == set(body.quantities), "Declare every band quantity exactly once.")
    require(all(set(q.roles) <= set(body.bindings) for q in body.quality), "Unknown quality target role.")
    require(sum(len(s.data) for s in body.sources) <= 48_000_000, "Combined source payload exceeds budget.")
    raw = [base64.b64decode(s.data, validate=True) for s in body.sources]
    require(all(len(s) <= 24_000_000 for s in raw), "Source exceeds inline GeoTIFF budget.")
    hashes = [hashlib.sha256(s).hexdigest() for s in raw]
    decoded = 0

    def read(binding, quantity, validity=None):
        nonlocal decoded
        i = binding.source
        require(i < len(raw), "Source index does not exist.")
        grid = read_band(body.sources[i], binding, quantity, raw[i], hashes[i],validity)
        decoded += grid.values.size
        require(decoded <= 12_000_000, "Preparation exceeds decoded cell budget.")
        return grid

    def geometry(binding):
        i=binding.source;require(i<len(raw),'Source index does not exist.')
        with MemoryFile(raw[i]) as mem,mem.open() as ds:
            require(ds.driver=='GTiff' and ds.crs and 1<=binding.band<=ds.count,'Use georeferenced GeoTIFF sources and valid bands.')
            a=ds.transform;require(a.b==a.d==0 and a.a>0 and a.e<0,'Explicitly align north-up raster grids first.')
            require(ds.width*ds.height<=2_000_000,'Raster exceeds two million cell limit.')
            return SimpleNamespace(shape=(ds.height,ds.width),transform=a,crs=ds.crs,sha256=hashes[i])
    # Reference geometry is independent of its unmasked science values.
    target = geometry(body.target)
    masks = [(q, read(Binding(source=q.source, band=q.band, encoding='raw'), 'class'))
             for q in body.quality]
    products = []
    common = np.ones(target.shape, bool)
    total = 0
    evidence = {}
    for role, binding in body.bindings.items():
        native_grid=geometry(binding)
        native_clear=np.ones(native_grid.shape,bool)
        applied = []
        for spec, qa in masks:
            if spec.roles and role not in spec.roles:
                continue
            # Decode QA first, align only its discrete validity, and mask the
            # native science pixels before continuous resampling can mix them.
            clear = (quality_mask(qa.values, spec.scheme) == 1).astype('uint8')
            native = np.zeros(native_grid.shape, dtype='uint8')
            reproject(clear, native, src_transform=qa.transform, src_crs=qa.crs,
                      dst_transform=native_grid.transform, dst_crs=native_grid.crs,
                      resampling=Resampling.nearest, dst_nodata=0)
            native_clear&=native==1
            applied.append({'sha256': qa.sha256, 'band': qa.band, 'scheme': spec.scheme})
        grid=read(binding,body.quantities[role],native_clear)
        interpolation = 'nearest' if body.quantities[role] == 'class' else body.resampling
        out = np.full(target.shape, np.nan)
        reproject(grid.values, out, src_transform=grid.transform, src_crs=grid.crs,
                  src_nodata=np.nan, dst_transform=target.transform, dst_crs=target.crs,
                  dst_nodata=np.nan, resampling=getattr(Resampling, interpolation))
        require(np.isfinite(out).any(), 'No valid prepared cells for role: ' + role)
        common &= np.isfinite(out)
        product = raster_product('prepared_' + role, out, target.transform, target.crs, grid.unit)
        total += len(product['data'])
        require(total <= 48_000_000, "Prepared output exceeds inline budget; use disk preparation.")
        products.append({'role': role, **product})
        evidence[role] = {'source_sha256': grid.sha256, 'band': grid.band,
                          'quantity': body.quantities[role], 'unit': grid.unit,
                          'scale': grid.scale, 'offset': grid.offset,
                          'source_crs': str(grid.crs), 'source_transform': list(grid.transform)[:6],
                          'resampling': interpolation, 'quality': applied,
                          'valid_cells': int(np.isfinite(out).sum()), 'output_sha256': product['sha256']}
    require(common.any(), 'Prepared bands have no common valid support.')
    mask = raster_product('prepared_common_clear', common.astype(float), target.transform, target.crs, 'class')
    receipt = {'schema': 'geofathom-prepared-bands-1', 'bands': evidence,
               'crs': str(target.crs), 'transform': list(target.transform)[:6],
               'shape': list(common.shape), 'common_valid_cells': int(common.sum()),
               'source_sha256': hashes, 'target_sha256': target.sha256,
               'mask_sha256': mask['sha256'], 'quality_order': 'native_screen_then_reproject',
               'assumptions': 'Explicit calibrated quantities and supplied QA; no atmospheric retrieval or cross-sensor harmonization inferred.'}
    receipt['sha256'] = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return {'bands': products, 'common_mask': mask, 'receipt': receipt}
