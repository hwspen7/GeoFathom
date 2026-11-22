/** Browser-local, project-isolated cache for complete Terrain output.
 *
 * Metadata receipts remain in localStorage, but the full raster, sections,
 * profile and mesh payloads live in IndexedDB. This cache is not a substitute
 * for exporting a scientific dataset or a portable project archive.
 */
import type {AdvancedTerrainResult,RasterAsset,TerrainOperation,TerrainResult} from './api';

export interface PersistedTerrainResult {
 id:string;title:string;operation:TerrainOperation|'slope'|'profile';
 source:RasterAsset;referenceSource?:RasterAsset;geometry:GeoJSON.Geometry;
 inputKey:string;visible:boolean;createdAt:number;saved?:boolean;opacity:number;
 resampling:'nearest'|'linear';
 advanced?:AdvancedTerrainResult;slope?:TerrainResult;
 profile?:{samples:Array<{distance_m:number;elevation_m:number|null;coordinate:number[]}>;length_m:number;source_crs:string;vertical_unit:string;warning:string};
}

interface IndexedResult extends PersistedTerrainResult {projectKey:string}
const DB_NAME='geofathom-terrain-output-cache';
const DB_VERSION=1;
const STORE='results';
const LIMIT=24;
// Keep single writes bounded. Large products remain exportable during the
// current session, but cannot silently exhaust the entire browser quota.
const MAX_RECORD_CHARACTERS=40_000_000;

const projectKey=(id:string|null)=>id?'project:'+id:'scratch';
let opening:Promise<IDBDatabase>|null=null;

function openDatabase():Promise<IDBDatabase>{
 if(opening)return opening;
 opening=new Promise<IDBDatabase>((resolve,reject)=>{
  if(typeof indexedDB==='undefined'){
   reject(new Error('IndexedDB is unavailable in this browser.'));
   return;
  }
  const request=indexedDB.open(DB_NAME,DB_VERSION);
  request.onupgradeneeded=()=>{
   const db=request.result;
   if(!db.objectStoreNames.contains(STORE)){
    const store=db.createObjectStore(STORE,{keyPath:['projectKey','id']});
    store.createIndex('by_project','projectKey',{unique:false});
   }
  };
  request.onsuccess=()=>{
   const db=request.result;
   db.onversionchange=()=>{db.close();opening=null;};
   resolve(db);
  };
  request.onerror=()=>reject(request.error??new Error('Unable to open Terrain result cache.'));
  request.onblocked=()=>reject(new Error('The Terrain cache is open in another tab. Close older tabs and retry.'));
 }).catch(error=>{opening=null;throw error;});
 return opening;
}

function completed(transaction:IDBTransaction):Promise<void>{
 return new Promise((resolve,reject)=>{
  transaction.oncomplete=()=>resolve();
  transaction.onerror=()=>reject(transaction.error??new Error('Terrain cache transaction failed.'));
  transaction.onabort=()=>reject(transaction.error??new Error('Terrain cache transaction was aborted.'));
 });
}

function validResult(value:unknown):value is IndexedResult{
 if(!value||typeof value!=='object')return false;
 const r=value as Partial<IndexedResult>;
 return typeof r.id==='string'&&typeof r.title==='string'&&
  typeof r.operation==='string'&&typeof r.createdAt==='number'&&
  Number.isFinite(r.createdAt)&&!!r.source&&typeof r.source.id==='string'&&
  !!r.geometry&&typeof r.geometry.type==='string'&&
  typeof r.inputKey==='string'&&
  (!!r.advanced||!!r.slope||!!r.profile);
}

export async function loadTerrainResults(projectId:string|null):Promise<PersistedTerrainResult[]>{
 const db=await openDatabase();
 const tx=db.transaction(STORE,'readonly');
 const done=completed(tx);
 const request=tx.objectStore(STORE).index('by_project').getAll(projectKey(projectId));
 const result=await new Promise<unknown[]>((resolve,reject)=>{
  request.onsuccess=()=>resolve(request.result as unknown[]);
  request.onerror=()=>reject(request.error??new Error('Terrain result cache read failed.'));
 });
 await done;
 // Restored results are hidden until explicitly enabled. This avoids drawing
 // outdated derived layers over a changed map or a newly selected source.
 return result.filter(validResult).sort((a,b)=>b.createdAt-a.createdAt)
  .slice(0,LIMIT).map(({projectKey:_key,...record})=>({...record,visible:false}));
}

export async function cacheTerrainResult(projectId:string|null,record:PersistedTerrainResult):Promise<void>{
 if(!validResult(record))throw new Error('Cannot cache an incomplete Terrain analysis result.');
 const copy:IndexedResult={...record,projectKey:projectKey(projectId),visible:false};
 // A simple bound makes storage failure explicit. Scientific data is not
 // truncated or downsampled merely to fit a cache.
 if(JSON.stringify(copy).length>MAX_RECORD_CHARACTERS)
  throw new Error('Terrain result is too large for the browser cache; export the GeoTIFF or result data.');
 const db=await openDatabase();
 const tx=db.transaction(STORE,'readwrite');
 const done=completed(tx);
 tx.objectStore(STORE).put(copy);
 await done;
}

export async function deleteTerrainResult(projectId:string|null,id:string):Promise<void>{
 const db=await openDatabase();
 const tx=db.transaction(STORE,'readwrite');
 const done=completed(tx);
 tx.objectStore(STORE).delete([projectKey(projectId),id]);
 await done;
}

export async function markTerrainResultSaved(projectId:string|null,id:string):Promise<void>{
 const db=await openDatabase();
 const tx=db.transaction(STORE,'readwrite');
 const done=completed(tx);
 const store=tx.objectStore(STORE);
 const request=store.get([projectKey(projectId),id]);
 request.onsuccess=()=>{
  const result=request.result as IndexedResult|undefined;
  if(result)store.put({...result,saved:true});
 };
 await done;
}
