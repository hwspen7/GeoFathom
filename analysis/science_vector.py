"""Projected vector and exact vector/raster integration kernels."""
import math
import numpy as np
from pyproj import CRS,Transformer
from shapely.geometry import shape,mapping,Point,box
from shapely.ops import transform,unary_union
from shapely import STRtree,get_num_coordinates
from rasterio.features import geometry_mask,shapes
from rasterio.transform import rowcol
from .science_raster import require

def load_layers(layers,crs):
    local=CRS.from_user_input(crs)
    require(local.is_projected and all(abs(a.unit_conversion_factor-1)<1e-12 for a in local.axis_info[:2]),'Choose a projected metre CRS.')
    forward=Transformer.from_crs(4326,local,always_xy=True)
    reverse=Transformer.from_crs(local,4326,always_xy=True)
    groups=[];total=0
    for layer in layers:
        require(layer.get('type')=='FeatureCollection' and isinstance(layer.get('features'),list),'Use GeoJSON FeatureCollection in WGS84.')
        items=[]
        for i,f in enumerate(layer['features']):
            require(isinstance(f,dict) and f.get('type')=='Feature' and isinstance(f.get('geometry'),dict),'Invalid GeoJSON feature.')
            g=shape(f['geometry'])
            require(g.geom_type in {'Point','MultiPoint','LineString','MultiLineString','Polygon','MultiPolygon'} and not g.is_empty and g.is_valid and not g.has_z,'Valid nonempty 2D geometries required.')
            xmin,ymin,xmax,ymax=g.bounds
            require(all(math.isfinite(v) for v in g.bounds) and -180<=xmin<=xmax<=180 and -90<=ymin<=ymax<=90 and xmax-xmin<170,'Invalid or antimeridian-spanning coordinates.')
            total+=int(get_num_coordinates(g));require(total<=100000,'Vector coordinate budget exceeded.')
            if local.area_of_use is not None:
                area=local.area_of_use
                require(area.south-1e-7<=ymin and ymax<=area.north+1e-7 and (area.west>area.east or area.west-1e-7<=xmin<=xmax<=area.east+1e-7),'Geometry outside selected CRS area of use.')
            p=transform(forward.transform,g)
            require(p.is_valid and not p.is_empty and all(math.isfinite(v) for v in p.bounds),'Projection produced invalid geometry.')
            items.append((i,p))
        require(0<len(items)<=5000,'Each vector layer needs 1–5,000 features.')
        groups.append(items)
    return groups,reverse

def collection(geometries,reverse):
    features=[]
    for g,props in geometries:
        if g.is_empty:continue
        if g.geom_type=='GeometryCollection':
            for part in g.geoms:
                if not part.is_empty:features.extend(collection([(part,props)],reverse)['features'])
            continue
        require(len(features)<10000 and get_num_coordinates(g)<=100000,'Vector output exceeds geometry budget.')
        world=transform(reverse.transform,g)
        require(world.is_valid and not world.is_empty and all(math.isfinite(v) for v in world.bounds),'Invalid inverse projection.')
        features.append({'type':'Feature','geometry':mapping(world),'properties':props})
    require(len(features)<=10000 and sum(get_num_coordinates(shape(f['geometry'])) for f in features)<=200000,'Vector output exceeds total budget.')
    return {'type':'FeatureCollection','features':features}

def vector_operation(method,groups,reverse,params):
    a=groups[0];b=groups[1] if len(groups)>1 else []
    ga=[g for _,g in a];gb=[g for _,g in b]
    meta={};rows=[];headers=[];out=[]
    if method in {'intersection','union','difference','symmetric_difference','convex_hull'}:
        first=unary_union(ga)
        if method=='convex_hull':g=first.convex_hull
        elif method=='union':g=unary_union(ga+gb)
        else:g=getattr(first,method)(unary_union(gb))
        meta['area_m2']=float(g.area);meta['length_m']=float(g.length)
        out=[(g,{'operation':method,'area_m2':meta['area_m2']})]
    elif method in {'buffer','centroid','simplify'}:
        for i,g in a:
            result=g.buffer(params['distance_m'],quad_segs=16) if method=='buffer' else g.centroid if method=='centroid' else g.simplify(params['distance_m'],preserve_topology=True)
            out.append((result,{'source_index':i,'area_m2':float(result.area),'length_m':float(result.length)}))
    elif method in {'spatial_join','nearest_join'}:
        tree=STRtree(gb);headers=['left_index','right_index','distance_m']
        for i,g in a:
            if method=='spatial_join':
                ids=sorted(tree.query(g,predicate='intersects').tolist())
                require(len(rows)+len(ids)<=20000,'Spatial join output exceeds 20,000 pairs.')
                rows.extend([i,j,0.] for j in ids)
            else:
                ids,dist=tree.query_nearest(g,all_matches=True,return_distance=True)
                j=int(ids.min());rows.append([i,j,float(g.distance(gb[j]))])
    elif method=='sample_polygon':
        region=unary_union(ga);require(region.geom_type in {'Polygon','MultiPolygon'} and region.area>0,'Polygon sample requires polygon coverage.')
        xmin,ymin,xmax,ymax=region.bounds;rng=np.random.default_rng(params['seed']);n=params['count']
        require(n*(xmax-xmin)*(ymax-ymin)/region.area<=100000,'Polygon rejection sampling exceeds budget.')
        from shapely import contains_xy
        samples=[]
        for _ in range(100):
            if len(samples)>=n:break
            batch=min(4096,max(64,4*(n-len(samples))))
            x=rng.uniform(xmin,xmax,batch);y=rng.uniform(ymin,ymax,batch)
            samples.extend(zip(x[contains_xy(region,x,y)],y[contains_xy(region,x,y)]))
        require(len(samples)>=n,'Polygon sampling did not reach requested population within budget.')
        out=[(Point(x,y),{'sample_id':i+1,'area_weight_m2':region.area/n}) for i,(x,y) in enumerate(samples[:n])]
        meta['study_area_m2']=float(region.area)
    elif method in {'point_centers','point_nearest_neighbor'}:
        require(all(g.geom_type=='Point' for g in ga),'Use individual point features.')
        coords=np.array([(g.x,g.y) for g in ga]);n=len(coords)
        if method=='point_centers':
            center=coords.mean(axis=0);sd=float(np.sqrt(np.mean(np.sum((coords-center)**2,axis=1))))
            out=[(Point(*center),{'standard_distance_m':sd,'point_count':n})];meta['standard_distance_m']=sd
        else:
            require(2<=n<=5000,'Nearest-neighbor analysis needs 2–5,000 points.')
            headers=['source_index','neighbor_index','distance_m']
            for start in range(0,n,128):
                d=np.sum((coords[start:start+128,None,:]-coords[None,:,:])**2,axis=2)
                d[np.arange(len(d)),np.arange(start,start+len(d))]=np.inf
                j=d.argmin(axis=1)
                rows.extend([start+i,int(k),float(np.sqrt(d[i,k]))] for i,k in enumerate(j))
            meta['mean_distance_m']=float(np.mean([r[2] for r in rows]))
    else:raise ValueError('Unknown vector method.')
    return collection(out,reverse) if out or not headers else None,headers,rows,meta

def zonal(grid,groups,classes=False):
    z=grid.values;a=grid.transform;h,w=z.shape;header=['zone_index','class_code','area_m2','fraction_of_valid_area'] if classes else ['zone_index','zone_area_m2','covered_area_m2','valid_area_m2','weighted_mean','weighted_sd','minimum','maximum']
    rows=[];budget=0
    for i,g in groups[0]:
        require(g.geom_type in {'Polygon','MultiPolygon'},'Zonal analysis requires polygons.')
        xmin,ymin,xmax,ymax=g.bounds
        c0=max(0,int(math.floor((xmin-a.c)/a.a)));c1=min(w,int(math.ceil((xmax-a.c)/a.a)))
        r0=max(0,int(math.floor((a.f-ymax)/abs(a.e))));r1=min(h,int(math.ceil((a.f-ymin)/abs(a.e))))
        budget+=max(0,c1-c0)*max(0,r1-r0);require(budget<=250000,'Exact zonal intersection budget exceeded.')
        values=[];weights=[];covered=0.
        for r in range(r0,r1):
            for c in range(c0,c1):
                x,y=a*(c,r);cell=box(x,y+a.e,x+a.a,y)
                overlap=g.intersection(cell).area
                covered+=overlap
                if overlap>0 and np.isfinite(z[r,c]):values.append(z[r,c]);weights.append(overlap)
        v=np.asarray(values);weight=np.asarray(weights);valid_area=float(weight.sum())
        if classes:
            require(np.all(v==np.floor(v)),'Class coverage requires integer class values.')
            codes=np.unique(v);require(len(codes)<=256,'Too many class codes.')
            rows.extend([i,float(code),float(weight[v==code].sum()),float(weight[v==code].sum()/valid_area)] for code in codes)
        elif valid_area:
            mean=float(np.average(v,weights=weight));sd=float(np.sqrt(np.average((v-mean)**2,weights=weight)))
            rows.append([i,float(g.area),covered,valid_area,mean,sd,float(v.min()),float(v.max())])
        else:rows.append([i,float(g.area),covered,0.,None,None,None,None])
    return header,rows

def integrated(method,grid,groups,params,reverse):
    z=grid.values;a=grid.transform;valid=np.isfinite(z);out=None;unit=grid.unit;headers=[];rows=[];features=None;meta={}
    if method in {'zonal_statistics','zonal_classes'}:headers,rows=zonal(grid,groups,method=='zonal_classes')
    elif method in {'clip_raster','rasterize'}:
        geoms=[g for _,g in groups[0]];require(all(g.geom_type in {'Polygon','MultiPolygon'} for g in geoms),'Polygon inputs required.')
        inside=geometry_mask(geoms,out_shape=z.shape,transform=a,invert=True,all_touched=False)
        out=np.where(valid&inside,z,np.nan) if method=='clip_raster' else np.where(valid,inside.astype(float),np.nan)
        if method=='rasterize':unit='class'
    elif method=='extract_points':
        headers=['source_index','easting','northing','value']
        for i,g in groups[0]:
            require(g.geom_type=='Point','Individual point features required.')
            r,c=rowcol(a,g.x,g.y);v=z[r,c] if 0<=r<z.shape[0] and 0<=c<z.shape[1] else np.nan
            rows.append([i,g.x,g.y,float(v) if np.isfinite(v) else None])
    elif method=='point_kernel_density':
        geoms=[g for _,g in groups[0]];require(all(g.geom_type=='Point' for g in geoms),'Point intensity requires point features.')
        east,north=grid.axes;b=params['bandwidth_m'];out=np.zeros(z.shape);work=0
        for g in geoms:
            xx=np.flatnonzero(abs(east-g.x)<=4*b);yy=np.flatnonzero(abs(north-g.y)<=4*b)
            work+=len(xx)*len(yy);require(work<=30_000_000,'Kernel density work budget exceeded.')
            if not len(xx) or not len(yy):continue
            d2=(east[xx][None,:]-g.x)**2+(north[yy][:,None]-g.y)**2
            out[np.ix_(yy,xx)]+=np.where(d2<=16*b*b,np.exp(-d2/(2*b*b))/(2*np.pi*b*b),0)
        out[~valid]=np.nan;unit='points/m2';meta['point_count']=len(geoms)
    elif method=='polygonize':
        require(valid.sum()<=250000 and np.all(z[valid]==np.floor(z[valid])) and np.max(abs(z[valid]))<=2**24,'Polygonize requires bounded integer class data.')
        values=[]
        for g,v in shapes(np.where(valid,z,0).astype(np.int32),mask=valid,transform=a,connectivity=4):
            require(len(values)<10000,'Polygonized feature budget exceeded.')
            values.append((shape(g),{'class_code':int(v)}))
        features=collection(values,reverse)
    return out,unit,headers,rows,features,meta
