"""Validated table and georeferenced raster inputs for scientific figures."""
from __future__ import annotations
import base64
import csv
import hashlib
import io
import math
from dataclasses import dataclass
import numpy as np
from rasterio.io import MemoryFile

MAX_TABLE_ROWS = 20000
MAX_COLUMNS = 32
MAX_RASTER_CELLS = 2_000_000
MAX_TOTAL_CELLS = 8_000_000

class FigureInputError(ValueError):
    pass

class Table:
    def __init__(self, text):
        try:
            reader = csv.reader(io.StringIO(text), strict=True)
            self.names = [v.strip().lstrip('\ufeff') for v in next(reader)]
            if not 1 <= len(self.names) <= MAX_COLUMNS or len(set(self.names))!=len(self.names) or any(not s or len(s)>120 for s in self.names):
                raise FigureInputError('CSV requires unique, nonempty column names (maximum 32).')
            self.rows=[]
            for row in reader:
                if not row or not any(v.strip() for v in row): continue
                if len(row)!=len(self.names) or any(len(v)>512 for v in row):
                    raise FigureInputError('Every CSV row must match the header; field length is bounded.')
                self.rows.append(row)
                if len(self.rows)>MAX_TABLE_ROWS: raise FigureInputError('CSV exceeds 20,000 rows.')
        except (StopIteration,csv.Error) as error:
            raise FigureInputError('Invalid CSV table.') from error
        if not self.rows: raise FigureInputError('CSV has no observations.')
        self.columns={name:[r[i].strip() for r in self.rows] for i,name in enumerate(self.names)}
    def labels(self,name):
        if name not in self.columns: raise FigureInputError('Unknown CSV column: '+str(name))
        return np.array(self.columns[name],dtype=str)
    def numeric(self,name):
        values=[]
        for v in self.labels(name):
            if not v: values.append(np.nan);continue
            try: n=float(v)
            except ValueError as error: raise FigureInputError('Non-numeric observation in '+str(name)) from error
            if not math.isfinite(n) or abs(n)>1e100: raise FigureInputError('Nonfinite or excessively large observation in '+str(name))
            values.append(n)
        return np.array(values,dtype=float)
    def aligned(self, names, labels=()):
        if not names: raise FigureInputError('Choose numeric columns.')
        arrays=[self.numeric(n) for n in names]
        cats=[self.labels(n) for n in labels]
        valid=np.logical_and.reduce([np.isfinite(a) for a in arrays]+[a!='' for a in cats])
        if not valid.any(): raise FigureInputError('No complete observations for the selected columns.')
        return [a[valid] for a in arrays], [a[valid] for a in cats],int(valid.sum())
@dataclass
class Grid:
    name:str
    values:np.ndarray
    transform:object
    crs:object
    unit:str
    sha256:str
    @property
    def extent(self):
        a=self.transform;h,w=self.values.shape
        return (a.c,a.c+a.a*w,a.f+a.e*h,a.f)
    @property
    def is_meter(self):
        return bool(self.crs.is_projected and self.crs.linear_units_factor[1]==1)
    @property
    def axes(self):
        x0,x1,y0,y1=self.extent;h,w=self.values.shape
        return np.linspace(x0+(x1-x0)/w/2,x1-(x1-x0)/w/2,w),np.linspace(y1-(y1-y0)/h/2,y0+(y1-y0)/h/2,h)

def read_grids(items):
    grids=[];total=0
    for item in items:
        try:
            raw=base64.b64decode(item.data,validate=True)
            if len(raw)>24_000_000: raise FigureInputError('Encoded raster exceeds size limit.')
            with MemoryFile(raw) as mem,mem.open() as ds:
                if ds.driver!='GTiff' or ds.count!=1 or not ds.crs: raise FigureInputError('Use single-band georeferenced GeoTIFFs.')
                total+=ds.width*ds.height
                if ds.width*ds.height>MAX_RASTER_CELLS or total>MAX_TOTAL_CELLS: raise FigureInputError('Raster rendering exceeds cell budget.')
                a=ds.transform
                if a.b!=0 or a.d!=0 or a.a<=0 or a.e>=0: raise FigureInputError('North-up rasters are required; explicitly reproject rotated grids first.')
                values=ds.read(1,masked=True).astype(np.float64).filled(np.nan)
                values=values*ds.scales[0]+ds.offsets[0]
                values[~np.isfinite(values)]=np.nan
                if not np.isfinite(values).any(): raise FigureInputError('No finite raster cells.')
                if np.nanmax(np.abs(values))>1e100: raise FigureInputError('Raster values exceed numerical range.')
                unit=ds.tags().get('TERRAIN_UNIT') or ds.units[0] or item.unit or ''
                if item.unit and unit and item.unit!=unit: raise FigureInputError('Supplied raster unit conflicts with GeoTIFF metadata.')
                grids.append(Grid(item.name,values,a,ds.crs,unit,hashlib.sha256(raw).hexdigest()))
        except FigureInputError: raise
        except (ValueError,RuntimeError,OSError) as error: raise FigureInputError('Invalid GeoTIFF: '+str(error)) from error
    return grids

def aligned_grids(grids):
    first=grids[0]
    for g in grids[1:]:
        if g.values.shape!=first.values.shape or g.crs!=first.crs or g.transform!=first.transform:
            raise FigureInputError('Raster grids, transforms and CRS must match exactly.')
        if g.unit!=first.unit: raise FigureInputError('Raster physical units must match.')
    stack=np.stack([g.values for g in grids])
    common=np.isfinite(stack).all(axis=0)
    if not common.any(): raise FigureInputError('No common valid raster cells.')
    return stack,common

def normalized(matrix):
    lo=matrix.min(axis=0);span=matrix.max(axis=0)-lo
    return np.divide(matrix-lo,span,out=np.full_like(matrix,.5),where=span>0)

def pareto_mask(x,y,maximize_x=False,maximize_y=False):
    """O(n log n) two-objective nondominance, retaining equal solutions."""
    a=-x if maximize_x else x;b=-y if maximize_y else y
    order=np.lexsort((b,a));mask=np.zeros(a.size,dtype=bool);best=np.inf;i=0
    while i<order.size:
        j=i+1
        while j<order.size and a[order[j]]==a[order[i]]:j+=1
        group=order[i:j];minimum=b[group].min()
        if minimum<best: mask[group[b[group]==minimum]]=True
        best=min(best,minimum);i=j
    return mask

def average_rank(values):
    order=np.argsort(-values,kind='stable');ranks=np.zeros(values.size);i=0
    while i<order.size:
        j=i+1
        while j<order.size and values[order[j]]==values[order[i]]:j+=1
        ranks[order[i:j]]=(i+j+1)/2;i=j
    return ranks

def regular_series(x,y,regular=False):
    order=np.argsort(x,kind='stable');x=x[order];y=y[order]
    if x.size<2 or np.any(np.diff(x)<=0): raise FigureInputError('Time/position values must be distinct.')
    if regular and not np.allclose(np.diff(x),np.diff(x)[0],rtol=1e-6,atol=0):
        raise FigureInputError('This method requires equally spaced observations.')
    return x,y

def rectangular_grid(x,y,z):
    xs=np.unique(x);ys=np.unique(y)
    if len(xs)<2 or len(ys)<2 or len(xs)*len(ys)!=len(z) or len(z)>2500:
        raise FigureInputError('Provide a complete rectangular design (2 to 2,500 distinct combinations).')
    out=np.full((len(ys),len(xs)),np.nan)
    for a,b,c in zip(x,y,z):
        i=np.searchsorted(ys,b);j=np.searchsorted(xs,a)
        if np.isfinite(out[i,j]):raise FigureInputError('Duplicate design combination.')
        out[i,j]=c
    if not np.isfinite(out).all():raise FigureInputError('Incomplete design grid.')
    return xs,ys,out

def linear_fit(x,y):
    if len(x)<3 or np.ptp(x)==0:raise FigureInputError('Regression requires at least three observations and varying predictor.')
    centered=x-x.mean();slope=float(np.dot(centered,y-y.mean())/np.dot(centered,centered))
    fitted=y.mean()+slope*centered
    return fitted,y-fitted,slope,float(y.mean()-slope*x.mean())

def sobol_indices(a,b,hybrids):
    if len(a)<8: raise FigureInputError('Sobol estimator requires at least eight aligned sample pairs; use many more for reliable estimates.')
    variance=float(np.var(np.concatenate((a,b)),ddof=1))
    if variance<=0:raise FigureInputError('Constant model response has undefined Sobol indices.')
    center=float(np.mean(np.concatenate((a,b))))
    first=[float(np.mean((b-center)*(h-a))/variance) for h in hybrids]
    total=[float(np.mean((a-h)**2)/(2*variance)) for h in hybrids]
    return first,total

def morris_effects(trajectory, y, matrix):
    if np.any((matrix<0)|(matrix>1)):raise FigureInputError('Morris coordinates must be normalized to [0,1].')
    effects=[[] for _ in range(matrix.shape[1])]
    for key in dict.fromkeys(trajectory):
        indexes=np.flatnonzero(trajectory==key)
        if len(indexes)!=matrix.shape[1]+1:raise FigureInputError('Each trajectory must have k+1 ordered evaluations.')
        seen=set()
        for a,b in zip(indexes[:-1],indexes[1:]):
            dx=matrix[b]-matrix[a];changed=np.flatnonzero(np.abs(dx)>1e-10)
            if len(changed)!=1 or int(changed[0]) in seen:raise FigureInputError('Each trajectory must change each factor exactly once.')
            j=int(changed[0]);seen.add(j);effects[j].append(float((y[b]-y[a])/dx[j]))
    if any(len(e)<2 for e in effects):raise FigureInputError('At least two complete Morris trajectories are required.')
    return [float(np.mean(np.abs(e))) for e in effects],[float(np.std(e,ddof=1)) for e in effects]


def raster_table(items, limit=MAX_TABLE_ROWS):
    """Export actual common valid cells, explicitly recording systematic sampling."""
    grids=read_grids(items)
    if not grids:raise FigureInputError('Select raster inputs.')
    if not 1<=limit<=MAX_TABLE_ROWS:raise FigureInputError('Invalid cell sample limit.')
    stack,common=aligned_grids(grids)
    indexes=np.flatnonzero(common.ravel());n=int(indexes.size)
    stride=max(1,math.ceil(n/limit));chosen=indexes[::stride]
    row,col=np.unravel_index(chosen,common.shape)
    g=grids[0];a=g.transform
    east=a.c+(col+.5)*a.a;north=a.f+(row+.5)*a.e
    names=['grid_x','grid_y',*[f'value_{i+1}'+(f' ({v.unit})' if v.unit else '') for i,v in enumerate(grids)]]
    f=io.StringIO();writer=csv.writer(f);writer.writerow(names)
    values=[v.ravel()[chosen] for v in stack]
    for r in zip(east,north,*values):writer.writerow(r)
    return {'csv':f.getvalue(),'metadata':{'population':'common finite raster cells',
        'population_cells':n,'sample_cells':int(chosen.size),'sampling':'all_cells' if stride==1 else 'every_kth_common_cell_in_row_major_order',
        'stride':stride,'coordinate_crs':str(g.crs),'columns':[{'column':name,'name':v.name,'sha256':v.sha256,'unit':v.unit} for name,v in zip(names[2:],grids)]}}
