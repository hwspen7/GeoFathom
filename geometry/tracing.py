"""Follow an existing vector network from two map clicks.

This is topological line-network tracing (not AI image edge detection).
Shapely nodes line crossings; PyProj supplies meter coordinates; C++ BVH
locates the clicked segments and Dijkstra picks the shortest connected route.
"""

import heapq
import math
from collections import defaultdict

from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString
from shapely.ops import unary_union

from .editing import coordinate, projection
from .measure import GeometryError, measure_geometry
from .spatial import SegmentIndex


def trace_along(
    start: list[float], end: list[float], paths: list[list[list[float]]],
    tolerance_m: float = 30.0,
) -> dict:
    origin = coordinate(start)
    target = coordinate(end)
    if (not math.isfinite(tolerance_m) or not 0 < tolerance_m <= 200
            or not 1 <= len(paths) <= 300):
        raise GeometryError("Trace requires 1–300 source paths and a 0–200 m tolerance.")
    forward, backward = projection(origin)
    lines = []
    total = 0
    for path in paths:
        if not 2 <= len(path) <= 4000:
            raise GeometryError("Each trace path needs 2–4,000 positions.")
        positions = [coordinate(pos) for pos in path]
        total += len(positions)
        if total > 20000:
            raise GeometryError("Trace network exceeds 20,000 vertices.")
        lines.append(LineString([forward.transform(*pos) for pos in positions]))
    # Node crossing lines before constructing the graph. Do not automatically
    # bridge grade-separated roads; callers must supply connected source paths.
    noded = unary_union(lines)
    if isinstance(noded, LineString):
        components = [noded]
    elif isinstance(noded, MultiLineString):
        components = list(noded.geoms)
    else:
        components = [g for g in noded.geoms if isinstance(g, LineString)]
    segments=[]
    for component in components:
        vertices=list(component.coords)
        for a,b in zip(vertices,vertices[1:]):
            if math.dist(a,b)>1e-8:
                segments.append((a,b))
    if not segments or len(segments)>30000:
        raise GeometryError("Network contains no usable line segments or is too large.")
    p_start = forward.transform(*origin)
    p_end = forward.transform(*target)
    with SegmentIndex(segments) as spatial:
        snap_a=spatial.query(*p_start,tolerance_m)
        snap_b=spatial.query(*p_end,tolerance_m)
        engine=spatial.engine
    if snap_a is None or snap_b is None:
        raise GeometryError("One or both points are farther than tolerance from the network.")
    def key(p):
        # 1 cm grid joins numerically equivalent endpoints after GEOS noding.
        return (round(p[0],2),round(p[1],2))
    graph=defaultdict(list)
    coordinates={}
    def connect(a,b):
        aa=key(a); bb=key(b)
        coordinates[aa]=a; coordinates[bb]=b
        weight=math.dist(a,b)
        if weight>0:
            graph[aa].append((bb,weight))
            graph[bb].append((aa,weight))
    for a,b in segments:
        connect(a,b)
    a=snap_a["point"]; b=snap_b["point"]
    for snap in (snap_a,snap_b):
        s0,s1=segments[snap["segment"]]
        connect(snap["point"],s0)
        connect(snap["point"],s1)
    if snap_a["segment"]==snap_b["segment"]:
        connect(a,b)
    beginning,ending=key(a),key(b)
    heap=[(0.0,beginning)]
    best={beginning:0.0}
    previous={}
    while heap:
        cost,node=heapq.heappop(heap)
        if cost!=best.get(node): continue
        if node==ending: break
        for adjacent,weight in graph[node]:
            proposal=cost+weight
            if proposal<best.get(adjacent,float("inf")):
                best[adjacent]=proposal
                previous[adjacent]=node
                heapq.heappush(heap,(proposal,adjacent))
    if ending not in best:
        raise GeometryError("Selected positions are on disconnected line networks.")
    route=[ending]
    while route[-1]!=beginning:
        route.append(previous[route[-1]])
    route.reverse()
    if len(route)<2:
        raise GeometryError("Trace endpoints resolve to the same network coordinate.")
    world=[list(backward.transform(*coordinates[node])) for node in route]
    geojson={"type":"LineString","coordinates":world}
    return {
        "geometry":geojson,
        "measurement":measure_geometry(geojson),
        "engine":engine,
        "method":"shortest path on vector line network",
        "snapped_start_distance_m":snap_a["distance_m"],
        "snapped_end_distance_m":snap_b["distance_m"],
        "source":"Existing vector geometry; not satellite edge recognition",
    }
