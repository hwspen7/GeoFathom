/** Deterministic sketch topology guards. Screen-space closure is decided by MapCanvas.
 * Coordinates are WGS84; backend Shapely/PyProj remains authoritative at commit.
 */
import type {Position,ShapeMode} from './editing';

const same=(a:Position,b:Position)=>a[0]===b[0]&&a[1]===b[1];
const cross=(a:Position,b:Position,c:Position)=>
  (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);

/** Includes collinear overlaps and endpoint touches. Adjacent edges are skipped by callers. */
export function sketchSegmentsIntersect(a:Position,b:Position,c:Position,d:Position):boolean{
  const scale=Math.max(Math.abs(b[0]-a[0]),Math.abs(b[1]-a[1]),
    Math.abs(d[0]-c[0]),Math.abs(d[1]-c[1]),1e-9);
  const tol=scale*scale*1e-12;
  const abC=cross(a,b,c),abD=cross(a,b,d);
  const cdA=cross(c,d,a),cdB=cross(c,d,b);
  const side=(v:number)=>v>tol?1:v< -tol?-1:0;
  const touches=(p:Position,q:Position,r:Position)=>
    r[0]>=Math.min(p[0],q[0])-scale*1e-12 &&
    r[0]<=Math.max(p[0],q[0])+scale*1e-12 &&
    r[1]>=Math.min(p[1],q[1])-scale*1e-12 &&
    r[1]<=Math.max(p[1],q[1])+scale*1e-12;
  if(side(abC)===0&&touches(a,b,c))return true;
  if(side(abD)===0&&touches(a,b,d))return true;
  if(side(cdA)===0&&touches(c,d,a))return true;
  if(side(cdB)===0&&touches(c,d,b))return true;
  return side(abC)!==side(abD)&&side(cdA)!==side(cdB);
}

const polygonMode=(mode:ShapeMode)=>mode==='polygon'||mode==='hole';
const maxSketchPoints=(mode:ShapeMode)=>mode==='point'?1:
  mode==='rectangle'||mode==='circle'||mode==='trace-along'?2:4000;

/** Returns a user-actionable reason instead of committing malformed geometry. */
export function sketchAddError(mode:ShapeMode,points:Position[],next:Position):string|null{
  if(!mode)return 'Select a drawing tool first.';
  if(!Number.isFinite(next[0])||!Number.isFinite(next[1])||
     Math.abs(next[0])>180||Math.abs(next[1])>90)
    return 'Add a finite longitude/latitude inside WGS84 bounds.';
  if(points.length>=maxSketchPoints(mode))return 'Maximum number of vertices reached. Finish the sketch.';
  if(points.length&&same(points[points.length-1],next))return 'Duplicate of the last point.';
  if(!polygonMode(mode))return null;
  if(points.some(p=>same(p,next)))return 'Use the first point to close the polygon. Other vertices cannot be repeated.';
  if(points.length<2)return null;
  const a=points[points.length-1];
  for(let i=0;i<points.length-2;i++){
    if(sketchSegmentsIntersect(a,next,points[i],points[i+1]))
      return 'New edge crosses or touches an existing polygon edge. Undo or choose another point.';
  }
  return null;
}

/** Includes closure intersection and zero-area checks. Does not silently repair invalid rings. */
export function sketchFinishError(mode:ShapeMode,points:Position[]):string|null{
  if(!mode)return 'Select a drawing tool first.';
  const required=mode==='point'?1:polygonMode(mode)?3:2;
  if(points.length<required)return 'Add '+(required-points.length)+' more point(s) to finish.';
  for(let i=0;i<points.length;i++){
    const error=sketchAddError(mode,points.slice(0,i),points[i]);
    if(error)return error;
  }
  if(!polygonMode(mode))return null;
  return sketchClosingError(points);
}

/** O(n) closing-edge verification; full O(n²) topology is checked on Finish. */
function sketchClosingError(points:Position[]):string|null{
  if(points.length<3)return 'At least three vertices are needed for polygon closure.';
  const start=points[0],end=points[points.length-1];
  if(same(start,end))return 'Do not repeat the starting coordinate; click its handle to close.';
  for(let i=1;i<points.length-2;i++){
    if(sketchSegmentsIntersect(end,start,points[i],points[i+1]))
      return 'Closing edge intersects the polygon. Move, undo or add a vertex before finishing.';
  }
  const bounds=points.reduce((acc,p)=>[
    Math.min(acc[0],p[0]),Math.min(acc[1],p[1]),
    Math.max(acc[2],p[0]),Math.max(acc[3],p[1]),
  ] as [number,number,number,number],[Infinity,Infinity,-Infinity,-Infinity] as [number,number,number,number]);
  if(bounds[2]-bounds[0]>170)return 'A polygon crossing the antimeridian needs a dedicated geographic construction.';
  const twiceArea=points.reduce((sum,a,i)=>{
    const b=points[(i+1)%points.length];
    return sum+(a[0]-start[0])*(b[1]-start[1])-(b[0]-start[0])*(a[1]-start[1]);
  },0);
  const scale=(bounds[2]-bounds[0])*(bounds[3]-bounds[1]);
  if(scale===0||Math.abs(twiceArea)<=scale*1e-12)
    return 'Polygon has zero area. Choose at least three non-collinear vertices.';
  return null;
}

/** A preview may be an open line but must never display a knowingly invalid closed polygon. */
export function canPreviewClosedSketch(mode:ShapeMode,points:Position[]):boolean{
  // Every inserted edge has already been checked by sketchAddError.
  // Checking only the new closing edge keeps mousemove at O(n), not O(n²).
  return polygonMode(mode)&&sketchClosingError(points)===null;
}
