"""Exact numerical plot tables from terrain quantities, independent of map colors.

All distribution statistics use every finite exported-raster cell. CDF knots
are exact evaluations at selected observed quantiles, never reconstructed
from a color legend. Quantile interpolation follows NumPy's linear method.
"""
import base64
import math
from statistics import NormalDist

import numpy as np
from rasterio.io import MemoryFile
from .cancellation import checkpoint

BIN_COUNTS = (10, 20, 40, 80, 160)
QUANTILE_PROBABILITIES = (0, .01, .05, .1, .25, .5, .75, .9, .95, .99, 1)
CATEGORICAL = {'flow_direction', 'streams', 'visibility', 'viewshed_multi', 'stream_order', 'least_cost'}


def _quantile(ordered, probability):
    rank = probability * (ordered.size - 1)
    lower = int(math.floor(rank)); upper = int(math.ceil(rank))
    return float(ordered[lower]) + (float(ordered[upper])-float(ordered[lower]))*(rank-lower)


def continuous_data(values, quantity, unit, cell_area_m2=1., cancel=None, domain=None):
    """Bounded output tables; sort float32 cells once rather than sampling them."""
    source = np.asarray(values)
    valid = source[np.isfinite(source)].reshape(-1)
    if not valid.size:
        return None
    checkpoint(cancel)
    ordered = np.sort(valid)
    n = int(ordered.size)
    lo, hi = float(ordered[0]), float(ordered[-1])
    # Chunked float64 moments bound additional memory for multi-million grids.
    totals = []
    for offset in range(0,n,65536):
        checkpoint(cancel)
        totals.append(float(np.sum(ordered[offset:offset+65536],dtype=np.float64)))
    mean = math.fsum(totals)/n
    squares=[]
    for offset in range(0,n,65536):
        chunk=ordered[offset:offset+65536].astype(np.float64)-mean
        squares.append(float(np.dot(chunk,chunk)))
    std=math.sqrt(math.fsum(squares)/n)
    quantiles=[{'probability':p, 'value':_quantile(ordered,p)} for p in QUANTILE_PROBABILITIES]
    q1,median,q3=(_quantile(ordered,p) for p in (.25,.5,.75))
    iqr=q3-q1
    lower=int(np.searchsorted(ordered,q1-1.5*iqr,side='left'))
    upper=int(np.searchsorted(ordered,q3+1.5*iqr,side='right'))
    fliers=[]
    for first,last in ((0,lower),(upper,n)):
        if last>first:
            indices=np.unique(np.linspace(first,last-1,min(50,last-first)).astype(int))
            fliers.extend(float(ordered[i]) for i in indices)
    # A bounded set of CDF knots preserves exact cumulative counts at each x.
    knots=sorted(set([_quantile(ordered,p) for p in np.linspace(0,1,257)]))
    cdf=[{'value':x, 'cells_le':int(np.searchsorted(ordered,x,side='right')),
          'percent_le':100*int(np.searchsorted(ordered,x,side='right'))/n} for x in knots]
    if domain:
        start,stop=domain
    elif hi>lo:
        start,stop=lo,hi
    else:
        padding=max(abs(lo)*.005,.5)
        start,stop=lo-padding,hi+padding
    histograms={}
    for bins in BIN_COUNTS:
        checkpoint(cancel)
        edges=np.linspace(start,stop,bins+1)
        positions=np.searchsorted(ordered,edges,side='left')
        positions[0]=0; positions[-1]=n
        counts=np.diff(positions)
        cumulative=np.cumsum(counts)
        histograms[str(bins)]=[{'lower':float(edges[i]),'upper':float(edges[i+1]),
            'midpoint':float((edges[i]+edges[i+1])/2), 'cells':int(count),
            'area_m2':float(count*cell_area_m2),'percent':100*int(count)/n,
            'density':int(count)/(n*float(edges[i+1]-edges[i])),
            'cumulative_pct':100*int(cumulative[i])/n} for i,count in enumerate(counts)]
    return {'schema':'geofathom-plot-data-1','kind':'continuous','quantity':quantity,'unit':unit,
        'population':'all_finite_exported_raster_cells', 'valid_cells':n,'cell_area_m2':cell_area_m2,
        'summary':{'minimum':lo,'maximum':hi,'mean':mean,'population_std':std,
            'q1':q1,'median':median,'q3':q3,'iqr':iqr},
        'histograms':histograms,'cdf':cdf,'quantiles':quantiles,
        'normal_qq':[{'probability':float(p),'normal_quantile':NormalDist().inv_cdf(float(p)),
                      'observed_quantile':_quantile(ordered,float(p))} for p in np.linspace(.005,.995,100)],
        'box':{'q1':q1,'median':median,'q3':q3,'whisker_low':float(ordered[lower]),
               'whisker_high':float(ordered[upper-1]),'lower_outliers':lower,'upper_outliers':n-upper,'fliers':fliers,'displayed_outliers':len(fliers)},
        'notes':['Histograms include every finite output cell; the last bin includes its upper edge.',
            'CDF lines connect at most 257 exact cumulative knots; full-resolution cells remain in the GeoTIFF.',
            'The density curve is a normalized frequency polygon, not a kernel density estimate.',
            'Box whiskers are observed values within 1.5 IQR fences; outlier counts and at most 100 representative outlier markers are reported.']}


def figure_data_from_result(result, cancel=None, source_z=None):
    raster=result.get('raster')
    operation=result['operation']
    area=float(result.get('cell_area_m2',1.))
    labels={'slope_map':'Slope angle','aspect_map':'Aspect','elevation':'Elevation',
        'tri':'Terrain ruggedness','tpi':'Topographic position','hillshade':'Illumination',
        'cutfill_map':'Cut / fill depth','dem_difference':'Elevation change',
        'flow_accumulation':'Contributing cells','flow_accumulation_mfd':'Contributing cell equivalents'}
    base={'schema':'geofathom-plot-data-1','operation':operation,'quantity':labels.get(operation,operation.replace('_',' ')),
        'unit':raster.get('unit','') if raster else '', 'kind':'summary',
        'cell_area_m2':area,'valid_cells':result.get('valid_cells',0),
        'metrics':result.get('metrics',{}),'classes':[],
        'notes':[], 'source_crs':result.get('source_crs'),
        'quality':result.get('quality'),'warning':result.get('warning','')}
    if raster:
        checkpoint(cancel)
        with MemoryFile(base64.b64decode(raster['geotiff'])) as memory, memory.open() as source:
            values=source.read(1)
        base['classes']=[{**entry,'area_m2':entry['cells']*area,
            'percent':100*entry['cells']/max(1,raster['valid_cells'])} for entry in raster['legend']]
        categorical=operation in CATEGORICAL or (operation=='suitability' and raster['unit']!='score_0_to_1')
        if operation=='aspect_map':
            directions=values[np.isfinite(values)&(values>=0)]
            base.update(kind='directional',valid_cells=raster['valid_cells'],directional_cells=int(directions.size),
                flat_cells=int(np.count_nonzero(np.isfinite(values)&(values<0))),roses={})
            for sectors in (8,16,36):
                width=360/sectors
                counts=np.bincount(np.floor(((directions+width/2)%360)/width).astype(int),minlength=sectors)
                base['roses'][str(sectors)]=[{'bearing_deg':i*width,'cells':int(count),
                    'percent':100*int(count)/max(1,directions.size),'area_m2':int(count)*area}
                    for i,count in enumerate(counts)]
            base['notes']=['Rose diagrams exclude flat cells, whose bearing is undefined.']
        elif categorical:
            base.update(kind='categorical',valid_cells=raster['valid_cells'])
        else:
            data=continuous_data(values,base['quantity'],base['unit'],area,cancel)
            if data:base.update(data)
            if source_z is not None and operation!='elevation':
                base['joint']=joint_elevation_data(source_z,values,base['quantity'],base['unit'],area,cancel)
            if operation=='slope_map':
                ordered=np.sort(values[np.isfinite(values)])
                base['thresholds']=[{'threshold_deg':threshold,
                    'cells_le':int(np.searchsorted(ordered,threshold,side='right')),
                    'percent_le':100*int(np.searchsorted(ordered,threshold,side='right'))/max(1,len(ordered))}
                    for threshold in (0,2,5,10,15,20,25,30,35,45,60,90)]
    elif result.get('distribution'):
        # These legacy products carry a pre-binned elevation distribution.
        # Do not invent per-cell quantiles from those bins.
        base.update(kind='binned',quantity='elevation',unit='m',histograms={'20':[
            {'lower':b['lower_m'],'upper':b['upper_m'],'midpoint':(b['lower_m']+b['upper_m'])/2,
             'cells':b['cells'],'area_m2':b['area_m2'],
             'percent':100*b['cells']/max(1,result['valid_cells']),
             'density':b['cells']/max(1,result['valid_cells'])/(b['upper_m']-b['lower_m']) if b['upper_m']>b['lower_m'] else None,
             'cumulative_pct':b['cumulative_pct']} for b in result['distribution']]},
             notes=['Legacy elevation histogram; exact per-cell quantiles require an elevation raster result.'])
    return base


def joint_elevation_data(elevation, product, quantity, unit, cell_area, cancel=None):
    """All-cell moments/density plus an explicitly bounded, deterministic sample."""
    mask=np.isfinite(elevation)&np.isfinite(product)
    x=np.asarray(elevation)[mask];y=np.asarray(product)[mask]
    n=int(x.size)
    if not n:return None
    xlo,xhi=float(x.min()),float(x.max());ylo,yhi=float(y.min()),float(y.max())
    def edges(lo,hi):
        padding=max(abs(lo)*.005,.5) if lo==hi else 0
        return np.linspace(lo-padding,hi+padding,41)
    xe,ye=edges(xlo,xhi),edges(ylo,yhi)
    mx=math.fsum(float(np.sum(x[i:i+65536],dtype=np.float64)) for i in range(0,n,65536))/n
    my=math.fsum(float(np.sum(y[i:i+65536],dtype=np.float64)) for i in range(0,n,65536))/n
    counts=np.zeros((40,40),dtype=np.int64);xx=[];yy=[];xy=[]
    for offset in range(0,n,65536):
        checkpoint(cancel)
        a=x[offset:offset+65536].astype(np.float64);b=y[offset:offset+65536].astype(np.float64)
        ix=np.clip(np.searchsorted(xe,a,side='right')-1,0,39)
        iy=np.clip(np.searchsorted(ye,b,side='right')-1,0,39)
        counts+=np.bincount(ix*40+iy,minlength=1600).reshape(40,40)
        da=a-mx;db=b-my;xx.append(float(np.dot(da,da)));yy.append(float(np.dot(db,db)));xy.append(float(np.dot(da,db)))
    vx=math.fsum(xx);vy=math.fsum(yy)
    indices=np.arange(0,n,max(1,math.ceil(n/2000)))
    return {'x_quantity':'Elevation','x_unit':'m','y_quantity':quantity,'y_unit':unit,
        'population_cells':n,'sample_cells':int(indices.size),'sampling':'every_kth_valid_cell_in_grid_order',
        'samples':[{'x':float(x[i]),'y':float(y[i])} for i in indices],
        'pearson_r':max(-1.,min(1.,math.fsum(xy)/math.sqrt(vx*vy))) if vx>0 and vy>0 else None,
        'density_cells':[{'x_lower':float(xe[i]),'x_upper':float(xe[i+1]),
            'y_lower':float(ye[j]),'y_upper':float(ye[j+1]),'cells':int(counts[i,j]),
            'area_m2':int(counts[i,j])*cell_area} for i in range(40) for j in range(40)],
        'notes':['Density and Pearson correlation use all aligned finite cells.',
                 'Scatter markers are a systematic sample of at most 2,000 valid pairs.',
                 'Spatial correlation is not accounted for in an inferential model; no p-value is claimed.']}
