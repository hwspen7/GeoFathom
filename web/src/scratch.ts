import {approximateMeasurement,pathsOf,geodesicDrag,drawingPreview,type Position,type ShapeMode} from './editing';
import type {Measurement} from './api';
export interface ScratchFeature {id:string;name:string;geometry:GeoJSON.Geometry;measurement:Measurement;visible:boolean;source?:string;properties?:Record<string,unknown>}
const KEY='geofathom-scratch-v1';
export const SCRATCH_LIMIT=200;
export const OFFLINE_METHOD='Local spherical estimate (not ellipsoidal validation)';
const equal=(a:Position,b:Position)=>a[0]===b[0]&&a[1]===b[1];
function intersection(a:Position,b:Position,c:Position,d:Position):boolean{
  const cross=(p:Position,q:Position,r:Position)=>(q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0]);
  const on=(p:Position,q:Position,r:Position)=>r[0]>=Math.min(p[0],q[0])&&r[0]<=Math.max(p[0],q[0])&&r[1]>=Math.min(p[1],q[1])&&r[1]<=Math.max(p[1],q[1]);
  const x=cross(a,b,c),y=cross(a,b,d),z=cross(c,d,a),w=cross(c,d,b);
  return ((x>0&&y<0||x<0&&y>0)&&(z>0&&w<0||z<0&&w>0))||x===0&&on(a,b,c)||y===0&&on(a,b,d)||z===0&&on(c,d,a)||w===0&&on(c,d,b);
}
/** Offline drafts support simple local shapes. Server validation remains
 * mandatory for authoritative project storage. */
export function localMeasurement(g:GeoJSON.Geometry):Measurement{
  if(!['Point','LineString','Polygon'].includes(g.type))throw Error('Complex geometry requires the connected GIS backend.');
  if(g.type==='Polygon'&&g.coordinates.length!==1)throw Error('Polygon holes require backend validation.');
  const paths=g.type==='Point'?[[g.coordinates as Position]]:pathsOf(g),points=paths.flat();
  if(!points.length||points.length>4001||points.some(p=>p.length!==2||!p.every(Number.isFinite)||Math.abs(p[0])>180||Math.abs(p[1])>=85))
    throw Error('Invalid local geometry coordinates.');
  const bounds=[Infinity,Infinity,-Infinity,-Infinity];
  for(const pt of points){bounds[0]=Math.min(bounds[0],pt[0]);bounds[1]=Math.min(bounds[1],pt[1]);bounds[2]=Math.max(bounds[2],pt[0]);bounds[3]=Math.max(bounds[3],pt[1]);}
  if(bounds[2]-bounds[0]>170)throw Error('Antimeridian geometry requires the GIS backend.');
  if(g.type!=='Point'){
    const ring=paths[0],n=ring.length;
    if(n<(g.type==='Polygon'?4:2))throw Error('Not enough vertices.');
    for(let i=1;i<n;i++)if(equal(ring[i],ring[i-1]))throw Error('Duplicate adjacent vertices.');
    if(g.type==='Polygon'){
      if(!equal(ring[0],ring[n-1]))throw Error('Polygon is not closed.');
      for(let i=0;i<n-1;i++)for(let j=i+2;j<n-1;j++){
        if(i===0&&j===n-2)continue;
        if(intersection(ring[i],ring[i+1],ring[j],ring[j+1]))throw Error('Polygon edges intersect. Remove or move a vertex.');
      }
    }
  }
  const totals=approximateMeasurement(g);
  if(g.type==='Polygon'&&!(totals.area_m2&&totals.area_m2>0))throw Error('Polygon has zero area.');
  if(g.type==='LineString'&&!(totals.length_m&&totals.length_m>0))throw Error('Line has zero length.');
  const edges:number[]=[];
  for(const path of paths)for(let i=1;i<path.length&&edges.length<48;i++)edges.push(geodesicDrag(path[i-1],path[i]).distance_m);
  return {...totals,geometry_type:g.type,area_km2:totals.area_m2===null?null:totals.area_m2/1e6,bounds,
    coordinate_count:points.length,edge_lengths_m:edges,method:OFFLINE_METHOD,note:'Unverified local scratch geometry; connect the backend for exact validation.'};
}
export function localShape(mode:ShapeMode,points:Position[]){
  if(!mode||!['point','line','rectangle','circle','polygon'].includes(mode))return null;
  if(points.length<(mode==='point'?1:mode==='polygon'?3:2))return null;
  const geometry=drawingPreview(mode,points);
  if(!geometry||((mode==='circle'||mode==='rectangle')&&geometry.type!=='Polygon'))throw Error('Invalid or oversized shape.');
  return {geometry,measurement:localMeasurement(geometry)};
}
export function readScratch():ScratchFeature[]{
  try{const value:unknown=JSON.parse(localStorage.getItem(KEY)||'[]');
    if(!Array.isArray(value))return [];
    return value.slice(0,SCRATCH_LIMIT).filter(f=>f&&typeof f.id==='string'&&f.id.startsWith('scratch-')&&typeof f.name==='string'&&typeof f.visible==='boolean'&&f.geometry&&f.measurement&&Array.isArray(f.measurement.bounds));
  }catch{return [];}
}
export function writeScratch(features:ScratchFeature[]):boolean{
  try{localStorage.setItem(KEY,JSON.stringify(features));return true;}catch{return false;}
}
