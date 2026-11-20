/* Pure, testable browser geometry state. Server PyProj is authoritative. */

export type Position = [number, number];
export type ShapeMode = 'polygon' | 'line' | 'rectangle' | 'circle' | 'hole' | 'split' | null;
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
  if (!ring || path.vertex < 0 || path.vertex >= ring.length) return result;
  ring[path.vertex] = [...coordinate];
  if (result.type !== 'LineString' && path.vertex === 0) closeRing(ring);
  return result;
}

export function addVertex(
  geometry: GeoJSON.Geometry, path: GeometryPath, coordinate: Position,
): GeoJSON.Geometry {
  const result = copyGeometry(geometry);
  const ring = ringAt(result, path);
  if (!ring) return result;
  ring.splice(path.vertex + 1, 0, [...coordinate]);
  return result;
}

export function removeVertex(geometry: GeoJSON.Geometry, path: GeometryPath): GeoJSON.Geometry {
  const result = copyGeometry(geometry);
  const ring = ringAt(result, path);
  if (!ring) return result;
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
