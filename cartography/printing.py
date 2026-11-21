"""Vector cartographic PDF layout with geodesic scale, map grid and metadata.

Produces a true single-page vector PDF, not a low-resolution screenshot.
Rendering intentionally contains project-owned geometries and does NOT
download unlicensed basemaps or assert cadastral/legal accuracy.
"""
import io
import math
from datetime import datetime,timezone

from pyproj import Transformer
from reportlab.lib import colors
from reportlab.lib.pagesizes import A3,A4,letter,landscape,portrait
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas
from shapely.geometry import shape
from shapely.ops import transform
from shapely.ops import unary_union

from geometry.measure import measure_geometry,GeometryError
from storage.database import StorageError
from storage.paging import bounding_candidates
from storage.workspace import layers as read_layers

_SIZES={"a4":A4,"a3":A3,"letter":letter}

def _rgb(value,fallback="#2563eb"):
    try:return colors.HexColor(value)
    except (TypeError,ValueError):return colors.HexColor(fallback)

def _nice_distance(target):
    if not target or target<=0:return 1
    order=10**math.floor(math.log10(target))
    return max(1,(max(x for x in (1,2,5,10) if x*order<=target)
                  if target>=order else 1)*order)

def _label(c,text,x,y,size=10,color="#263e55",max_width=180):
    text=str(text).replace("\n"," ").replace("\r"," ").strip()[:90]
    c.setFont("Helvetica",size)
    c.setFillColor(_rgb(color))
    while len(text)>1 and c.stringWidth(text,"Helvetica",size)>max_width:
        text=text[:-2]+"…"
    c.drawString(x,y,text)

def render_pdf(project_id:str,title:str="GeoFathom map",paper:str="a4",
               orientation:str="landscape",extent:list[float]|None=None,
               show_grid:bool=True,show_legend:bool=True,
               layer_ids:list[str]|None=None)->bytes:
    title=title.strip()
    if not 1<=len(title)<=120:raise StorageError("Map title must have 1–120 characters.")
    if paper not in _SIZES or orientation not in {"landscape","portrait"}:
        raise StorageError("Unsupported paper format or orientation.")
    visible=[layer for layer in read_layers(project_id) if layer["visible"] and
             (not layer_ids or layer["id"] in layer_ids)]
    if layer_ids:
        available={layer["id"] for layer in read_layers(project_id)}
        if any(lid not in available for lid in layer_ids):
            raise StorageError("Layer not found.")
    all_items=bounding_candidates(project_id,extent or (-179.99,-85,179.99,85),
                                  [layer["id"] for layer in visible] if visible else None,
                                  visible_only=True,max_candidates=15000) if visible else []
    if not visible:all_items=[]
    if extent is None:
        if not all_items:raise StorageError("Map has no visible features. Specify an extent.")
        bounds=unary_union([shape(item["geometry"]) for item in all_items]).bounds
        dx=max(bounds[2]-bounds[0],.01)
        dy=max(bounds[3]-bounds[1],.01)
        extent=[bounds[0]-.1*dx,bounds[1]-.1*dy,bounds[2]+.1*dx,bounds[3]+.1*dy]
        extent=[max(-179.99,extent[0]),max(-85,extent[1]),
                min(179.99,extent[2]),min(85,extent[3])]
    else:
        if len(extent)!=4:raise StorageError("Invalid WGS84 print extent.")
        west,south,east,north=extent
        if not (-180<west<east<180 and -85<south<north<85 and east-west<=70):
            raise StorageError("Print extent must be a bounded area, without dateline crossing.")
    west,south,east,north=extent
    if east-west>70:raise StorageError("Print layout supports regional extents up to 70°.")
    center_lon=(west+east)/2;center_lat=(south+north)/2
    projection=(f"+proj=aeqd +lat_0={center_lat} +lon_0={center_lon} "
                "+datum=WGS84 +units=m +no_defs")
    forward=Transformer.from_crs("EPSG:4326",projection,always_xy=True).transform
    mapped=[(r,transform(forward,shape(r["geometry"]))) for r in all_items]
    frame=unary_union([shape({"type":"Point","coordinates":p}) for p in
          [[west,south],[east,south],[east,north],[west,north]]])
    corners=[forward(*p) for p in [[west,south],[east,south],[east,north],[west,north],
                                  [west,(south+north)/2],[east,(south+north)/2],
                                  [(west+east)/2,south],[(west+east)/2,north]]]
    xs=[p[0] for p in corners];ys=[p[1] for p in corners]
    left,right,bottom,top=min(xs),max(xs),min(ys),max(ys)
    if not math.isfinite(right-left) or right-left<=0 or top-bottom<=0:
        raise StorageError("Cannot render this geographic extent.")
    page=(landscape if orientation=="landscape" else portrait)(_SIZES[paper])
    W,H=page
    sidebar=150 if show_legend else 0
    map_x,map_y=42,84
    map_width=W-84-sidebar;map_height=H-156
    scale=min(map_width/(right-left),map_height/(top-bottom))
    cx=(left+right)/2;cy=(top+bottom)/2
    def project_xy(x,y):
        return map_x+map_width/2+(x-cx)*scale,map_y+map_height/2+(y-cy)*scale
    def draw_path(geom):
        path=c.beginPath()
        def ring(coords):
            points=[project_xy(x,y) for x,y in coords]
            if not points:return
            path.moveTo(*points[0])
            for x,y in points[1:]:path.lineTo(x,y)
            path.close()
        if geom.geom_type=="Polygon":
            for r in [geom.exterior,*geom.interiors]:ring(r.coords)
        elif geom.geom_type=="MultiPolygon":
            for p in geom.geoms:
                for r in [p.exterior,*p.interiors]:ring(r.coords)
        elif geom.geom_type=="LineString":
            points=[project_xy(x,y) for x,y in geom.coords]
            if len(points)<2:return None
            path.moveTo(*points[0])
            for p in points[1:]:path.lineTo(*p)
        elif geom.geom_type=="MultiLineString":
            for part in geom.geoms:
                points=[project_xy(x,y) for x,y in part.coords]
                if len(points)<2:continue
                path.moveTo(*points[0])
                for p in points[1:]:path.lineTo(*p)
        return path

    stream=io.BytesIO()
    c=Canvas(stream,pagesize=page,pageCompression=1)
    c.setTitle(title);c.setAuthor("GeoFathom")
    c.setSubject("Project vector map; WGS84 geographic input, regional metric map scale")
    c.setFillColor(colors.white);c.rect(0,0,W,H,fill=1,stroke=0)
    c.setFillColor(_rgb("#1b3351"));c.setFont("Helvetica-Bold",18)
    c.drawString(42,H-48,title)
    c.setStrokeColor(_rgb("#d2e2f0"));c.line(42,H-61,W-42,H-61)
    c.setFillColor(_rgb("#f5f8fc"));c.rect(map_x,map_y,map_width,map_height,fill=1,stroke=0)
    # Clip spatial content to the printed map frame.
    clipping=c.beginPath()
    clipping.rect(map_x,map_y,map_width,map_height)
    c.saveState();c.clipPath(clipping,stroke=0,fill=0)
    if show_grid:
        c.setStrokeColor(_rgb("#d6dfeb"));c.setLineWidth(.4)
        for index in range(1,6):
            lon=west+(east-west)*index/6
            last=None
            for step in range(31):
                lat=south+(north-south)*step/30
                current=project_xy(*forward(lon,lat))
                if last:c.line(*last,*current)
                last=current
            lat=south+(north-south)*index/6
            last=None
            for step in range(31):
                lng=west+(east-west)*step/30
                current=project_xy(*forward(lng,lat))
                if last:c.line(*last,*current)
                last=current
    palette={layer["id"]:layer for layer in visible}
    total=0
    for row,geom in mapped:
        layer=palette.get(row["layer_id"])
        if not layer:continue
        style=layer.get("style") or {}
        symbol=style.get("symbol",{})
        c.setLineWidth(float(symbol.get("line_width",2))*.65)
        c.setStrokeColor(_rgb(layer["color"]))
        c.setFillColor(_rgb(layer["color"]))
        c.setFillAlpha(min(1,max(0,float(symbol.get("fill_opacity",.17)))))
        if geom.geom_type=="Point":
            x,y=project_xy(geom.x,geom.y)
            c.setFillAlpha(1)
            c.circle(x,y,max(2,float(symbol.get("point_radius",5))*.6),
                     fill=1,stroke=1)
        else:
            path=draw_path(geom)
            if path:
                c.drawPath(path,fill=int(geom.geom_type in {"Polygon","MultiPolygon"}),
                           stroke=1,fillMode=0)
        total+=1
        label_settings=style.get("labels",{})
        is_note=row["properties"].get("annotation") is True
        if is_note or label_settings.get("enabled"):
            field=label_settings.get("field","name")
            text=(row["properties"].get("annotation_text") if is_note else
                  row["name"] if field=="name" else row["source"] if field=="source" else
                  row["properties"].get(field,""))
            if text not in (None,"") and not geom.is_empty:
                target=geom.representative_point()
                x,y=project_xy(target.x,target.y)
                c.setFillAlpha(1)
                _label(c,text,x+3,y+5,size=min(12,label_settings.get("font_size",10)),
                       color=label_settings.get("text_color","#1b3553"),max_width=115)
    c.restoreState()
    c.setStrokeColor(_rgb("#bacbdb"));c.setLineWidth(1)
    c.rect(map_x,map_y,map_width,map_height,fill=0,stroke=1)
    # Graphic north arrow. AEQD projection has true north along the center meridian.
    cx_arrow=map_x+map_width-28;cy_arrow=map_y+map_height-35
    c.setFillColor(_rgb("#253f62"));c.setStrokeColor(_rgb("#253f62"))
    arrow=c.beginPath()
    arrow.moveTo(cx_arrow,cy_arrow+23);arrow.lineTo(cx_arrow-6,cy_arrow+1)
    arrow.lineTo(cx_arrow,cy_arrow+6);arrow.lineTo(cx_arrow+6,cy_arrow+1)
    arrow.close();c.drawPath(arrow,fill=1,stroke=0)
    _label(c,"N",cx_arrow-3,cy_arrow+28,10)
    # Scale reflects local projection meters.
    distance=_nice_distance((map_width*.28)/scale)
    distance=min(distance,(map_width*.3)/scale)
    width=distance*scale
    y=map_y+16;x=map_x+18
    c.setFillColor(_rgb("#102946"));c.rect(x,y,width/2,6,fill=1,stroke=0)
    c.setFillColor(colors.white);c.rect(x+width/2,y,width/2,6,fill=1,stroke=1)
    _label(c,"0",x,y+10,8);_label(c,f"{distance/1000:g} km" if distance>=1000
          else f"{distance:g} m",x+max(width-25,0),y+10,8)
    if show_legend:
        x=map_x+map_width+18
        c.setFont("Helvetica-Bold",11);c.setFillColor(_rgb("#2b4263"))
        c.drawString(x,H-93,"LAYERS")
        for index,layer in enumerate(visible[:20]):
            ypos=H-115-21*index
            c.setFillColor(_rgb(layer["color"]))
            c.rect(x,ypos-3,12,10,stroke=0,fill=1)
            _label(c,layer["name"],x+19,ypos,9,max_width=110)
        if len(visible)>20:_label(c,f"+{len(visible)-20} more",x,H-115-21*20,8)
        _label(c,f"Features: {total}",x,map_y+27,8)
    _label(c,"WGS84 features · local AEQD map projection · metric scale at center",
           map_x,59,8,color="#627992",max_width=W-85)
    _label(c,"Map geometry does not establish land ownership or survey accuracy.",
           map_x,42,8,color="#627992",max_width=W-85)
    _label(c,datetime.now(timezone.utc).strftime("UTC %Y-%m-%d"),map_x,25,8,
           color="#627992")
    c.showPage();c.save()
    data=stream.getvalue()
    if len(data)>30_000_000:raise StorageError("Printed map exceeds the 30 MB output limit.")
    return data
