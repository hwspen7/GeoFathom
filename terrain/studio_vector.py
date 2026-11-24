"""Native vector cartography and raster overlays, with explicit CRS and attribute semantics."""
import hashlib,json,math
import numpy as np
from .studio_data import FigureInputError

RECIPES=(
 ('research_vector_map','Vector research map','Cartography','vector',''),
 ('research_vector_overlay','Vector and native raster overlay','Cartography','vector',''),
)
IDS={r[0] for r in RECIPES}
MIN_RASTERS={'research_vector_map':0,'research_vector_overlay':1}
NOTES={'research_vector_map':'RFC 7946 longitude/latitude GeoJSON; explicit display EPSG, optional numeric attribute. No invented geometry.',
       'research_vector_overlay':'WGS84 GeoJSON projected onto the selected native raster CRS; clipped to native extent. Raster cells remain unchanged.'}

def require(ok,msg):
    if not ok:raise FigureInputError(msg)

def vector_inputs(collection,target,field):
    import shapely
    from shapely.geometry import shape
    from shapely.ops import transform
    from pyproj import CRS,Transformer
    from pyproj.exceptions import CRSError
    from shapely.errors import GEOSException
    require(isinstance(collection,dict) and collection.get('type')=='FeatureCollection' and 'crs' not in collection,'Use RFC 7946 WGS84 FeatureCollection without legacy CRS.')
    raw=json.dumps(collection,allow_nan=False,sort_keys=True,separators=(',',':')).encode()
    require(len(raw)<=8_000_000,'Vector source exceeds 8 MB.')
    features=collection.get('features');require(isinstance(features,list) and 1<=len(features)<=10000,'Choose 1–10,000 features.')
    try:crs=CRS.from_user_input(target)
    except CRSError as e:raise FigureInputError('Invalid display CRS.') from e
    require(crs.is_projected or crs.is_geographic,'Display CRS must be geographic or projected.')
    projection=Transformer.from_crs('EPSG:4326',crs,always_xy=True)
    records=[];vertices=0
    for i,f in enumerate(features):
        require(isinstance(f,dict) and f.get('type')=='Feature' and isinstance(f.get('geometry'),dict),'Invalid feature geometry.')
        try:geom=shape(f['geometry'])
        except (GEOSException,ValueError,TypeError,KeyError,IndexError) as e:raise FigureInputError('Invalid feature geometry.') from e
        require(not geom.is_empty and geom.is_valid and geom.geom_type in ('Point','MultiPoint','LineString','MultiLineString','Polygon','MultiPolygon'),'Use valid nonempty point, line or polygon geometry.')
        coord=shapely.get_coordinates(geom);vertices+=len(coord)
        require(vertices<=250000 and np.isfinite(coord).all(),'Invalid coordinates or vertex budget exceeded.')
        require(np.all(abs(coord[:,0])<=180) and np.all(abs(coord[:,1])<=90),'GeoJSON coordinates must be longitude/latitude.')
        require(geom.bounds[2]-geom.bounds[0]<=180,'Split antimeridian-crossing geometries before drawing.')
        try:g=transform(projection.transform,geom)
        except (GEOSException,ValueError,TypeError) as e:raise FigureInputError('Geometry projection failed.') from e
        require(g.is_valid and not g.is_empty and np.isfinite(shapely.get_coordinates(g)).all(),'Geometry invalid in chosen display CRS.')
        props=f.get('properties') or {};require(isinstance(props,dict),'Feature properties must be an object.')
        val=props.get(field) if field else None
        if val is not None:require(isinstance(val,(int,float)) and not isinstance(val,bool) and math.isfinite(val) and abs(val)<=1e100,'Selected attribute must be finite numeric or null.')
        records.append((i+1,g,float(val) if val is not None else None))
    return records,{'vector_sha256':hashlib.sha256(raw).hexdigest(),'vector_features':len(records),'vector_vertices':vertices,'display_crs':crs.to_string(),'attribute':field or None}

def render_vector(kind,req,fig,ax,grids,meta):
    from shapely.geometry import box
    from shapely.geometry.polygon import orient
    from matplotlib import colormaps
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable
    from matplotlib.path import Path
    from matplotlib.patches import PathPatch,Patch
    from matplotlib.collections import LineCollection,PatchCollection
    from matplotlib.ticker import MaxNLocator
    overlay=kind=='research_vector_overlay'
    require(len(grids)==int(overlay),'Overlay requires exactly one raster; standalone uses no raster.')
    grid=grids[0] if overlay else None
    target=grid.crs if grid is not None else f'EPSG:{req.vector_epsg}'
    records,receipt=vector_inputs(req.vector_geojson,target,req.vector_attribute);meta.update(receipt)
    meta['input_count']=len(records)
    if grid is not None:
        xmin,xmax,ymin,ymax=grid.extent;extent=box(xmin,ymin,xmax,ymax)
        records=[(i,g.intersection(extent),v) for i,g,v in records if g.intersects(extent)]
        records=[(i,g,v) for i,g,v in records if not g.is_empty]
        cm=colormaps['Greys'].copy();cm.set_bad('#dedede');im=ax.imshow(grid.values,extent=grid.extent,origin='upper',interpolation='nearest',cmap=cm,alpha=.8)
        fig.colorbar(im,ax=ax,shrink=.75,label=grid.unit or 'Raster value')
    require(records,'No features intersect display extent.')
    vals=np.asarray([v for _,_,v in records if v is not None],float)
    if req.vector_attribute:require(len(vals)>0,'Selected attribute has no numeric values in the displayed features.')
    cmap=colormaps[req.sequential_cmap if req.sequential_cmap!='default' else 'viridis']
    norm=None
    if len(vals):
        lo,hi=float(vals.min()),float(vals.max())
        if lo==hi:pad=max(abs(lo)*.01,1e-9);lo-=pad;hi+=pad
        norm=Normalize(lo,hi);meta['attribute_range']=[lo,hi]
    points=[];pc=[];lines=[];lc=[];patches=[];fc=[]
    def add(g,color):
        if hasattr(g,'geoms'):
            for q in g.geoms:add(q,color)
        elif g.geom_type=='Point':points.append((g.x,g.y));pc.append(color)
        elif g.geom_type=='LineString':lines.append(np.asarray(g.coords)[:,:2]);lc.append(color)
        elif g.geom_type=='Polygon':
            g=orient(g,sign=1.);vertices=[];codes=[]
            for ring in [g.exterior,*g.interiors]:
                a=np.asarray(ring.coords)[:,:2];vertices.extend(a);codes.extend([Path.MOVETO]+[Path.LINETO]*(len(a)-2)+[Path.CLOSEPOLY])
            patches.append(PathPatch(Path(vertices,codes)));fc.append(color)
    for _,g,v in records:add(g,cmap(norm(v)) if norm is not None and v is not None else '#909090' if req.vector_attribute else '#0072B2')
    if patches:ax.add_collection(PatchCollection(patches,facecolors=fc,edgecolors='#404040',linewidths=.5,alpha=.65 if overlay else .85,zorder=2))
    if lines:ax.add_collection(LineCollection(lines,colors=lc,linewidths=req.line_width,zorder=3))
    if points:
        a=np.asarray(points);ax.scatter(a[:,0],a[:,1],c=pc,s=22,edgecolors='white',linewidths=.4,zorder=4)
    if overlay:ax.set(xlim=(xmin,xmax),ylim=(ymin,ymax))
    else:ax.autoscale_view();ax.margins(.05)
    ax.set_aspect('equal');ax.ticklabel_format(style='plain',useOffset=False);ax.xaxis.set_major_locator(MaxNLocator(4));ax.yaxis.set_major_locator(MaxNLocator(4))
    ax.set(xlabel='X coordinate',ylabel='Y coordinate')
    if req.map_decoration=='minimal':ax.set(xlabel='',ylabel='',xticks=[],yticks=[])
    if norm is not None:
        fig.colorbar(ScalarMappable(norm=norm,cmap=cmap),ax=ax,shrink=.75,label=req.vector_attribute)
        if len(vals)<len(records):ax.legend(handles=[Patch(facecolor='#909090',label='Missing attribute')])
    meta.update(used_count=len(records),missing_attribute_count=len(records)-len(vals) if req.vector_attribute else 0,rendered_extent=list(ax.get_xlim())+list(ax.get_ylim()),interpretation='Native projected features; vector overlay clipped to raster extent. Coordinates shown in display CRS, not a claim of equal-area or geodesic distance.')
    return [['feature_number','geometry_type','attribute_value'],*[[i,g.geom_type,v] for i,g,v in records]]
