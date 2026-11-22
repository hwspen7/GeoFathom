"""Projected terrain products with explicit masks, units and bounded computation."""
import base64
import heapq
import io
import math

import numpy as np
import rasterio
from PIL import Image
from rasterio.io import MemoryFile
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform
from rasterio.transform import array_bounds
from shapely.geometry import LineString, MultiLineString
from imagery.raster import RasterError
from .cancellation import checkpoint

SURFACES = {"elevation", "slope_map", "aspect_map", "hillshade", "tri", "tpi",
            "curvature", "plan_curvature", "profile_curvature", "flow_direction", "flow_accumulation", "streams",
            "suitability", "cutfill_map", "least_cost"}
D8 = ((-1,0,64),(-1,1,128),(0,1,1),(1,1,2),(1,0,4),
      (1,-1,8),(0,-1,16),(-1,-1,32))
COLORS = ("#263c84","#287fa5","#65b5a2","#d8cf76","#bc7b42","#873c34")
# High-lightness slope palette on top of vector basemaps; scientific classes
# and exact float32 GeoTIFF values are unchanged.
SLOPE_COLORS = ("#dcebec","#96cbc8","#5eac9e","#ebc579","#d68e60","#a94946")
DIRECTION_COLORS = ("#777777","#d94841","#d59635","#269d68","#285cb0",
                    "#853a9b","#999d39","#2caabb","#be709b")

def derivatives(z, valid, dx, dy):
    """Horn gradients, Riley TRI, mean-neighbor TPI and Laplacian on complete windows."""
    if min(z.shape)<3:
        raise RasterError("Terrain derivatives require a 3 × 3 grid.")
    p=np.lib.stride_tricks.sliding_window_view(z,(3,3))
    windows=np.lib.stride_tricks.sliding_window_view(valid,(3,3))
    good=windows.all(axis=(-1,-2))
    if not good.any():
        raise RasterError("No complete valid 3 × 3 terrain neighborhoods.")
    c=p[:,:,1,1]
    e=(p[:,:,0,2]+2*p[:,:,1,2]+p[:,:,2,2]-p[:,:,0,0]-2*p[:,:,1,0]-p[:,:,2,0])/(8*dx)
    s=(p[:,:,2,0]+2*p[:,:,2,1]+p[:,:,2,2]-p[:,:,0,0]-2*p[:,:,0,1]-p[:,:,0,2])/(8*dy)
    gradient=np.hypot(e,s)
    slope=np.degrees(np.arctan(gradient))
    aspect=np.degrees(np.arctan2(-e,s))%360
    aspect=np.where(gradient>1e-12,aspect,np.nan)
    tri=np.sqrt(((p-c[:,:,None,None])**2).sum(axis=(-1,-2)))
    tpi=c-(p.sum(axis=(-1,-2))-c)/8
    zxx=(p[:,:,1,0]+p[:,:,1,2]-2*c)/dx**2
    zyy=(p[:,:,0,1]+p[:,:,2,1]-2*c)/dy**2
    zxy=(p[:,:,2,2]-p[:,:,2,0]-p[:,:,0,2]+p[:,:,0,0])/(4*dx*dy)
    lap=zxx+zyy
    # Profile/plan curvature in inverse meters. A horizontal cell has
    # undefined slope direction, so directional curvature remains NoData.
    squared=e*e+s*s
    with np.errstate(divide="ignore",invalid="ignore"):
        profile_curvature=(e*e*zxx+2*e*s*zxy+s*s*zyy)/(squared*(1+squared)**1.5)
        plan_curvature=(s*s*zxx-2*e*s*zxy+e*e*zyy)/squared**1.5
    profile_curvature=np.where(squared>1e-12,profile_curvature,np.nan)
    plan_curvature=np.where(squared>1e-12,plan_curvature,np.nan)
    def pad(a):
        out=np.full(z.shape,np.nan)
        out[1:-1,1:-1]=np.where(good,a,np.nan)
        return out
    return {k:pad(v) for k,v in {"slope_map":slope,"aspect_map":aspect,"tri":tri,
             "tpi":tpi,"curvature":lap,"plan_curvature":plan_curvature,
             "profile_curvature":profile_curvature,"east":e,"south":s}.items()}

def d8_directions(z, valid, dx, dy, cancel=None):
    """Steepest strictly downhill receiver; deterministic tie order shared by all products."""
    h,w=z.shape
    dst=np.full(z.shape,-1,dtype=np.int64)
    direction=np.zeros(z.shape,dtype=np.float64)
    best=np.zeros(z.shape)
    for dr,dc,code in D8:
        checkpoint(cancel)
        rs=slice(max(0,-dr),min(h,h-dr));cs=slice(max(0,-dc),min(w,w-dc))
        rt=slice(max(0,dr),min(h,h+dr));ct=slice(max(0,dc),min(w,w+dc))
        drop=(z[rs,cs]-z[rt,ct])/math.hypot(dr*dy,dc*dx)
        good=valid[rs,cs]&valid[rt,ct]&(drop>best[rs,cs])
        rr,cc=np.indices(drop.shape)
        best[rs,cs][good]=drop[good];dst[rs,cs][good]=((rr+rt.start)*w+cc+ct.start)[good]
        direction[rs,cs][good]=code
    return dst,np.where(valid,direction,np.nan)

def d8_flow(z, valid, dx, dy, cancel=None):
    """Strict downhill D8; accumulation includes each cell itself."""
    dst,direction=d8_directions(z,valid,dx,dy,cancel)
    cells=np.flatnonzero(valid.ravel())
    order=cells[np.argsort(z.ravel()[cells],kind="stable")[::-1]]
    accum=valid.ravel().astype(np.int64)
    flat=dst.ravel()
    for i,index in enumerate(order):
        if i%4096==0:checkpoint(cancel)
        target=flat[index]
        if target>=0:accum[target]+=accum[index]
    return dst,direction,np.where(valid,accum.reshape(z.shape),np.nan)

def least_cost(z,valid,start,end,dx,dy,max_grade,cancel=None):
    """Dijkstra on raster cell centres; no diagonal corner cutting through nodata."""
    if valid.size>262144:raise RasterError("Route grid exceeds 262,144 cells.")
    if not math.isfinite(max_grade) or not 0<max_grade<=90:
        raise RasterError("Route slope limit must be in (0, 90] degrees.")
    h,w=z.shape
    dist=np.full(z.shape,np.inf);dist[start]=0
    prev=np.full(z.shape,-1,dtype=np.int64)
    queue=[(0.,*start)];iterations=0
    while queue:
        cost,r,c=heapq.heappop(queue)
        iterations+=1
        if iterations%1024==0:checkpoint(cancel)
        if cost!=dist[r,c]:continue
        if (r,c)==end:break
        for dr,dc,_ in D8:
            rr,cc=r+dr,c+dc
            if not (0<=rr<h and 0<=cc<w and valid[rr,cc]):continue
            # Both orthogonal neighbors of a diagonal move must be valid;
            # this avoids crossing between two blocked/no-data cells.
            if dr and dc and not (valid[r,cc] and valid[rr,c]):
                continue
            horizontal=math.hypot(dr*dy,dc*dx)
            rise=float(z[rr,cc]-z[r,c]);grade=math.degrees(math.atan(abs(rise)/horizontal))
            if grade>max_grade:continue
            # Cost is surface length with a symmetric grade penalty.
            candidate=cost+math.hypot(horizontal,rise)*(1+(rise/horizontal)**2)
            if candidate<dist[rr,cc]:
                dist[rr,cc]=candidate;prev[rr,cc]=r*w+c
                heapq.heappush(queue,(candidate,rr,cc))
    if not np.isfinite(dist[end]):raise RasterError("No valid terrain route within the slope limit.")
    path=[end]
    while path[-1]!=start:
        index=prev[path[-1]]
        path.append(divmod(int(index),w))
    path.reverse()
    return path,float(dist[end])

def circular_mean_degrees(angles):
    """Return an angular mean only when the resultant direction is well-defined."""
    if not len(angles):return None
    radians=np.deg2rad(angles)
    east=float(np.sin(radians).mean());north=float(np.cos(radians).mean())
    if math.hypot(east,north)<1e-8:return None
    direction=float(np.rad2deg(np.arctan2(east,north))%360)
    return 0.0 if 360-direction<1e-10 else direction

def _hex(value):
    return tuple(int(value[i:i+2],16) for i in (1,3,5))

def classification(values,operation):
    """Stable engineering classes for angles and categorical products."""
    finite=np.isfinite(values)
    if not finite.any():raise RasterError("No valid cells for this terrain product.")
    lo,hi=float(values[finite].min()),float(values[finite].max())
    if operation=="slope_map":
        edges=[0,5,15,25,35,45,90];labels=["0–5°","5–15°","15–25°","25–35°","35–45°","45–90°"]
    elif operation=="aspect_map":
        labels=["N","NE","E","SE","S","SW","W","NW","Flat"]
        return np.where(finite,np.where(values<0,8,np.floor(((values+22.5)%360)/45)),-1).astype(np.int16),labels,(*COLORS,"#743a9b","#278577","#a6adb4")
    elif operation=="hillshade":
        edges=[0,43,85,128,170,213,255];labels=["0–43","43–85","85–128","128–170","170–213","213–255"]
    elif operation=="flow_direction":
        codes=[0,64,128,1,2,4,8,16,32]
        classes=np.full(values.shape,-1,dtype=np.int16)
        for i,code in enumerate(codes):classes[finite&(values==code)]=i
        return classes,["Sink/flat","N","NE","E","SE","S","SW","W","NW"],DIRECTION_COLORS
    elif operation in {"streams","suitability","least_cost"}:
        return np.where(finite,values,-1).astype(np.int16),["Other","Selected"],("#a6adb4","#16856f")
    elif operation=="cutfill_map":
        return np.where(finite,np.where(values<0,0,np.where(values>0,2,1)),-1).astype(np.int16),["Fill","Balanced","Cut"],("#287fa5","#b8b8b8","#b95b37")
    elif operation=="dem_difference":
        # Diverging classes are always zero-centered, even for one-sided
        # changes. Original GeoTIFF values and statistics are unaffected.
        classes=np.full(values.shape,-1,dtype=np.int16)
        max_abs=max(abs(lo),abs(hi))
        if max_abs==0:
            classes[finite]=3
        else:
            inner=max_abs/3
            outer=2*max_abs/3
            v=values[finite]
            classes[finite]=np.select(
                [v<=-outer,v<=-inner,v<0,v==0,v<inner,v<outer],
                [0,1,2,3,4,5],default=6
            ).astype(np.int16)
        labels=(["Large decrease","Decrease","Small decrease","No change (0 m)",
                 "Small increase","Increase","Large increase"] if max_abs==0 else
                [f"≤ -{outer:.3g} m",f"-{outer:.3g} to -{inner:.3g} m",
                 f"-{inner:.3g} to 0 m","No change (0 m)",
                 f"0 to {inner:.3g} m",f"{inner:.3g} to {outer:.3g} m",
                 f"≥ {outer:.3g} m"])
        return classes,labels,("#225c8f","#6a98bf","#b7d0e1","#d8d8d8",
                              "#e9c1ab","#c87953","#98432d")
    else:
        edges=np.linspace(lo,hi,7).tolist() if lo!=hi else [lo,hi]
        labels=[f"{a:.3g}–{b:.3g}" for a,b in zip(edges,edges[1:])]
    classes=np.full(values.shape,-1,dtype=np.int16)
    classes[finite]=np.digitize(values[finite],edges[1:-1])
    return classes,labels,(("#222222","#555555","#888888","#aaaaaa","#dddddd","#ffffff") if operation=="hillshade" else SLOPE_COLORS if operation=="slope_map" else COLORS)[:len(labels)]

def raster_product(values,operation,affine,crs,cancel=None):
    """Export exact source-grid GeoTIFF and a Web Mercator map preview with alpha nodata."""
    checkpoint(cancel)
    classes,labels,colors=classification(values,operation)
    finite=np.isfinite(values)
    legend=[{"label":label,"color":color,"cells":int((classes==i).sum())}
            for i,(label,color) in enumerate(zip(labels,colors))]
    height,width=values.shape
    with MemoryFile() as memory:
        with memory.open(driver="GTiff",height=height,width=width,count=1,dtype="float32",
                         crs=crs,transform=affine,nodata=float("nan"),compress="deflate") as dst:
            dst.write(values.astype(np.float32),1)
            dst.update_tags(TERRAIN_OPERATION=operation)
        tif=base64.b64encode(memory.read()).decode("ascii")
    bounds=array_bounds(height,width,affine)
    target,tw,th=calculate_default_transform(crs,"EPSG:3857",width,height,*bounds)
    factor=max(tw,th)/512
    if factor>1:
        target=target*rasterio.Affine.scale(factor,factor)
        tw=max(1,math.ceil(tw/factor));th=max(1,math.ceil(th/factor))
    preview=np.full((th,tw),-1,dtype=np.int16)
    reproject(classes,preview,src_transform=affine,src_crs=crs,src_nodata=-1,
              dst_transform=target,dst_crs="EPSG:3857",dst_nodata=-1,resampling=Resampling.nearest)
    rgba=np.zeros((th,tw,4),dtype=np.uint8)
    for i,color in enumerate(colors):rgba[preview==i]=(*_hex(color),255)
    if operation=="hillshade":
        # Continuous grayscale relief; preserve nodata transparency.
        brightness=np.full((th,tw),np.nan,dtype=np.float32)
        reproject(values.astype(np.float32),brightness,src_transform=affine,src_crs=crs,src_nodata=float("nan"),
                  dst_transform=target,dst_crs="EPSG:3857",dst_nodata=float("nan"),resampling=Resampling.bilinear)
        good=np.isfinite(brightness)&(preview>=0)
        rgba[:]=0;rgba[good,:3]=np.repeat(np.clip(brightness[good],0,255).astype(np.uint8)[:,None],3,axis=1)
        rgba[good,3]=255
    sink=io.BytesIO();Image.fromarray(rgba).save(sink,format="PNG")
    west,south,east,north=array_bounds(th,tw,target)
    xs,ys=transform("EPSG:3857","EPSG:4326",[west,east,east,west],[north,north,south,south])
    checkpoint(cancel)
    return {"png":"data:image/png;base64,"+base64.b64encode(sink.getvalue()).decode("ascii"),
            "geotiff":tif,"corners":[[x,y] for x,y in zip(xs,ys)],"legend":legend,
            "width":width,"height":height,"valid_cells":int(finite.sum())}

def surface(z,valid,affine,crs,operation,reference,point,end_point,max_slope,
            min_elevation,max_elevation,max_tri,stream_cells,azimuth,altitude,feature,origin,cancel=None):
    """Return the exact source-grid derivative and product-specific statistics."""
    dx,dy=abs(affine.a),abs(affine.e);cell=dx*dy
    features=[];metrics={}
    if operation=="elevation":
        values=np.where(valid,z,np.nan)
    elif operation=="cutfill_map":
        if not math.isfinite(reference):raise RasterError("Reference elevation must be finite.")
        values=np.where(valid,z-reference,np.nan)
        metrics={"cut_m3":float(np.nansum(np.maximum(values,0))*cell),
                 "fill_m3":float(np.nansum(np.maximum(-values,0))*cell)}
    elif operation in {"flow_direction","flow_accumulation","streams"}:
        dst,direction,accum=d8_flow(z,valid,dx,dy,cancel)
        if operation=="flow_direction":values=direction
        elif operation=="flow_accumulation":values=accum
        else:
            if not 1<=stream_cells<=1_000_000:raise RasterError("Invalid stream accumulation threshold.")
            values=np.where(valid,(accum>=stream_cells).astype(float),np.nan)
            stream=(values==1).ravel()
            # Trace each edge once; cap the vector output while preserving the full raster.
            indices=np.flatnonzero(stream&(dst.ravel()>=0))
            indices=indices[stream[dst.ravel()[indices]]]
            if len(indices)<=20000:
                for start in range(0,len(indices),256):
                    checkpoint(cancel)
                    lines=[]
                    for index in indices[start:start+256]:
                        target=int(dst.ravel()[index])
                        r,c=divmod(int(index),z.shape[1]);rr,cc=divmod(target,z.shape[1])
                        lines.append([affine*(c+.5,r+.5),affine*(cc+.5,rr+.5)])
                    features.append(feature(MultiLineString(lines),crs,{"name":"Drainage network","color":"#167bb8"}))
            metrics={"stream_cells":int(stream.sum()),"stream_threshold_cells":stream_cells,
                     "drainage_edges":int(len(indices)),"vector_edges":int(len(indices)) if features else 0}
    elif operation=="least_cost":
        start=origin(point,crs,affine,valid);end=origin(end_point,crs,affine,valid)
        if start==end:raise RasterError("Route endpoints must occupy different cells.")
        route,cost=least_cost(z,valid,start,end,dx,dy,max_slope,cancel)
        coordinates=[affine*(c+.5,r+.5) for r,c in route]
        line=LineString(coordinates)
        values=np.where(valid,0.,np.nan)
        for r,c in route:values[r,c]=1
        features=[feature(line,crs,{"name":"Least-cost route","color":"#b74127"})]
        metrics={"route_length_m":float(line.length),"route_cost":cost,"route_cells":len(route)}
    else:
        d=derivatives(z,valid,dx,dy);checkpoint(cancel)
        if operation=="hillshade":
            if not (0<=azimuth<=360 and 0<=altitude<=90):raise RasterError("Invalid sun angles.")
            a,b=math.radians(azimuth),math.radians(altitude)
            east,south=d["east"],d["south"]
            values=255*np.clip((math.sin(b)-east*math.cos(b)*math.sin(a)+south*math.cos(b)*math.cos(a))/np.sqrt(1+east**2+south**2),0,1)
        elif operation=="suitability":
            if not (0<=max_slope<=90 and min_elevation<=max_elevation and max_tri>=0):
                raise RasterError("Invalid suitability limits.")
            good=np.isfinite(d["slope_map"])
            passed=(d["slope_map"]<=max_slope)&(z>=min_elevation)&(z<=max_elevation)&(d["tri"]<=max_tri)
            values=np.where(good,passed.astype(float),np.nan)
            metrics={"suitable_area_m2":float((values==1).sum()*cell),
                     "suitable_pct":float(100*(values==1).sum()/good.sum())}
        elif operation=="aspect_map":
            values=np.where(np.isfinite(d["slope_map"])&~np.isfinite(d["aspect_map"]),-1,d["aspect_map"])
        else:values=d[operation]
    if not np.isfinite(values).any():raise RasterError("No valid cells for this terrain product.")
    product=raster_product(values,operation,affine,crs,cancel)
    if operation in {"flow_direction","streams","suitability","least_cost"}:
        metrics["product_valid_cells"]=product["valid_cells"]
    elif operation=="aspect_map":
        angles=values[np.isfinite(values)&(values>=0)]
        metrics.update({"flat_cells":int((values==-1).sum()),
                        "directional_cells":int(angles.size),"product_valid_cells":product["valid_cells"]})
        if angles.size:
            bearing=circular_mean_degrees(angles)
            if bearing is not None:metrics["circular_mean_aspect_deg"]=bearing
    else:
        metrics.update({"product_valid_cells":product["valid_cells"],
                        "product_min":float(np.nanmin(values)),"product_max":float(np.nanmax(values)),
                        "product_mean":float(np.nanmean(values))})
    return product,metrics,features
