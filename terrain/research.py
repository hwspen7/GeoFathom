"""Reproducible terrain experiments on one source grid and study population.

Scenario spread is descriptive. Monte Carlo intervals propagate an explicitly
assumed Gaussian DEM error model; they do not establish surveyed accuracy.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import math
import platform
import os
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile

from imagery.raster import RasterError
from imagery.store import describe, file_sha256
from .advanced import _window, run_terrain
from .cancellation import checkpoint
from .professional import raster_product
from .figure_data import continuous_data, figure_data_from_result, joint_elevation_data

# Numeric one- and two-factor sweeps only vary parameters used by the operation.
SWEEP_PARAMETERS = {
    'slope_map': [], 'aspect_map': [], 'elevation': [],
    'hillshade': ['azimuth', 'altitude'],
    'tri': ['neighborhood_radius'], 'tpi': ['neighborhood_radius'],
    'curvature': ['curvature_radius'], 'plan_curvature': ['curvature_radius'],
    'profile_curvature': ['curvature_radius'],
    'flow_accumulation': [], 'flow_accumulation_mfd': ['mfd_exponent'],
    'streams': ['stream_cells'], 'stream_order': ['stream_cells'],
    'cutfill_map': ['reference', 'design_east_grade', 'design_north_grade',
                    'design_curvature_east', 'design_curvature_cross', 'design_curvature_north'],
    'volume': ['reference', 'design_east_grade', 'design_north_grade',
               'design_curvature_east', 'design_curvature_cross', 'design_curvature_north'],
    'suitability': ['max_slope', 'min_elevation', 'max_elevation', 'max_tri'],
    'visibility': ['observer_height', 'target_height', 'refraction_coeff', 'max_distance_m'],
    'viewshed_multi': ['observer_height', 'target_height', 'refraction_coeff', 'max_distance_m'],
}
SCENARIO_PARAMETERS = {op: list(values) for op, values in SWEEP_PARAMETERS.items()}
for operation in {'slope_map','aspect_map','hillshade','suitability','plan_curvature','profile_curvature'}:
    SCENARIO_PARAMETERS[operation].append('gradient_method')
for operation in {'curvature','plan_curvature','profile_curvature'}:
    SCENARIO_PARAMETERS[operation].append('curvature_method')
for operation in {'flow_accumulation','flow_accumulation_mfd','streams','stream_order'}:
    SCENARIO_PARAMETERS[operation] += ['fill_sinks','depression_method']
SCENARIO_PARAMETERS['flow_accumulation'].append('flow_routing_method')
SCENARIO_PARAMETERS['stream_order'].append('stream_order_scheme')
SCENARIO_PARAMETERS['hillshade'].append('hillshade_mode')
SCENARIO_PARAMETERS['suitability'] += ['suitability_model','suitability_weights']
for operation in {'visibility','viewshed_multi'}:
    SCENARIO_PARAMETERS[operation] += ['consider_curvature','view_azimuth','view_width']
SCENARIO_PARAMETERS['viewshed_multi'] += ['observer_points','optimize_observers']

# Angular and categorical outputs need circular differences or transitions,
# rather than subtraction of nominal class codes.
UNCERTAINTY_OPERATIONS = {'elevation', 'slope_map', 'hillshade', 'tri', 'tpi',
    'curvature', 'plan_curvature', 'profile_curvature', 'cutfill_map', 'volume', 'suitability'}
MAX_ENSEMBLE_CELLS = 12_000_000
MAX_SCENARIO_CELLS = 2_000_000
INTEGER_PARAMETERS = {'neighborhood_radius', 'curvature_radius', 'stream_cells'}


def execute(body, path, resolve, cancel=None, include_plot_data=True):
    options = body.model_dump(exclude={'image_id', 'texture_image_id', 'comparison_image_id',
        'dsm_image_id', 'external_inflow_image_id'})
    for identifier, target, enabled in [
        (body.texture_image_id, 'texture_path', body.operation == 'mesh'),
        (body.comparison_image_id, 'comparison_path', body.operation == 'dem_difference'),
        (body.dsm_image_id, 'dsm_path', body.operation in {'visibility', 'viewshed_multi'}),
        (body.external_inflow_image_id, 'external_inflow_path', True),
    ]:
        if identifier and enabled:
            options[target] = resolve(identifier)
    return run_terrain(path, **options, cancel=cancel, include_plot_data=include_plot_data)


def unpack(product):
    with MemoryFile(base64.b64decode(product['geotiff'])) as memory, memory.open() as ds:
        return ds.read(1).astype(np.float64), ds.transform, ds.crs


def research_raster(values, affine, crs, unit, title, kind='continuous', metadata=None, cancel=None):
    # Reuse georeferencing/alpha preview machinery, then write the actual
    # quantity and unit into GeoTIFF tags. No change raster is mislabeled DEM.
    operation = 'dem_difference' if kind == 'difference' else 'elevation'
    product = raster_product(values, operation, affine, crs, cancel)
    with MemoryFile(base64.b64decode(product['geotiff'])) as source, source.open() as ds:
        profile = ds.profile
        if not profile.get('tiled'):
            profile.pop('blockxsize',None)
            profile.pop('blockysize',None)
        tags = ds.tags()
    tags.update(TERRAIN_OPERATION='research_' + kind, TERRAIN_UNIT=unit,
                RESEARCH_TITLE=title, RESEARCH_METADATA=json.dumps(metadata or {}, sort_keys=True))
    with MemoryFile() as memory:
        with memory.open(**profile) as dst:
            dst.write(values.astype(np.float32), 1)
            dst.update_tags(**tags)
        product['geotiff'] = base64.b64encode(memory.read()).decode('ascii')
    if kind == 'difference':
        for entry in product['legend']:
            entry['label'] = entry['label'].replace(' m', ' ' + unit)
    product.update(unit=unit, title=title)
    return product


def difference(reference, candidate, operation, cancel=None):
    a, affine, crs = unpack(reference)
    b, transform, projection = unpack(candidate)
    if a.shape != b.shape or affine != transform or crs != projection:
        raise RasterError('Scenario outputs must have identical grids; explicitly align sources first.')
    if reference['unit'] != candidate['unit']:
        raise RasterError('Scenario output units differ; numerical comparison is undefined.')
    common = np.isfinite(a) & np.isfinite(b)
    categorical = operation in {'streams', 'visibility', 'viewshed_multi', 'stream_order'} or (
        operation == 'suitability' and reference['unit'] != 'score_0_to_1')
    if operation == 'aspect_map':
        # -1 denotes flat cells, not a direction; exclude them explicitly.
        common &= (a >= 0) & (b >= 0)
    if not common.any():
        raise RasterError('No common valid output cells to compare.')
    values = np.full(a.shape, np.nan)
    if categorical:
        values[common] = (b[common] != a[common]).astype(float)
        kind, unit = 'transition', 'changed_0_or_1'
    elif operation == 'aspect_map':
        values[common] = (b[common] - a[common] + 180) % 360 - 180
        kind, unit = 'difference', 'degrees'
    else:
        values[common] = b[common] - a[common]
        kind, unit = 'difference', reference['unit']
    delta = values[common]
    stats = {'common_cells': int(common.sum()), 'reference_valid_cells': int(np.isfinite(a).sum()),
        'candidate_valid_cells': int(np.isfinite(b).sum()),
        'common_coverage_pct': 100 * int(common.sum()) / max(1, int(np.isfinite(a).sum())),
        'changed_cells': int(np.count_nonzero(delta)),
        'changed_pct': 100 * np.count_nonzero(delta) / delta.size,
        'mean_difference': float(delta.mean()), 'mae': float(np.abs(delta).mean()),
        'rms_difference': float(np.sqrt(np.mean(delta * delta))),
        'minimum_difference': float(delta.min()), 'maximum_difference': float(delta.max())}
    if categorical:
        pairs, counts = np.unique(np.column_stack((a[common], b[common])), axis=0, return_counts=True)
        stats['transitions'] = [{'reference': float(p[0]), 'candidate': float(p[1]), 'cells': int(n)}
                                for p, n in zip(pairs, counts)]
    # Use the actual exported physical values for the residual distribution.
    # Paired agreement is descriptive, not an independent accuracy validation.
    plot_data = None
    if not categorical:
        area = abs(affine.a * affine.e - affine.b * affine.d)
        plot_data = continuous_data(values.astype(np.float32), 'Candidate minus baseline', unit, area, cancel)
        if plot_data is not None:
            plot_data['classes'] = []
            if operation != 'aspect_map':
                joint = joint_elevation_data(a, b, 'Candidate', unit, area, cancel)
                joint.update(x_quantity='Baseline', x_unit=unit, identity_line=True)
                if delta.size >= 2:
                    bias = float(delta.mean())
                    sd = float(delta.std(ddof=1))
                    joint['agreement'] = {'bias':bias, 'sample_std':sd,
                        'lower':bias-1.96*sd, 'upper':bias+1.96*sd}
                plot_data['joint'] = joint
    return {'statistics': stats, 'kind': kind, 'plot_data': plot_data,
        'raster': research_raster(values, affine, crs, unit,
            'Candidate minus baseline' if not categorical else 'Category transitions', kind,
            {'sign': 'candidate_minus_baseline', 'operation': operation}, cancel)}


def shared_previews(products, operation, cancel=None):
    """Use one numerical grayscale range for matched continuous map swipes."""
    if operation not in {'elevation','tri','tpi','curvature','plan_curvature',
                         'profile_curvature','flow_accumulation','flow_accumulation_mfd'}:
        return
    selected = [p for p in products if p['role'] in {'baseline','scenario'}]
    if len(selected) < 2:
        return
    grids = [unpack(p['raster']) for p in selected]
    low = min(float(np.nanmin(g)) for g,_,_ in grids)
    high = max(float(np.nanmax(g)) for g,_,_ in grids)
    for item,(grid,affine,crs) in zip(selected,grids):
        checkpoint(cancel)
        display = (grid-low)*255/(high-low) if high > low else np.where(np.isfinite(grid),127.,np.nan)
        preview = raster_product(display,'hillshade',affine,crs,cancel)
        item['raster']['png'] = preview['png']
        edges = np.linspace(low,high,7) if high>low else np.array([low,high])
        finite = np.isfinite(grid)
        classes = np.digitize(grid[finite],edges[1:-1])
        palette = ['#222222','#555555','#888888','#aaaaaa','#dddddd','#ffffff']
        item['raster']['legend'] = [{'label':f'{a:.5g} to {b:.5g}',
            'cells':int(np.count_nonzero(classes==i)), 'color':palette[i]}
            for i,(a,b) in enumerate(zip(edges,edges[1:]))]
        item['raster']['preview_scale'] = {'minimum':low, 'maximum':high,
            'palette':'continuous_grayscale', 'shared_across_scenarios':True}


def _metrics(result):
    return {k: float(v) for k, v in result['metrics'].items()
            if isinstance(v, (int, float)) and math.isfinite(v)}


def _receipt(label, body, result):
    return {'label': label, 'input': body.model_dump(), 'metrics': _metrics(result),
        'quality': result.get('quality'), 'warning': result.get('warning', ''),
        'algorithm_options': result.get('algorithm_options')}


def _metric_table(runs, populations=None):
    keys = sorted(set.intersection(*(set(r['metrics']) for r in runs)))
    rows = []
    for key in keys:
        vals = [r['metrics'][key] for r in runs]
        base = vals[0]
        comparable = populations or [True]*len(vals)
        rows.append({'metric': key, 'values': vals,
            'deltas': [v-base if same else None for v,same in zip(vals,comparable)],
            'relative_pct': [100*(v-base)/abs(base) if base != 0 and same else None for v,same in zip(vals,comparable)]})
    return rows



def software_revision():
    """Record the engine checkout without requiring Git in packaged installs."""
    root = Path(__file__).resolve().parents[1]
    try:
        head = subprocess.run(['git','rev-parse','HEAD'],cwd=root,check=True,
            capture_output=True,text=True,timeout=2).stdout.strip()
        dirty = subprocess.run(['git','status','--porcelain'],cwd=root,check=True,
            capture_output=True,text=True,timeout=2).stdout.strip()
        return {'geofathom_commit':head, 'working_tree_modified':bool(dirty)}
    except (OSError,subprocess.SubprocessError):
        return {'geofathom_commit':os.getenv('GEOFATHOM_BUILD_REVISION','not_recorded'),
                'working_tree_modified':None}

def analyze_experiment(body, resolve, cancel=None):
    from .routes import AdvancedTerrainInput
    checkpoint(cancel)
    path = resolve(body.base.image_id)
    # Validate a bounded study window before any repeated calculation/allocation.
    z, valid, _, affine, crs, _, _ = _window(path, body.base.geometry, 4096, MAX_SCENARIO_CELLS)
    source_checksum = file_sha256(path)
    if body.expected_source_sha256 and source_checksum != body.expected_source_sha256:
        raise RasterError('Source checksum changed; this experiment cannot reproduce the saved input.')
    for identifier, checksum in body.expected_dependency_sha256.items():
        if file_sha256(resolve(identifier)) != checksum:
            raise RasterError('Dependency checksum changed; this experiment cannot reproduce the saved input.')
    dependencies = {identifier:file_sha256(resolve(identifier))
        for identifier in [body.base.dsm_image_id,body.base.external_inflow_image_id] if identifier}
    baseline = execute(body.base, path, resolve, cancel, include_plot_data=False)
    runs = [_receipt(body.baseline_name, body.base, baseline)]
    products = []
    baseline_raster = baseline.get('raster')
    if baseline_raster:
        products.append({'name': body.baseline_name, 'role': 'baseline', 'raster': baseline_raster,
                         'plot_data': figure_data_from_result(baseline, cancel)})
    result = {'title': body.title, 'mode': body.mode, 'runs': runs, 'products': products,
              'differences': [], 'sensitivity': [], 'factorial': None, 'uncertainty': None}
    variants = []
    populations = [True]
    if body.mode == 'sensitivity':
        def apply_value(values, parameter, value):
            if parameter in INTEGER_PARAMETERS and not float(value).is_integer():
                raise RasterError('This parameter requires integer sweep values.')
            values[parameter] = int(value) if parameter in INTEGER_PARAMETERS else value
        if body.secondary_parameter:
            result['factorial'] = {'x_parameter':body.parameter, 'y_parameter':body.secondary_parameter,
                                   'x_values':sorted(body.values), 'y_values':sorted(body.secondary_values), 'cells':[]}
        for value in body.values:
            for secondary in body.secondary_values if body.secondary_parameter else [None]:
                values = body.base.model_dump()
                apply_value(values, body.parameter, value)
                name = f'{body.parameter} = {value:g}'
                if secondary is not None:
                    apply_value(values, body.secondary_parameter, secondary)
                    name += f', {body.secondary_parameter} = {secondary:g}'
                variants.append((name, AdvancedTerrainInput.model_validate(values), value, secondary))
    elif body.mode == 'comparison':
        for scenario in body.scenarios:
            variant = AdvancedTerrainInput.model_validate({**body.base.model_dump(), **scenario.parameters})
            variants.append((scenario.name, variant, None, None))
    else:
        if body.samples * z.size > MAX_ENSEMBLE_CELLS:
            raise RasterError('Uncertainty ensemble exceeds 12,000,000 cell realizations; reduce area or sample count.')
        _uncertainty(body, path, resolve, z, valid, affine, crs, baseline, result, cancel)
    if (len(variants) + 1) * z.size > MAX_ENSEMBLE_CELLS:
        raise RasterError('Scenario experiment exceeds 12,000,000 cell evaluations; reduce the area or scenario count.')
    for name, variant, value, secondary in variants:
        checkpoint(cancel)
        output = execute(variant, path, resolve, cancel, include_plot_data=False)
        runs.append(_receipt(name, variant, output))
        if output.get('raster'):
            products.append({'name': name, 'role': 'scenario', 'raster': output['raster'],
                             'plot_data': figure_data_from_result(output, cancel)})
        matched_population = True
        if baseline_raster and output.get('raster'):
            delta = difference(baseline_raster, output['raster'], body.base.operation, cancel)
            result['differences'].append({'name': name, **delta})
            stats = delta['statistics']
            matched_population = stats['common_cells'] == stats['reference_valid_cells'] == stats['candidate_valid_cells']
        populations.append(matched_population)
        if secondary is not None:
            result['factorial']['cells'].append({'x':value,'y':secondary,
                'metrics':_metrics(output),'matched_population':matched_population})
        elif value is not None:
            base_value = getattr(body.base, body.parameter)
            dx = value - base_value
            derivatives = {k: (v-runs[0]['metrics'][k])/dx for k,v in _metrics(output).items()
                if k in runs[0]['metrics']} if dx and matched_population else {}
            result['sensitivity'].append({'parameter': body.parameter, 'value': value,
                'baseline_value': base_value, 'metrics': _metrics(output), 'derivatives': derivatives})
    shared_previews(products, body.base.operation, cancel)
    result['metric_table'] = _metric_table(runs, populations)
    result['comparison_warning'] = (
        'Output populations differ. Aggregate deltas and response slopes are disabled for unmatched populations; pixel differences use only common valid cells.'
        if not all(populations) else '')
    if file_sha256(path) != source_checksum or any(file_sha256(resolve(identifier)) != checksum
            for identifier,checksum in dependencies.items()):
        raise RasterError('Source bytes changed during the experiment; discard this result and retry.')
    result['manifest'] = {
        'schema': 'geofathom-research-1', 'created_at': datetime.now(timezone.utc).isoformat(),
        'input': body.model_dump(), 'source': {**describe(body.base.image_id), 'sha256': source_checksum},
        'dependencies': [{**describe(identifier), 'sha256': file_sha256(resolve(identifier))}
            for identifier in [body.base.dsm_image_id,body.base.external_inflow_image_id] if identifier],
        'grid': {'crs': str(crs), 'transform': list(affine), 'shape': list(z.shape),
                 'valid_source_cells': int(valid.sum())},
        'software': {'python': platform.python_version(), 'numpy': np.__version__,
                     'rasterio': rasterio.__version__, 'gdal': rasterio.__gdal_version__,
                     **software_revision()},
        'method': 'Matched source, geometry and grid; candidate minus baseline on common valid cells.',
        'limitations': ['Source accuracy is not independently validated.',
            'Scenario spread is not a confidence interval.',
            'Monte Carlo intervals are conditional on the supplied error model; finite sampling error is reported.',
            'Study-boundary and source NoData masks are retained.'],
        'references': ['https://doi.org/10.59161/JCGM101-2008'],
    }
    # Lock subsequent reproduction to the actual source bytes.
    result['manifest']['input']['expected_source_sha256'] = source_checksum
    result['manifest']['input']['expected_dependency_sha256'] = {item['id']:item['sha256'] for item in result['manifest']['dependencies']}
    result['archive_base64'] = base64.b64encode(research_archive(result, cancel)).decode('ascii')
    checkpoint(cancel)
    return result


def _uncertainty(body, path, resolve, z, valid, affine, crs, baseline, result, cancel):
    """Seeded PCG64 Monte Carlo with independent or common-offset DEM errors.

    Perturb the bounded original source window (including outside-polygon cells
    used by derivative stencils); keep original nodata fixed. Quantiles require
    validity in *every* realization to avoid selection-biased uncertainty maps.
    """
    rng = np.random.Generator(np.random.PCG64(body.seed))
    arrays = []
    metrics = []
    with rasterio.open(path) as source:
        tags = source.tags()
    with tempfile.TemporaryDirectory(prefix='geofathom-research-') as directory:
        temporary = Path(directory) / 'perturbed.tif'
        for index in range(body.samples):
            checkpoint(cancel)
            noise = rng.normal(0, body.sigma_m, z.shape if body.error_model == 'independent' else 1)
            perturbed = z + noise
            with rasterio.open(temporary, 'w', driver='GTiff', height=z.shape[0], width=z.shape[1],
                count=1, dtype='float64', crs=crs, transform=affine, nodata=float('nan')) as dst:
                dst.write(perturbed, 1)
                dst.update_tags(**tags)
            output = execute(body.base, temporary, resolve, cancel, include_plot_data=False)
            metrics.append(_metrics(output))
            if output.get('raster'):
                arrays.append(unpack(output['raster'])[0])
    alpha = (1-body.coverage)/2
    summaries = {}
    realizations = {}
    for key in sorted(set.intersection(*(set(m) for m in metrics))):
        data = np.array([m[key] for m in metrics])
        realizations[key] = data.tolist()
        low, high = np.quantile(data, [alpha, 1-alpha], method='linear')
        half = body.samples // 2
        first = np.quantile(data[:half], [alpha,1-alpha])
        second = np.quantile(data[half:], [alpha,1-alpha])
        summaries[key] = {'baseline': _metrics(baseline).get(key), 'mean': float(data.mean()),
            'std': float(data.std(ddof=1)), 'low': float(low), 'high': float(high),
            'mean_standard_error': float(data.std(ddof=1)/math.sqrt(body.samples)),
            'split_half_endpoint_difference': float(np.max(np.abs(first-second)))}
    result['uncertainty'] = {'model': body.error_model, 'sigma_m': body.sigma_m,
        'seed': body.seed, 'generator': 'PCG64', 'samples': body.samples, 'coverage': body.coverage,
        'interval_type': 'empirical_equal_tail_model_coverage', 'metrics': summaries,
        'realizations': realizations,
        'warning': 'Assumed Gaussian vertical errors, not measured accuracy or a confidence interval of the mean. '
            'Pointwise intervals are not simultaneous spatial bounds. Split-half endpoint differences diagnose sampling instability; convergence is not certified.'}
    if arrays:
        stack = np.stack(arrays)
        common = np.isfinite(stack).all(axis=0)
        if not common.any():
            raise RasterError('No cells are valid in every uncertainty realization.')
        data = stack[:,common]
        quantities = {'mean': data.mean(axis=0), 'std': data.std(axis=0, ddof=1),
            'low': np.quantile(data,alpha,axis=0), 'high': np.quantile(data,1-alpha,axis=0)}
        result['uncertainty']['common_cells'] = int(common.sum())
        unit = baseline['raster']['unit']
        for key, quantity in quantities.items():
            checkpoint(cancel)
            grid = np.full(z.shape, np.nan)
            grid[common] = quantity
            product = research_raster(grid, affine, crs, unit, 'Uncertainty ' + key,
                'uncertainty_' + key, result['uncertainty'] | {'metrics': 'see manifest'}, cancel)
            plot_data = continuous_data(grid.astype(np.float32), 'Uncertainty ' + key, unit,
                abs(affine.a * affine.e - affine.b * affine.d), cancel)
            if plot_data is not None:
                plot_data['classes'] = []
            result['products'].append({'name': 'Uncertainty ' + key, 'role': key, 'raster': product,
                                       'plot_data': plot_data})


def _csv(rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    for row in rows:
        # CSV spreadsheet formulas are data, never executable report content.
        writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in row])
    return stream.getvalue()


def research_archive(result, cancel=None):
    from .research_report import make_report
    checkpoint(cancel)
    manifest = {k:v for k,v in result.items() if k not in {'products', 'differences', 'archive_base64'}}
    manifest['artifacts'] = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for i, item in enumerate(result['products'] + result['differences']):
            checkpoint(cancel)
            name = f'rasters/{i+1:02d}'
            manifest['artifacts'].append({'name': item['name'], 'path': name+'.tif',
                'unit': item['raster']['unit'], 'role': item.get('role', item.get('kind')),
                'statistics': item.get('statistics'), 'preview_scale':item['raster'].get('preview_scale')})
            archive.writestr(name+'.tif', base64.b64decode(item['raster']['geotiff']))
            archive.writestr(name+'.png', base64.b64decode(item['raster']['png'].split(',',1)[1]))
        labels = [r['label'] for r in result['runs']]
        archive.writestr('metrics.csv', _csv([['metric', *labels]] +
            [[r['metric'], *r['values']] for r in result['metric_table']]))
        if result['sensitivity']:
            archive.writestr('sensitivity.csv', _csv([['parameter','value','metric','response','derivative_from_baseline']] +
                [[r['parameter'], r['value'], k,v,r['derivatives'].get(k)]
                 for r in result['sensitivity'] for k,v in r['metrics'].items()]))
        if result.get('factorial'):
            grid = result['factorial']
            archive.writestr('factorial.csv', _csv([[grid['x_parameter'],grid['y_parameter'],'metric','response','matched_population']] +
                [[c['x'],c['y'],key,value,c['matched_population']] for c in grid['cells'] for key,value in c['metrics'].items()]))
        archive.writestr('figure-tables.json', json.dumps([
            {'name': item['name'], 'role': item.get('role', item.get('kind')), 'plot_data': item['plot_data']}
            for item in result['products'] + result['differences'] if item.get('plot_data')], allow_nan=False))
        if result['uncertainty']:
            archive.writestr('uncertainty-realizations.csv', _csv([['realization', *result['uncertainty']['realizations']]] +
                [[i+1, *[series[i] for series in result['uncertainty']['realizations'].values()]]
                 for i in range(result['uncertainty']['samples'])]))
            fields = ['baseline','mean','std','low','high','mean_standard_error','split_half_endpoint_difference']
            archive.writestr('uncertainty.csv', _csv([['metric',*fields]] +
                [[k,*[v[f] for f in fields]] for k,v in result['uncertainty']['metrics'].items()]))
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False))
        archive.writestr('experiment.json', json.dumps(result['manifest']['input'], ensure_ascii=False, indent=2, allow_nan=False))
        archive.writestr('report.pdf', make_report(result, cancel))
        archive.writestr('README.txt', 'POST experiment.json to /terrain/research/analyze to reproduce.\n'
            'The source image must remain available with the recorded SHA-256.\n'
            'GeoTIFFs retain the projected study grid. PNGs are map previews.\n'
            'Metrics retain their quantity/unit suffixes; raster units are in manifest.json and GeoTIFF tags.\n'
            'Research intervals depend on the declared model; they do not certify accuracy.\n')
    return buffer.getvalue()
