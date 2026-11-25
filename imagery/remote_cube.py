"""Windowed optical acquisition cubes with native QA and explicit target geometry."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling

from analysis.science_raster import require
from .remote_band import read_calibrated
from .remote_kernels import quality_mask
from .remote_windowed import digest, windows
from .remote_harmonization import validate_corrections,correct_band,registration_diagnostics


def acquisition_times(acquisitions):
    times = []
    for item in acquisitions:
        value = datetime.fromisoformat(item['datetime'].replace('Z', '+00:00'))
        require(value.tzinfo is not None, 'Acquisition datetime requires an explicit timezone.')
        times.append(value.astimezone(timezone.utc))
    require(all(b > a for a, b in zip(times, times[1:])), 'Acquisitions must have unique increasing UTC times.')
    return times


def build_cube(config, output, progress=None, check=lambda: None):
    acquisitions = config['acquisitions']
    require(2 <= len(acquisitions) <= 64, 'Use 2–64 acquisitions.')
    dates = acquisition_times(acquisitions)
    roles = list(acquisitions[0]['bands'])
    require(1 <= len(roles) <= 12 and all(set(a['bands']) == set(roles) for a in acquisitions),
            'Declare the same 1–12 spectral roles in every acquisition.')
    require(len({a['id'] for a in acquisitions}) == len(acquisitions), 'Acquisition IDs must be unique.')
    sensors = {a['sensor'] for a in acquisitions}
    harmonization = config.get('harmonization', '')
    reference_sensor=validate_corrections(acquisitions,config.get('reference_sensor'))
    require(len(sensors) == 1 or len(harmonization.strip()) >= 20,
            'Cross-sensor cubes require a documented external harmonization procedure.')
    tile = config.get('tile', 256)
    require(type(tile) is int and 32 <= tile <= 1024, 'Cube tile size must be 32–1024.')
    resampling = config.get('resampling', 'bilinear')
    require(resampling in ('nearest', 'bilinear','area'), 'Use explicit nearest, bilinear or area resampling.')
    output = Path(output).resolve()
    require(output.parent.is_dir() and not output.exists(), 'Choose a new output in an existing directory.')
    paths = {str(Path(config['target_path']).resolve())}
    for a in acquisitions:
        paths.update(str(Path(b['path']).resolve()) for b in a['bands'].values())
        paths.update(str(Path(q['path']).resolve()) for q in a.get('quality', []))
    if config.get('registration'):paths.add(str(Path(config['registration']['mask_path']).resolve()))
    require(str(output) not in paths, 'Input and output paths must differ.')
    hashes = {p: digest(p) for p in paths}
    with TemporaryDirectory(prefix='.cube-'+output.stem+'-', dir=output.parent) as folder, ExitStack() as stack:
        target = stack.enter_context(rasterio.open(config['target_path']))
        require(target.driver == 'GTiff' and target.crs and target.transform.a > 0 and
                target.transform.e < 0 and target.transform.b == target.transform.d == 0,
                'The target must be a north-up georeferenced GeoTIFF.')
        cells = target.width * target.height
        require(cells <= 150_000_000, 'Cube target exceeds 150 million cells.')
        profiles = dict(driver='GTiff', dtype='float64', nodata=np.nan, compress='deflate',
                        tiled=True, blockxsize=256, blockysize=256, BIGTIFF='IF_SAFER')
        science = []
        native_cells = 0
        for a in acquisitions:
            require(all(set(q.get('roles', [])) <= set(roles) for q in a.get('quality', [])), 'Unknown cube QA target role.')
            for role in roles:
                spec = a['bands'][role]
                ds = stack.enter_context(rasterio.open(spec['path']))
                require(ds.driver == 'GTiff' and ds.crs and ds.transform.a > 0 and ds.transform.e < 0 and
                        ds.transform.b == ds.transform.d == 0, 'Use north-up science GeoTIFFs.')
                native_cells += ds.width * ds.height
                require(native_cells <= 2_000_000_000, 'Cube native processing budget exceeded.')
                science.append((a, role, spec, ds))
        estimate = 8 * (native_cells + cells * (len(science) + len(roles)))
        if resampling=='area':estimate+=8*cells*len(science)
        budget = config.get('disk_budget_mb', 8192)
        require(type(budget) is int and 64 <= budget <= 65536, 'Disk budget must be 64–65536 MiB.')
        require(estimate <= budget * 1024**2 and estimate + 64*1024**2 <= shutil.disk_usage(output.parent).free,
                'Insufficient declared or available scratch/output disk budget.')
        aligned = []
        layout = []
        for i, (acquisition, role, spec, ds) in enumerate(science):
            check()
            binding = SimpleNamespace(band=spec.get('band', 1), encoding=spec.get('encoding', 'metadata'),
                scale=spec.get('scale', 1), offset=spec.get('offset', 0), unit=spec.get('unit', ''))
            require(binding.encoding in ('metadata', 'raw', 'custom', 'landsat_sr'), 'Unsupported optical calibration.')
            masks = []
            for q in acquisition.get('quality', []):
                if q.get('roles') and role not in q['roles']:
                    continue
                qa = stack.enter_context(rasterio.open(q['path']))
                require(qa.driver == 'GTiff' and qa.crs and 1 <= q.get('band', 1) <= qa.count, 'Invalid cube QA source.')
                require(q['scheme'] in ('binary', 'sentinel_clear', 'landsat_clear', 'landsat_unsaturated'), 'Unknown QA scheme.')
                view = stack.enter_context(WarpedVRT(qa, crs=ds.crs, transform=ds.transform,
                    width=ds.width, height=ds.height, resampling=Resampling.nearest,
                    dtype='float64', nodata=np.nan))
                masks.append((q, view))
            prepared = Path(folder) / (str(i) + '.tif')
            scale = offset = None
            correction=acquisition.get('corrections',{}).get(role);correction_evidence=None
            correction_excluded=0
            with rasterio.open(prepared, 'w', **profiles, width=ds.width, height=ds.height,
                               count=1, crs=ds.crs, transform=ds.transform) as dst:
                for window in windows(ds.width, ds.height, tile):
                    check()
                    valid=None
                    for q, qa in masks:
                        z = qa.read(q.get('band', 1), window=window, masked=True).filled(np.nan)
                        clear=quality_mask(z,q['scheme'])==1
                        valid=clear if valid is None else valid&clear
                    values, _, scale, offset = read_calibrated(ds, binding, 'reflectance', window,validity=valid)
                    if correction:
                        values,correction_evidence=correct_band(values,correction)
                        correction_excluded+=correction_evidence.get('brdf_diagnostics',{}).get('outside_supported_cells',0)
                    dst.write(values, 1, window=window)
            if correction_evidence and 'brdf_diagnostics' in correction_evidence:
                correction_evidence['brdf_diagnostics']['outside_supported_cells']=correction_excluded
            if resampling=='area':
                from .remote_support_disk import transfer
                area_path=Path(folder)/(str(i)+'-area.tif')
                transfer(prepared,config['target_path'],area_path,unit='reflectance',minimum_coverage=config.get('minimum_coverage',.8),
                    tile=min(tile,512),use_target_mask=False,check=check)
                view=stack.enter_context(rasterio.open(area_path))
            else:
                view = stack.enter_context(WarpedVRT(stack.enter_context(rasterio.open(prepared)),
                    crs=target.crs, transform=target.transform, width=target.width, height=target.height,
                    resampling=getattr(Resampling, resampling), dtype='float64', nodata=np.nan))
            aligned.append(view)
            layout.append({'band': i+1, 'acquisition': acquisition['id'], 'datetime': acquisition['datetime'],
                'sensor': acquisition['sensor'], 'role': role, 'unit': 'reflectance',
                'source_sha256': hashes[str(Path(spec['path']).resolve())], 'source_band': binding.band,
                'scale': scale, 'offset': offset,'correction':correction_evidence, 'quality': [dict(q) for q in acquisition.get('quality', [])]})
            if progress: progress(.45 * (i+1) / len(science))
        registration=[]
        if config.get('registration'):
            spec=config['registration'];require(spec['role'] in roles,'Unknown registration role.')
            mask=stack.enter_context(rasterio.open(spec['mask_path']))
            require(mask.crs==target.crs and mask.transform==target.transform and mask.shape==target.shape,'Registration mask must match the target grid.')
            c,r,w,h=spec.get('window',[0,0,min(256,target.width),min(256,target.height)])
            require(all(type(v) is int for v in (c,r,w,h)) and c>=0 and r>=0 and 16<=w<=512 and 16<=h<=512 and c+w<=target.width and r+h<=target.height,'Invalid registration window.')
            window=rasterio.windows.Window(c,r,w,h);index=roles.index(spec['role']);ref=aligned[index].read(1,window=window,masked=True).filled(np.nan)
            controls=mask.read(1,window=window,masked=True).astype(float).filled(0)
            for j in range(1,len(acquisitions)):
                check();candidate=aligned[j*len(roles)+index].read(1,window=window,masked=True).filled(np.nan)
                registration.append({'acquisition':acquisitions[j]['id'],**registration_diagnostics(ref,candidate,controls,spec.get('max_shift_pixels',.5),spec.get('max_rmse',.03))})
        staged = Path(folder) / 'cube.tif'
        support = {r: 0 for r in roles}
        total_windows = ((target.width+tile-1)//tile) * ((target.height+tile-1)//tile)
        with rasterio.open(staged, 'w', **profiles, width=target.width, height=target.height,
                           count=len(layout)+len(roles), crs=target.crs, transform=target.transform) as dst:
            dst.update_tags(REMOTE_SCHEMA='geofathom-optical-cube-1', TIME_UNIT='UTC',
                TIME_ORIGIN=dates[0].isoformat(),AXIS_UNIT='day',
                QUALITY_ORDER='native_screen_then_reproject', HARMONIZATION=harmonization)
            for entry in layout:
                b = entry['band']
                dst.set_band_description(b, entry['acquisition'] + ':' + entry['role'])
                dst.update_tags(b, TERRAIN_UNIT='reflectance', ACQUISITION_DATETIME=entry['datetime'], ROLE=entry['role'])
            for k, role in enumerate(roles):
                dst.set_band_description(len(layout)+k+1, role+':valid_count')
                dst.update_tags(len(layout)+k+1, TERRAIN_UNIT='count', ROLE=role)
            for n, window in enumerate(windows(target.width, target.height, tile)):
                check()
                counts = {r: np.zeros((int(window.height), int(window.width)), dtype='uint16') for r in roles}
                for entry, src in zip(layout, aligned):
                    z = src.read(1, window=window, masked=True).filled(np.nan)
                    counts[entry['role']] += np.isfinite(z)
                    dst.write(z, entry['band'], window=window)
                for k, role in enumerate(roles):
                    dst.write(counts[role].astype(float), len(layout)+k+1, window=window)
                    support[role] += int(counts[role].sum())
                if progress: progress(.45 + .5 * (n+1) / total_windows)
        require(all(n > 0 for n in support.values()), 'A cube role has no valid observations.')
        check()
        require(all(digest(p) == h for p, h in hashes.items()), 'Cube input changed during processing.')
        receipt = {'schema': 'geofathom-optical-cube-1', 'band_layout': layout,
            'source_sha256': hashes, 'roles': roles, 'acquisition_count': len(acquisitions),
            'utc_datetimes': [t.isoformat() for t in dates], 'time_origin': dates[0].isoformat(),
            'time_unit': 'day', 'times': [(t-dates[0]).total_seconds()/86400 for t in dates],
            'shape': [target.height, target.width], 'crs': str(target.crs), 'transform': list(target.transform)[:6],
            'support_bands': {r: len(layout)+i+1 for i, r in enumerate(roles)},
            'valid_observations': support, 'resampling': resampling, 'harmonization_declaration': harmonization,
            'reference_sensor':reference_sensor,'registration':registration,'minimum_coverage':config.get('minimum_coverage',.8) if resampling=='area' else None,
            'sha256': digest(staged), 'assumptions': 'Supplied analysis-ready reflectance and QA; gaps retained; no cloud imputation or inferred sensor equivalence.'}
        os.link(staged, output)
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(build_cube(json.loads(args.config.read_text()), args.output), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
