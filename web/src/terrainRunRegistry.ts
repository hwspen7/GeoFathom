import type {RasterAsset} from './api';
import {terrainGeometryBounds} from './terrainSource';
export interface TerrainRunReceipt{
 id:string;createdAt:number;operation:string;sourceId:string;sourceName:string;
 provenance:string;crs:string;grid:[number,number];
 sourceBounds:[number,number,number,number];
 studyBounds:[number,number,number,number]|null;
 sourceAcquiredAt:string|null;metrics:Record<string,number>;
 referenceSourceId?:string;referenceSourceName?:string;
 referenceCRS?:string;referenceAcquiredAt?:string|null;
}
const LIMIT=100;
const key=(projectId:string|null)=>'geofathom-terrain-run-history-v1:'+(projectId??'local');
export function summarizeTerrainRun(
 id:string,createdAt:number,operation:string,source:RasterAsset,
 geometry:GeoJSON.Geometry,metrics:Record<string,number>,reference?:RasterAsset,
):TerrainRunReceipt{
 const valid=Object.fromEntries(Object.entries(metrics)
   .filter(([,v])=>typeof v==='number'&&Number.isFinite(v)));
 return {id,createdAt,operation,sourceId:source.id,sourceName:source.name,
   provenance:source.provenance,crs:source.crs,grid:[source.width,source.height],
   sourceBounds:[...source.bbox],studyBounds:terrainGeometryBounds(geometry),
   sourceAcquiredAt:source.acquired_at,metrics:valid,
   ...(reference?{referenceSourceId:reference.id,referenceSourceName:reference.name,
     referenceCRS:reference.crs,referenceAcquiredAt:reference.acquired_at}:{})};
}
/** Preserve only compact scientific metadata, not base64 PNG/GeoTIFF payloads. */
export function insertTerrainRun(history:TerrainRunReceipt[],run:TerrainRunReceipt):TerrainRunReceipt[]{
 return [run,...history.filter(x=>x.id!==run.id)].slice(0,LIMIT);
}
export function readTerrainRuns(projectId:string|null):TerrainRunReceipt[]{
 try{
  const raw:unknown=JSON.parse(localStorage.getItem(key(projectId))||'[]');
  return Array.isArray(raw)?raw.filter((x):x is TerrainRunReceipt=>!!x&&
    typeof x==='object'&&typeof x.id==='string'&&
    typeof x.createdAt==='number'&&typeof x.operation==='string'&&
    typeof x.sourceId==='string'&&typeof x.sourceName==='string'&&
    x.metrics!==null&&typeof x.metrics==='object').slice(0,LIMIT):[];
 }catch{return [];}
}
export function writeTerrainRuns(projectId:string|null,runs:TerrainRunReceipt[]):boolean{
 try{localStorage.setItem(key(projectId),JSON.stringify(runs.slice(0,LIMIT)));return true;}
 catch{return false;}
}
