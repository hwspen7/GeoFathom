import type {PersistedTerrainResult} from './terrainResultStore';
import type {ResearchExperiment,ResearchResult} from './api';

/** Convert historical human-readable receipts back to engine input keys. */
export function researchBase(record:PersistedTerrainResult):ResearchExperiment['base']{
 if(record.researchInput)return structuredClone(record.researchInput) as ResearchExperiment['base'];
 const aliases:Record<string,string>={contour_interval_m:'interval',section_spacing_m:'section_spacing',section_half_width_m:'section_width',reference_elevation_m:'reference',azimuth_deg:'azimuth',altitude_deg:'altitude',
  neighborhood_radius_cells:'neighborhood_radius',curvature_radius_cells:'curvature_radius',
  max_slope_deg:'max_slope',min_elevation_m:'min_elevation',max_elevation_m:'max_elevation',max_tri_m:'max_tri',
  min_stream_cells:'stream_cells',observer_height_m:'observer_height',target_height_m:'target_height',
  maximum_distance_m:'max_distance_m',view_azimuth_deg:'view_azimuth',view_width_deg:'view_width',refraction_coefficient:'refraction_coeff'};
 const parameters:Record<string,unknown>={};
 for(const [key,value] of Object.entries(record.parameters??{})){
  if(!['observer_longitude','observer_latitude','end_longitude','end_latitude','drape'].includes(key))
   parameters[aliases[key]??key]=value;
 }
 const p=record.parameters??{};
 if(p.observer_longitude!==undefined)parameters.point=[p.observer_longitude,p.observer_latitude];
 if(p.end_longitude!==undefined)parameters.end_point=[p.end_longitude,p.end_latitude];
 return {image_id:record.source.id,geometry:structuredClone(record.geometry),
  operation:record.operation==='slope'?'slope_map':record.operation,...parameters};
}

export function parseSweep(raw:string):number[]{
 const tokens=raw.split(',').map(x=>x.trim());
 const values=tokens.map(Number);
 if(tokens.some(x=>!x)||values.length<2||values.length>8||values.some(x=>!Number.isFinite(x))||new Set(values).size!==values.length)
  throw new Error('Enter two to eight distinct numbers, separated by commas.');
 return values;
}
export function parseParameter(raw:string):unknown{
 if(!raw.trim())throw new Error('Enter a parameter value.');
 if(raw==='true'||raw==='false')return raw==='true';
 if(Number.isFinite(Number(raw)))return Number(raw);
 if(raw.includes(',')){
  const values=raw.split(',').map(x=>x.trim());
  if(values.some(x=>!x||!Number.isFinite(Number(x))))throw new Error('Enter valid comma-separated numbers.');
  return values.map(Number);
 }
 return raw.trim();
}
export function downloadResearch(base64:string,filename:string,type:string){
 const bytes=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));
 const url=URL.createObjectURL(new Blob([bytes],{type}));
 const link=document.createElement('a');link.href=url;link.download=filename;link.click();
 window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}

// Large experiment outputs stay in IndexedDB; do not fill synchronous localStorage.
const database='geofathom-research-experiments';
function open():Promise<IDBDatabase>{return new Promise((resolve,reject)=>{
 const request=indexedDB.open(database,1);
 request.onupgradeneeded=()=>request.result.createObjectStore('experiments',{keyPath:'project'});
 request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
 });}
export async function saveResearch(projectId:string|null,input:ResearchExperiment,result:ResearchResult){
 if(JSON.stringify(result).length>60_000_000)throw new Error('Experiment is too large to cache. Download its research package before closing.');
 const db=await open();try{
  await new Promise<void>((resolve,reject)=>{
   const tx=db.transaction('experiments','readwrite');
   tx.objectStore('experiments').put({project:projectId??'local',input,result});
   tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);
  });
 }finally{db.close();}
}
export async function loadResearch(projectId:string|null):Promise<{input:ResearchExperiment;result:ResearchResult}|null>{
 const db=await open();try{return await new Promise((resolve,reject)=>{
  const request=db.transaction('experiments').objectStore('experiments').get(projectId??'local');
  request.onsuccess=()=>resolve(request.result??null);request.onerror=()=>reject(request.error);
 });}finally{db.close();}
}
