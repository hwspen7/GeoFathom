/* Pure, testable browser geometry state. Server PyProj is authoritative. */

export type Position = [number, number];
export type ShapeMode = 'polygon' | 'line' | 'rectangle' | 'circle' | 'hole' | 'split' | 'trace-along' | null;
export type GeometryPath = { polygon: number; ring: number; vertex: number };
type Rings = Position[][][];

export function copyGeometry<T extends GeoJSON.Geometry>(value: T): T {
  return structuredClone(value);
}

function rings(geometry: GeoJSON.Geometry): Rings {
  if (geometry.type === 'Polygon') return [geometry.coordinates as Position[][]];
  if (geometry.type === 'MultiPolygon') return geometry.coordinates as Position[][][];
  if (geometry.type === 'LineString') return [[geometry.coordinates as Position[]]];
  return [];
}

function ringAt(geometry: GeoJSON.Geometry, path: GeometryPath): Position[] | null {
  return rings(geometry)[path.polygon]?.[path.ring] ?? null;
}

/** Closing polygon coordinate is a duplicate, never an independent vertex. */
function editableIndex(geometry: GeoJSON.Geometry, ring: Position[], index: number): boolean {
  return Number.isInteger(index) && index >= 0 &&
    index < ring.length - (geometry.type === 'LineString' ? 0 : 1);
}
function closeRing(vertices: Position[]): void {
  if (vertices.length && (vertices[0][0] !== vertices[vertices.length - 1][0] ||
                          vertices[0][1] !== vertices[vertices.length - 1][1])) {
    vertices[vertices.length - 1] = [...vertices[0]];
  }
}

export function verticesOf(geometry: GeoJSON.Geometry): Array<{
  path: GeometryPath; point: Position; midpoint: boolean;
}> {
  const output: Array<{ path: GeometryPath; point: Position; midpoint: boolean }> = [];
  rings(geometry).forEach((polygon, p) => polygon.forEach((ring, r) => {
    const closed = geometry.type !== 'LineString';
    const size = closed ? ring.length - 1 : ring.length;
    for (let v = 0; v < size; v++) {
      output.push({ path: { polygon: p, ring: r, vertex: v }, point: ring[v], midpoint: false });
      if (closed || v + 1 < size) {
        const next = ring[(v + 1) % size];
        output.push({
          path: { polygon: p, ring: r, vertex: v }, midpoint: true,
          point: [(ring[v][0] + next[0]) / 2, (ring[v][1] + next[1]) / 2],
        });
      }
    }
  }));
  return output;
}

export function moveVertex(
  geometry: GeoJSON.Geometry, path: GeometryPath, coordinate: Position,
): GeoJSON.Geometry {
  const result = copyGeometry(geometry);
  const ring = ringAt(result, path);
  if (!ring || !editableIndex(result,ring,path.vertex)) return result;
  ring[path.vertex] = [...coordinate];
  if (result.type !== 'LineString' && path.vertex === 0) closeRing(ring);
  return result;
}

export function addVertex(
  geometry: GeoJSON.Geometry, path: GeometryPath, coordinate: Position,
): GeoJSON.Geometry {
  const result = copyGeometry(geometry);
  const ring = ringAt(result, path);
  if (!ring || !editableIndex(result,ring,path.vertex)) return result;
  ring.splice(path.vertex + 1, 0, [...coordinate]);
  return result;
}

export function removeVertex(geometry: GeoJSON.Geometry, path: GeometryPath): GeoJSON.Geometry {
  const result = copyGeometry(geometry);
  const ring = ringAt(result, path);
  if (!ring || !editableIndex(result,ring,path.vertex)) return result;
  const min = result.type === 'LineString' ? 2 : 4;
  if (ring.length <= min) throw new Error('Cannot delete another vertex from this shape.');
  ring.splice(path.vertex, 1);
  if (result.type !== 'LineString' && path.vertex === 0) closeRing(ring);
  return result;
}

export function shiftGeometry(
  geometry: GeoJSON.Geometry, longitudeDelta: number, latitudeDelta: number,
): GeoJSON.Geometry {
  const result = copyGeometry(geometry);
  function shift(coords: unknown): unknown {
    if (!Array.isArray(coords)) return coords;
    if (typeof coords[0] === 'number') {
      const p = coords as number[];
      return [p[0] + longitudeDelta, p[1] + latitudeDelta];
    }
    return coords.map(shift);
  }
  if ('coordinates' in result) {
    const target = result as GeoJSON.Geometry & { coordinates: unknown };
    target.coordinates = shift(target.coordinates);
  }
  return result;
}

export function approximateMeasurement(geometry: GeoJSON.Geometry): {
  area_m2: number | null; perimeter_m: number | null; length_m: number | null;
} {
  // Fast spherical preview while dragging. FastAPI/PyProj recalculates exact
  // WGS84 ellipsoidal values when an edit commits.
  const radius = 6371008.8;
  const toRad = Math.PI / 180;
  function segment(a: Position, b: Position): number {
    const x = (b[0] - a[0]) * toRad * Math.cos((a[1] + b[1]) * toRad / 2);
    const y = (b[1] - a[1]) * toRad;
    return radius * Math.hypot(x, y);
  }
  function ringStats(ring: Position[]) {
    let perimeter = 0;
    let signedArea = 0;
    for (let i = 0; i < ring.length - 1; i++) {
      const a = ring[i], b = ring[i + 1];
      perimeter += segment(a, b);
      signedArea += (b[0] - a[0]) * toRad *
        (2 + Math.sin(a[1] * toRad) + Math.sin(b[1] * toRad));
    }
    return { perimeter, area: Math.abs(signedArea) * radius * radius / 2 };
  }
  if (geometry.type === 'LineString') {
    const pts = geometry.coordinates as Position[];
    return {
      area_m2: null, perimeter_m: null,
      length_m: pts.slice(1).reduce((sum, point, i) => sum + segment(pts[i], point), 0),
    };
  }
  if (geometry.type === 'Polygon' || geometry.type === 'MultiPolygon') {
    let area = 0, perimeter = 0;
    rings(geometry).forEach(polygon => polygon.forEach((ring, r) => {
      const stats = ringStats(ring);
      area += r === 0 ? stats.area : -stats.area;
      perimeter += stats.perimeter;
    }));
    return { area_m2: Math.max(area, 0), perimeter_m: perimeter, length_m: null };
  }
  return { area_m2: null, perimeter_m: null, length_m: null };
}

export function snapPixels(
  point: Position, targets: Position[], project: (p: Position) => Position,
  tolerance = 12,
): Position {
  const target = project(point);
  let closest = tolerance;
  let snapped = point;
  for (const candidate of targets) {
    const pixel = project(candidate);
    const distance = Math.hypot(target[0] - pixel[0], target[1] - pixel[1]);
    if (distance < closest) { closest = distance; snapped = candidate; }
  }
  return snapped;
}

export class GeometryTimeline {
  private states: Array<GeoJSON.Geometry | null> = [null];
  private index = 0;
  get current(): GeoJSON.Geometry | null { return copyNullable(this.states[this.index]); }
  get canUndo(): boolean { return this.index > 0; }
  get canRedo(): boolean { return this.index + 1 < this.states.length; }

  push(value: GeoJSON.Geometry | null): void {
    if (JSON.stringify(value) === JSON.stringify(this.states[this.index])) return;
    this.states = this.states.slice(0, this.index + 1);
    this.states.push(copyNullable(value));
    if (this.states.length > 100) this.states.shift();
    this.index = this.states.length - 1;
  }
  undo(): GeoJSON.Geometry | null {
    if (this.canUndo) this.index--;
    return this.current;
  }
  redo(): GeoJSON.Geometry | null {
    if (this.canRedo) this.index++;
    return this.current;
  }
}

function copyNullable(value: GeoJSON.Geometry | null): GeoJSON.Geometry | null {
  return value === null ? null : copyGeometry(value);
}


export function pathsOf(geometry: GeoJSON.Geometry): Position[][] {
  if (geometry.type === 'Polygon') return geometry.coordinates as Position[][];
  if (geometry.type === 'MultiPolygon') return geometry.coordinates.flat() as Position[][];
  if (geometry.type === 'LineString') return [geometry.coordinates as Position[]];
  if (geometry.type === 'MultiLineString') return geometry.coordinates as Position[][];
  return [];
}

export function snapToPaths(
  coordinate: Position, paths: Position[][], project: (point: Position) => Position,
  tolerance = 12,
): { position: Position; kind: 'vertex' | 'edge' | 'none' } {
  const click = project(coordinate);
  let nearest = coordinate, best = tolerance, kind: 'vertex' | 'edge' | 'none' = 'none';
  // Vertex priority means a corner stays a corner when near a line segment.
  for (const path of paths) {
    for (const vertex of path) {
      const px = project(vertex);
      const distance = Math.hypot(click[0] - px[0], click[1] - px[1]);
      if (distance < best) { best = distance; nearest = vertex; kind = 'vertex'; }
    }
  }
  if (kind === 'vertex') return { position: nearest, kind };
  for (const path of paths) {
    for (let i = 0; i + 1 < path.length; i++) {
      const start = project(path[i]), end = project(path[i + 1]);
      const dx = end[0] - start[0], dy = end[1] - start[1];
      const len = dx * dx + dy * dy;
      if (len === 0) continue;
      const fraction = Math.max(0, Math.min(1,
        ((click[0] - start[0]) * dx + (click[1] - start[1]) * dy) / len));
      const distance = Math.hypot(click[0] - start[0] - dx * fraction,
                                  click[1] - start[1] - dy * fraction);
      if (distance < best) {
        best = distance;
        nearest = [
          path[i][0] + (path[i + 1][0] - path[i][0]) * fraction,
          path[i][1] + (path[i + 1][1] - path[i][1]) * fraction,
        ];
        kind = 'edge';
      }
    }
  }
  return { position: nearest, kind };
}


export function previewEdgeLengths(geometry: GeoJSON.Geometry, limit = 30): {
  edges: Array<{ label: string; length_m: number }>; total: number;
} {
  const radius = 6371008.8, degrees = Math.PI / 180;
  const paths = pathsOf(geometry);
  const total = paths.reduce((sum, path) => sum + Math.max(0,path.length - 1), 0);
  const edges: Array<{ label: string; length_m: number }> = [];
  for (const [ringIndex, path] of paths.entries()) {
    for (let i = 0; i + 1 < path.length; i++) {
      if (edges.length >= limit) return { edges, total };
      const a=path[i],b=path[i+1];
      const longitude=(b[0]-a[0])*degrees;
      const latitude=(b[1]-a[1])*degrees;
      const factor=Math.cos(((a[1]+b[1])/2)*degrees);
      edges.push({
        label: 'Ring '+(ringIndex+1)+' · edge '+(i+1),
        length_m: radius*Math.hypot(longitude*factor,latitude),
      });
    }
  }
  return { edges, total };
}


export function singleMovedVertex(
  before: GeoJSON.Geometry, after: GeoJSON.Geometry,
): {old:[number,number];next:[number,number]} | null {
  if(before.type!==after.type)return null;
  const oldPaths=pathsOf(before),newPaths=pathsOf(after);
  if(oldPaths.length!==newPaths.length)return null;
  let change: {old:[number,number];next:[number,number]} | null=null;
  for(let i=0;i<oldPaths.length;i++) {
    const a=oldPaths[i],b=newPaths[i];
    if(a.length!==b.length)return null;
    for(let j=0;j<a.length;j++) {
      if(a[j][0]===b[j][0]&&a[j][1]===b[j][1])continue;
      const candidate={old:[...a[j]] as [number,number],next:[...b[j]] as [number,number]};
      if(change && (change.old[0]!==candidate.old[0]||
        change.old[1]!==candidate.old[1]||change.next[0]!==candidate.next[0]||
        change.next[1]!==candidate.next[1]))return null;
      change=candidate;
    }
  }
  return change;
}


// Fast spherical drag preview; server PyProj Geod is authoritative on release.
export function geodesicDrag(from:Position,to:Position): {
  bearing_deg:number;distance_m:number;
} {
  const radius=6371008.8;
  const rad=Math.PI/180;
  const [lon1,lat1]=from.map(x=>x*rad);
  const [lon2,lat2]=to.map(x=>x*rad);
  const dLon=lon2-lon1,dLat=lat2-lat1;
  const half=Math.sin(dLat/2)**2+Math.cos(lat1)*Math.cos(lat2)*Math.sin(dLon/2)**2;
  const distance=2*radius*Math.asin(Math.min(1,Math.sqrt(half)));
  const bearing=Math.atan2(Math.sin(dLon)*Math.cos(lat2),
    Math.cos(lat1)*Math.sin(lat2)-Math.sin(lat1)*Math.cos(lat2)*Math.cos(dLon));
  return {bearing_deg:bearing/rad,distance_m:distance};
}

export function translateSpherical(
  geometry:GeoJSON.Geometry,bearingDeg:number,distanceM:number,
):GeoJSON.Geometry {
  const result=copyGeometry(geometry);
  const angle=bearingDeg*Math.PI/180;
  const delta=distanceM/6371008.8;
  function shifted(value:unknown):unknown {
    if(!Array.isArray(value))return value;
    if(typeof value[0]==='number'){
      const p=value as number[];
      const lon=p[0]*Math.PI/180,lat=p[1]*Math.PI/180;
      const latitude=Math.asin(Math.sin(lat)*Math.cos(delta)+
        Math.cos(lat)*Math.sin(delta)*Math.cos(angle));
      const longitude=lon+Math.atan2(Math.sin(angle)*Math.sin(delta)*Math.cos(lat),
        Math.cos(delta)-Math.sin(lat)*Math.sin(latitude));
      let lng=longitude*180/Math.PI;
      lng=((lng+540)%360)-180;
      return [lng,latitude*180/Math.PI,...p.slice(2)];
    }
    return value.map(shifted);
  }
  if('coordinates' in result){
    (result as GeoJSON.Geometry&{coordinates:unknown}).coordinates=
      shifted((result as GeoJSON.Geometry&{coordinates:unknown}).coordinates);
  }
  return result;
}
