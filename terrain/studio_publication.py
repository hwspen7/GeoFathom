"""Numerical and layout helpers for publication-grade response and profile figures."""
from __future__ import annotations
import math
import numpy as np
from .studio_data import FigureInputError

def require(ok, message):
    if not ok:
        raise FigureInputError(message)

def response_grid(table, x_name, y_name, z_name):
    """Retain actual design coordinates, including explicitly missing responses."""
    x,y,z = [table.numeric(name) for name in (x_name,y_name,z_name)]
    require(np.isfinite(x).all() and np.isfinite(y).all(), 'Design coordinates cannot be missing.')
    xs,ys=np.unique(x),np.unique(y)
    require(len(xs)>=2 and len(ys)>=2 and len(xs)*len(ys)<=2500,
            'Design needs at least two levels per axis and at most 2,500 grid positions.')
    values=np.full((len(ys),len(xs)),np.nan)
    seen=set()
    for a,b,c in zip(x,y,z):
        ij=(int(np.searchsorted(ys,b)),int(np.searchsorted(xs,a)))
        require(ij not in seen,'Duplicate design combination.')
        seen.add(ij)
        values[ij]=c
    require(np.isfinite(values).any(),'No valid response values.')
    return xs,ys,values

def cell_edges(v):
    v=np.asarray(v,dtype=float)
    m=(v[1:]+v[:-1])/2
    return np.r_[v[0]-(m[0]-v[0]),m,v[-1]+(v[-1]-m[-1])]

def profile_data(table, x_name, columns, mode):
    """Distance-aligned profile observations; preserve each series' NoData gaps."""
    x=table.numeric(x_name)
    require(len(x)>=2 and np.isfinite(x).all(),'Profile distance needs at least two finite observations.')
    order=np.argsort(x,kind='stable')
    x=x[order]
    require(np.all(np.diff(x)>0),'Profile distances must be unique.')
    require(x[0]>=0,'Profile distance cannot be negative.')
    require(2<=len(columns)<=12,'Choose two to twelve profile columns.')
    a=np.stack([table.numeric(n)[order] for n in columns])
    require(np.isfinite(a).any(),'No finite profile values.')
    if mode=='delta':
        a=a[1:]-a[0]
        names=[n+' − '+columns[0] for n in columns[1:]]
    else:names=columns
    if mode=='bands':
        require(len(columns)%3==0,'Select columns in ordered mean, lower, upper triples.')
        for i in range(0,len(columns),3):
            mean,lo,hi=a[i:i+3]
            mask=np.isfinite(mean)&np.isfinite(lo)&np.isfinite(hi)
            require(mask.any() and np.all((lo[mask]<=mean[mask])&(mean[mask]<=hi[mask])),
                    'Each profile interval needs valid ordered bounds containing its estimate.')
            # A missing bound breaks the band, but not the recorded mean.
    require(np.isfinite(a).any(),'No common valid profile differences.')
    return x,a,names

def raster_profiles(grids, table, x_name, y_name):
    """Sample native pixels at projected path coordinates, with cumulative distance."""
    from .studio_data import aligned_grids
    aligned_grids(grids)
    g=grids[0]
    require(g.is_meter,'Raster transects require a projected metre CRS.')
    x,y=[table.numeric(n) for n in (x_name,y_name)]
    require(len(x)>=2 and np.isfinite(x).all() and np.isfinite(y).all(),'Path coordinates must be finite.')
    steps=np.hypot(np.diff(x),np.diff(y))
    require(np.all(steps>0),'Consecutive path coordinates must be distinct.')
    distance=np.r_[0,np.cumsum(steps)]
    a=g.transform
    col=np.floor((x-a.c)/a.a).astype(np.int64)
    row=np.floor((y-a.f)/a.e).astype(np.int64)
    inside=(row>=0)&(row<g.values.shape[0])&(col>=0)&(col<g.values.shape[1])
    values=np.full((len(grids),len(x)),np.nan)
    for i,item in enumerate(grids):
        values[i,inside]=item.values[row[inside],col[inside]]
    require(np.isfinite(values).any(),'No valid raster observations along this path.')
    return distance,values

def numeric_rows(headers,*arrays):
    return [list(headers),*[[None if isinstance(v,(float,np.floating)) and not np.isfinite(v) else
             v.item() if isinstance(v,np.generic) else v for v in row] for row in zip(*arrays)]]

def layout_receipt(fig):
    """Inspect axes and text tight bounds at the actual canvas dimensions."""
    fig.canvas.draw()
    renderer=fig.canvas.get_renderer()
    width,height=fig.canvas.get_width_height()
    clipped=[]
    axes=[]
    for i,ax in enumerate(fig.axes):
        if not ax.get_visible():continue
        box=ax.get_tightbbox(renderer)
        if box is None:continue
        axes.append([round(v,3) for v in (box.x0/width,box.y0/height,box.x1/width,box.y1/height)])
        if box.x0 < -2 or box.y0 < -2 or box.x1 > width+2 or box.y1 > height+2:
            clipped.append(i+1)
    return {'canvas_pixels':[width,height],'axes_bounds_normalized':axes,
            'potentially_clipped_axes':clipped,'layout_check':'canvas bounds only; visual review still required'}

def draw_legacy_panel(container, scene, label):
    """Render the native gallery's validated vector scene without rasterizing it."""
    from matplotlib.patches import Rectangle, Circle, Polygon
    ax=container.add_subplot(111)
    ax.set_xlim(0,scene.width);ax.set_ylim(scene.height,0);ax.set_aspect('equal');ax.axis('off')
    # The scene's native coordinates are pixels. Scale strokes and text to
    # the actual panel width in points; maintain geometry in scene units.
    parent=container.get_figure(root=True)
    factor=min(container.bbox.width/parent.dpi*72/scene.width,container.bbox.height/parent.dpi*72/scene.height)*.88
    for p in scene.primitives:
        face=p.fill;edge=p.stroke;lw=p.line_width*factor
        style='--' if p.dashed else '-'
        if p.kind=='line':ax.plot([p.x,p.x2],[p.y,p.y2],color=edge,linewidth=lw,linestyle=style)
        elif p.kind=='rect':ax.add_patch(Rectangle((p.x,p.y),p.width,p.height,facecolor=face,edgecolor=edge if lw else 'none',linewidth=lw,linestyle=style))
        elif p.kind=='circle':ax.add_patch(Circle((p.x,p.y),p.radius,facecolor=face,edgecolor=edge if lw else 'none',linewidth=lw))
        elif p.kind in {'polyline','polygon'} and p.points:
            if p.kind=='polygon':ax.add_patch(Polygon(p.points,closed=True,facecolor=face,edgecolor=edge,linewidth=lw,linestyle=style))
            else:ax.plot(*zip(*p.points),color=edge,linewidth=lw,linestyle=style)
        elif p.kind=='text':
            ax.text(p.x,p.y,p.text,ha={'start':'left','middle':'center','end':'right'}[p.anchor],
                    va='baseline',rotation=-p.angle,rotation_mode='anchor',fontsize=max(3,p.font_size*factor),
                    fontfamily='serif' if p.font=='serif' else 'sans-serif',color=face if face!='none' else '#222222')
    container.suptitle(label, x=.025,ha='left',fontsize=10,fontweight='medium')
