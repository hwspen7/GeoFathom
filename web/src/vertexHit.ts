/** Deterministic editing hit-test against authoritative geometry, not a
 * potentially stale MapLibre queryRenderedFeatures worker frame.
 *
 * Every tool (inspection, dragging, deletion) must resolve the same vertex
 * path for the same screen location. Exact geometry is never subsampled.
 */
import {verticesOf,type GeometryPath,type Position} from './editing';

export type EditableHandle={path:GeometryPath;point:Position;midpoint:boolean};
export type ScreenPosition={x:number;y:number};
export type Projection=(coordinate:Position)=>ScreenPosition;

export function nearestEditableHandle(
  geometry:GeoJSON.Geometry,
  pointer:ScreenPosition,
  project:Projection,
  mode:'vertex'|'midpoint'|'both'='both',
):EditableHandle|null{
  let found:EditableHandle|null=null;
  let bestDistance=Infinity;
  for(const candidate of verticesOf(geometry)){
    if(mode==='vertex'&&candidate.midpoint || mode==='midpoint'&&!candidate.midpoint)continue;
    const xy=project(candidate.point);
    if(!Number.isFinite(xy.x)||!Number.isFinite(xy.y))continue;
    const distance=Math.hypot(pointer.x-xy.x,pointer.y-xy.y);
    // Vertices and midpoints use bounded pixel tolerances regardless of zoom.
    // A midpoint must never win when a vertex is closer to the pointer.
    const tolerance=candidate.midpoint?8:10;
    if(distance>tolerance)continue;
    if(distance<bestDistance-1e-6 ||
      Math.abs(distance-bestDistance)<=1e-6 && found?.midpoint && !candidate.midpoint){
      bestDistance=distance;
      found=candidate;
    }
  }
  return found;
}
