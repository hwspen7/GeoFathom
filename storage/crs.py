"""Per-project EPSG coordinate reference metadata and safe transformations.

MapLibre web tiles remain Web Mercator; WGS84 is still authoritative storage.
Project CRS affects coordinate readouts, analysis requests and projected
grids. The app never pretends that changing CRS reprojects the tile canvas.
"""
from pyproj import CRS,Transformer
from storage.database import StorageError,_connect,_now,_required_project

def _epsg(text):
    if not isinstance(text,str) or len(text)>24 or not text.upper().startswith("EPSG:"):
        raise StorageError("Use a registered EPSG:<code> coordinate reference system.")
    try:
        crs=CRS.from_user_input(text.upper())
        authority=crs.to_authority()
        if not authority or authority[0]!="EPSG":
            raise ValueError("Expected EPSG authority")
        return f"EPSG:{authority[1]}"
    except (ValueError,TypeError) as error:
        raise StorageError("Unknown or unsupported EPSG coordinate system.") from error

def _table(c):
    c.execute("""CREATE TABLE IF NOT EXISTS project_crs(
        project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        epsg TEXT NOT NULL DEFAULT 'EPSG:4326',
        grid_visible INTEGER NOT NULL DEFAULT 0,
        revision INTEGER NOT NULL DEFAULT 0)""")

def get_crs(project_id):
    with _connect() as c:
        _required_project(c,project_id);_table(c)
        row=c.execute("SELECT * FROM project_crs WHERE project_id=?",(project_id,)).fetchone()
    return (dict(row) if row else {
        "project_id":project_id,"epsg":"EPSG:4326",
        "grid_visible":0,"revision":0})

def update_crs(project_id,epsg,grid_visible=False,expected_revision=None):
    value=_epsg(epsg)
    if not isinstance(grid_visible,bool):raise StorageError("Grid visibility must be boolean.")
    with _connect() as c:
        c.execute("BEGIN IMMEDIATE")
        _required_project(c,project_id);_table(c)
        row=c.execute("SELECT * FROM project_crs WHERE project_id=?",(project_id,)).fetchone()
        revision=row["revision"] if row else 0
        if expected_revision is not None and revision!=expected_revision:
            raise StorageError("Project CRS revision conflict.")
        result={"project_id":project_id,"epsg":value,
                "grid_visible":int(grid_visible),"revision":revision+1}
        c.execute("INSERT INTO project_crs VALUES(?,?,?,?) "
            "ON CONFLICT(project_id) DO UPDATE SET epsg=excluded.epsg,"
            "grid_visible=excluded.grid_visible,revision=excluded.revision",
            tuple(result.values()))
        c.execute("UPDATE projects SET updated_at=? WHERE id=?",(_now(),project_id))
        return result

def transform_positions(points,source="EPSG:4326",target="EPSG:3857"):
    src=_epsg(source);dst=_epsg(target)
    if not 1<=len(points)<=2000:
        raise StorageError("Transform between 1 and 2000 coordinate pairs.")
    import math
    for p in points:
        if len(p)!=2 or not all(isinstance(x,(int,float)) and
            not isinstance(x,bool) and math.isfinite(x) for x in p):
            raise StorageError("Coordinate pairs must contain two finite numbers.")
    to=Transformer.from_crs(src,dst,always_xy=True)
    result=[list(to.transform(*p)) for p in points]
    if not all(math.isfinite(x) for pair in result for x in pair):
        raise StorageError("Coordinates are outside the target projection domain.")
    return {"source":src,"target":dst,"coordinates":result,
            "units":CRS.from_user_input(dst).axis_info[0].unit_name}

def projected_grid(project_id,bbox,divisions=5):
    from storage.paging import _bounds
    import math
    if not 2<=divisions<=10:raise StorageError("Grid subdivisions must be 2–10.")
    west,south,east,north=_bounds(bbox)
    source=get_crs(project_id)["epsg"]
    target=CRS.from_user_input(source)
    coords=[(west,south),(west,north),(east,south),(east,north)]
    fwd=Transformer.from_crs("EPSG:4326",target,always_xy=True)
    inv=Transformer.from_crs(target,"EPSG:4326",always_xy=True)
    corners=[fwd.transform(*p) for p in coords]
    if not all(math.isfinite(a) and math.isfinite(b) for a,b in corners):
        raise StorageError("Viewport cannot be represented in the chosen CRS.")
    xs=[p[0] for p in corners];ys=[p[1] for p in corners]
    left,right=min(xs),max(xs);bottom,top=min(ys),max(ys)
    lines=[]
    for dimension in ("x","y"):
        for k in range(1,divisions):
            fraction=k/divisions
            constant=(left+(right-left)*fraction) if dimension=="x" else (bottom+(top-bottom)*fraction)
            points=[]
            for step in range(32):
                proportion=step/31
                x=constant if dimension=="x" else left+(right-left)*proportion
                y=bottom+(top-bottom)*proportion if dimension=="x" else constant
                lon,lat=inv.transform(x,y)
                if not (-180<=lon<=180 and -90<=lat<=90 and
                        math.isfinite(lon) and math.isfinite(lat)):
                    points=[];break
                points.append([lon,lat])
            if points:
                lines.append({"type":"Feature","properties":{
                    "label":f"{constant:,.0f} {target.axis_info[0].unit_name}",
                    "axis":dimension},
                    "geometry":{"type":"LineString","coordinates":points}})
    return {"type":"FeatureCollection","features":lines,
            "crs":source,"method":"grid in project CRS, converted to WGS84 for MapLibre"}
