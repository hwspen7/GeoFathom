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

def fit_publication_text(fig):
    """Rotate only demonstrably crowded tick labels, retaining numeric values."""
    if not hasattr(fig,'canvas'):return
    fig.canvas.draw()
    renderer=fig.canvas.get_renderer()
    for ax in fig.axes:
        if not ax.get_visible() or ax.name!='rectilinear' or getattr(ax,'_colorbar',None) is not None:continue
        ticks=[t for t in ax.get_xticklabels() if t.get_visible() and t.get_text()]
        if len(ticks)<2:continue
        bounds=[t.get_window_extent(renderer) for t in ticks]
        ordered=sorted(bounds,key=lambda b:b.x0)
        if any(a.x1>b.x0+2 and min(a.y1,b.y1)-max(a.y0,b.y0)>2 for a,b in zip(ordered,ordered[1:])):
            if all(abs(t.get_rotation())<1 for t in ticks):
                for t in ticks:t.set_rotation(35);t.set_ha('right');t.set_rotation_mode('anchor')
    fig.canvas.draw()


def layout_receipt(fig):
    """Measure actual canvas, clipped text and same-axis tick overlaps.

    Intentional text over data (e.g. map annotations) is not treated as a
    collision. This is a mechanical preflight, not human publication approval.
    """
    fig.canvas.draw()
    renderer=fig.canvas.get_renderer()
    width,height=fig.canvas.get_width_height()
    clipped=[];axes=[];text_clipped=[];tick_overlaps=[]
    for i,ax in enumerate(fig.axes):
        if not ax.get_visible():continue
        box=ax.get_tightbbox(renderer)
        if box is not None:
            axes.append([round(v,3) for v in (box.x0/width,box.y0/height,box.x1/width,box.y1/height)])
            if box.x0 < -2 or box.y0 < -2 or box.x1 > width+2 or box.y1 > height+2:clipped.append(i+1)
        for direction,labels in [('x',ax.get_xticklabels()),('y',ax.get_yticklabels())]:
            if ax.name!='rectilinear':continue
            boxes=[(t.get_text(),t.get_window_extent(renderer)) for t in labels if t.get_visible() and t.get_text()]
            for label,b in boxes:
                if b.x0 < -2 or b.y0 < -2 or b.x1 > width+2 or b.y1 > height+2:
                    text_clipped.append({'axis':i+1,'text':label[:100]})
            for j,(first,a) in enumerate(boxes):
                for second,b in boxes[j+1:]:
                    overlap_x=min(a.x1,b.x1)-max(a.x0,b.x0)
                    overlap_y=min(a.y1,b.y1)-max(a.y0,b.y0)
                    if overlap_x>3 and overlap_y>3:
                        tick_overlaps.append({'axis':i+1,'direction':direction,'labels':[first[:60],second[:60]]})
                        if len(tick_overlaps)>=100:break
                if len(tick_overlaps)>=100:break
    return {'canvas_pixels':[width,height],'axes_bounds_normalized':axes,
            'potentially_clipped_axes':clipped,'clipped_tick_text':text_clipped[:100],
            'tick_overlaps':tick_overlaps[:100],
            'layout_check':'canvas and tick bounding-box preflight; visual review still required'}



def prepare_publication(fig):
    """Try compact typography without changing data, axis limits or figure size.

    Layout is finalized on the Agg canvas and frozen before vector/raster
    export to avoid backend-dependent constrained-layout recalculation.
    Unresolved layout problems remain explicitly visible in the receipt.
    """
    import warnings
    from matplotlib.text import Text
    attempts=[]
    original={id(text):text.get_fontsize() for text in fig.findobj(match=Text)}
    receipt=None
    for factor in (1.,.90,.80,.70):
        for text in fig.findobj(match=Text):
            if id(text) in original:
                text.set_fontsize(max(min(6,original[id(text)]),original[id(text)]*factor))
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter('always',UserWarning)
            fit_publication_text(fig)
            receipt=layout_receipt(fig)
        layout_warnings=list(dict.fromkeys(str(w.message) for w in captured if 'layout' in str(w.message).lower()))
        collapsed=any(ax.get_visible() and min(ax.get_position().width,ax.get_position().height)<.025 for ax in fig.axes)
        unresolved=bool(layout_warnings or collapsed or receipt['potentially_clipped_axes'] or receipt['clipped_tick_text'] or receipt['tick_overlaps'])
        attempts.append({'font_factor':factor,'layout_warnings':layout_warnings,'collapsed_axes':collapsed,'unresolved':unresolved})
        # Do not discard labels, reduce plotted data, or expand requested page dimensions.
        if not unresolved:break
    receipt.update(preflight_passed=not attempts[-1]['unresolved'],layout_attempts=attempts,
                   typography_factor=attempts[-1]['font_factor'],layout_frozen=True)
    fig.set_layout_engine('none')
    return receipt

def publication_title(text,width_mm,font_size):
    import textwrap
    # Conservative physical-width estimate, including long uninterrupted words.
    columns=max(14,int(width_mm/25.4*72/(font_size*.62)))
    return textwrap.fill(text,width=columns,break_long_words=True,break_on_hyphens=False)

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
