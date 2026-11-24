"""Bounded global sensitivity designs evaluated by the production terrain engine."""
from __future__ import annotations
import csv
import io
import math
import numpy as np
from imagery.raster import RasterError
from imagery.store import file_sha256
from .advanced import _window
from .cancellation import checkpoint
from .research import (execute, unpack, _metrics, software_revision, MAX_ENSEMBLE_CELLS,
                       MAX_SCENARIO_CELLS, SWEEP_PARAMETERS, INTEGER_PARAMETERS)
from .studio_data import sobol_indices, morris_effects

def design(method, bounds, samples, seed):
    """Generate independent uniform paired designs or randomized Morris paths.

    Morris steps use a six-level grid and normalized delta=0.6.
    Returns ordered labels, physical values, and normalized coordinates.
    """
    rng=np.random.default_rng(seed)
    k=len(bounds)
    low=np.asarray([b[0] for b in bounds],float);high=np.asarray([b[1] for b in bounds],float)
    if method=='sobol':
        a,b=rng.random((2,samples,k))
        blocks=[a,b]
        for j in range(k):
            h=a.copy();h[:,j]=b[:,j];blocks.append(h)
        normalized=np.concatenate(blocks)
        labels=[f'{block}:{i+1}' for block in ['A','B',*[f'AB{j+1}' for j in range(k)]] for i in range(samples)]
    else:
        paths=[];labels=[]
        for i in range(samples):
            direction=rng.choice([-1,1],size=k)
            start=rng.integers(0,3,size=k)/5
            current=np.where(direction>0,start,start+.6)
            paths.append(current.copy());labels.append(str(i+1))
            for j in rng.permutation(k):
                current=current.copy();current[j]+=direction[j]*.6
                paths.append(current);labels.append(str(i+1))
        normalized=np.clip(np.asarray(paths),0,1)
    return labels,low+(high-low)*normalized,normalized

def csv_text(header,rows):
    f=io.StringIO();writer=csv.writer(f);writer.writerow(header);writer.writerows(rows);return f.getvalue()

def evaluate_global(body,resolve,cancel=None):
    from .routes import AdvancedTerrainInput
    checkpoint(cancel)
    path=resolve(body.base.image_id)
    checksum=file_sha256(path)
    if body.expected_source_sha256 and checksum!=body.expected_source_sha256:
        raise RasterError('Source checksum changed.')
    dependencies={identifier:file_sha256(resolve(identifier)) for identifier in
                  [body.base.dsm_image_id,body.base.external_inflow_image_id] if identifier}
    names=[f.name for f in body.factors];k=len(names)
    labels,physical,normalized=design(body.method,[(f.minimum,f.maximum) for f in body.factors],body.samples,body.seed)
    z,*_=_window(path,body.base.geometry,4096,MAX_SCENARIO_CELLS)
    if (len(physical)+1)*z.size>MAX_ENSEMBLE_CELLS:
        raise RasterError('Global design exceeds the 12,000,000 cell evaluation budget; reduce study area or sample count.')
    # Validate all parameter combinations before running expensive model calculations.
    variants=[AdvancedTerrainInput.model_validate({**body.base.model_dump(),**dict(zip(names,map(float,row)))}) for row in physical]
    baseline=execute(body.base,path,resolve,cancel,include_plot_data=False)
    if body.metric not in _metrics(baseline):raise RasterError('Selected scalar metric is unavailable for the baseline operation.')
    base_raster=baseline.get('raster')
    base_grid=unpack(base_raster) if base_raster else None
    base_mask=np.isfinite(base_grid[0]) if base_grid else None
    response=[]
    for variant in variants:
        checkpoint(cancel)
        output=execute(variant,path,resolve,cancel,include_plot_data=False)
        metrics=_metrics(output)
        if body.metric not in metrics:raise RasterError('Selected metric is undefined at a design evaluation; no index estimated.')
        candidate=output.get('raster')
        if bool(candidate)!=bool(base_raster):raise RasterError('Output type changes within the global design.')
        if candidate:
            grid,transform,crs=unpack(candidate)
            if (grid.shape!=base_grid[0].shape or transform!=base_grid[1] or crs!=base_grid[2]
                or candidate['unit']!=base_raster['unit'] or not np.array_equal(np.isfinite(grid),base_mask)):
                raise RasterError('Global design changes valid output population or units; indices would not be comparable.')
        response.append(metrics[body.metric])
    if file_sha256(path)!=checksum or any(file_sha256(resolve(i))!=v for i,v in dependencies.items()):
        raise RasterError('Source data changed during the experiment.')
    y=np.asarray(response)
    if body.method=='sobol':
        a,b,*hybrids=y.reshape(k+2,body.samples)
        first,total=sobol_indices(a,b,hybrids)
        # Paired nonparametric bootstrap, retaining A/B/hybrid row structure.
        rng=np.random.default_rng(body.seed+1);draws=[]
        for _ in range(200):
            idx=rng.integers(0,body.samples,body.samples)
            try:draws.append(sobol_indices(a[idx],b[idx],[h[idx] for h in hybrids]))
            except ValueError:continue
        intervals=np.quantile(np.asarray(draws),[.025,.975],axis=0) if len(draws)>=100 else None
        indices=[{'factor':name,'first_order':first[j],'total_order':total[j],
                  'first_low':float(intervals[0,0,j]) if intervals is not None else None,
                  'first_high':float(intervals[1,0,j]) if intervals is not None else None,
                  'total_low':float(intervals[0,1,j]) if intervals is not None else None,
                  'total_high':float(intervals[1,1,j]) if intervals is not None else None}
                 for j,name in enumerate(names)]
        plot_csv=csv_text(['A response','B response',*names],zip(a,b,*hybrids))
        bindings={'x':'A response','y':'B response','columns':names}
        method_note='Independent uniform Monte Carlo paired design; Saltelli first-order and Jansen total-order estimates, 200 paired bootstrap draws. Finite-sample estimates and intervals can be unstable or outside [0,1]. Not a calibrated physical parameter distribution.'
    else:
        mu,sigma=morris_effects(np.asarray(labels),y,normalized)
        indices=[{'factor':name,'mu_star':mu[j],'sigma':sigma[j]} for j,name in enumerate(names)]
        plot_csv=csv_text(['Trajectory','Response',*names],[[label,value,*row] for label,value,row in zip(labels,y,normalized)])
        bindings={'x':'Trajectory','y':'Response','columns':names}
        method_note='Randomized six-level Morris trajectories with normalized step 0.6. Elementary effects are per unit normalized factor; screening, not variance attribution.'
    design_csv=csv_text(['Evaluation',*names,body.metric],[[label,*row,value] for label,row,value in zip(labels,physical,y)])
    return {'method':body.method,'metric':body.metric,'evaluations':len(y),'indices':indices,'plot_csv':plot_csv,
            'design_csv':design_csv,'bindings':bindings,'method_note':method_note,
            'manifest':{'schema':'geofathom-global-sensitivity-1','input':body.model_dump(),
                        'source_sha256':checksum,'dependency_sha256':dependencies,'software':software_revision(),
                        'generator':'numpy.default_rng/PCG64','baseline_metric':_metrics(baseline)[body.metric],
                        'cell_evaluations':int((len(y)+1)*z.size),
                        'warnings':['Small designs are screening estimates; check convergence with independent seeds and larger sample sizes.',
                                    'Independent uniform bounds are assumptions, not measured parameter distributions.']}}
