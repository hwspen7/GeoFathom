import {useEffect,useRef,useState,type ChangeEvent} from 'react';
import {Mountain} from 'lucide-react';
import {advancedTerrain,saveFeatureBatch,analyzeTerrain,terrainProfile,listImagery,uploadImagery,fetchPublicDEM,type TerrainResult,type TerrainMesh,type TerrainOperation,type AdvancedTerrainResult,type RasterAsset,type TerrainRasterLayer} from './api';
import {ProfilePlot,MetricBars,ElevationDistribution,AspectRose,SectionPlot,ResultPane} from './TerrainCharts';
import {GPUView} from './TerrainMeshView';
import type {Position} from './editing';
import {measurementAnchor} from './editing';

function MeshView({mesh}:{mesh:TerrainMesh}){
  const canvas=useRef<HTMLCanvasElement>(null);
  const [angle,setAngle]=useState(-.6);
  const [tilt,setTilt]=useState(.9);
  const [exaggeration,setExaggeration]=useState(1);
  const drag=useRef<{x:number;y:number}|null>(null);
  useEffect(()=>{
    const node=canvas.current,ctx=node?.getContext('2d');if(!node||!ctx)return;
    const valid=mesh.heights.filter((v):v is number=>v!==null);
    if(!valid.length)return;
    const lo=Math.min(...valid),hi=Math.max(...valid);
    const span=Math.max(mesh.cols*mesh.dx_m,mesh.rows*mesh.dy_m,(hi-lo)*exaggeration,1);
    const scale=260/span;
    const project=(r:number,c:number)=> {
      const h=mesh.heights[r*mesh.cols+c];
      if(h===null)return null;
      const x=(c-(mesh.cols-1)/2)*mesh.dx_m,y=(r-(mesh.rows-1)/2)*mesh.dy_m;
      const xx=x*Math.cos(angle)-y*Math.sin(angle),yy=x*Math.sin(angle)+y*Math.cos(angle);
      const z=(h-(hi+lo)/2)*exaggeration;
      return {x:160+xx*scale,y:108+(yy*Math.cos(tilt)-z*Math.sin(tilt))*scale,depth:yy*Math.sin(tilt)+z*Math.cos(tilt),h};
    };
    const cells:Array<{points:Array<NonNullable<ReturnType<typeof project>>>;depth:number;h:number}>=[];
    for(let r=0;r+1<mesh.rows;r++)for(let c=0;c+1<mesh.cols;c++){
      const p=[project(r,c),project(r,c+1),project(r+1,c+1),project(r+1,c)];
      if(p.some(v=>v===null))continue;
      const q=p as Array<NonNullable<ReturnType<typeof project>>>;
      cells.push({points:q,depth:q.reduce((sum,v)=>sum+v.depth,0)/4,h:q.reduce((sum,v)=>sum+v.h,0)/4});
    }
    ctx.fillStyle='#edf2f5';ctx.fillRect(0,0,320,220);
    cells.sort((a,b)=>b.depth-a.depth);
    for(const cell of cells){
      ctx.beginPath();cell.points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.closePath();
      const ratio=(cell.h-lo)/(hi-lo||1);
      ctx.fillStyle='hsl('+(120-95*ratio)+' 38% '+(35+30*ratio)+'%)';
      ctx.fill();ctx.strokeStyle='#203a3b45';ctx.lineWidth=.4;ctx.stroke();
    }
  },[mesh,angle,tilt,exaggeration]);
  return <div className="dem-mesh">
    <canvas ref={canvas} width={320} height={220} aria-label="Interactive 3D terrain preview"
      onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);drag.current={x:e.clientX,y:e.clientY};}}
      onPointerMove={e=>{if(!drag.current)return;const dx=e.clientX-drag.current.x,dy=e.clientY-drag.current.y;
        setAngle(a=>a+dx*.012);setTilt(t=>Math.max(.2,Math.min(1.45,t+dy*.008)));drag.current={x:e.clientX,y:e.clientY};}}
      onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}/>
    <label>Vertical exaggeration <input aria-label="Terrain vertical exaggeration" type="range" min="1" max="5" step=".5"
      value={exaggeration} onChange={e=>setExaggeration(Number(e.target.value))}/></label>
    <div className="survey-action-bar"><small>Drag to rotate · elevations in meters</small><button onClick={()=>{setAngle(-.6);setTilt(.9);setExaggeration(1);}}>Reset view</button></div>
  </div>;
}

type Operation=TerrainOperation|'slope'|'profile';
type ProfileResult=Awaited<ReturnType<typeof terrainProfile>>;
interface TerrainRecord {
 id:string;title:string;operation:Operation;source:RasterAsset;geometry:GeoJSON.Geometry;
 inputKey:string;visible:boolean;createdAt:number;saved?:boolean;
 advanced?:AdvancedTerrainResult;slope?:TerrainResult;profile?:ProfileResult;
}
const modes:Array<{id:Operation;title:string}>=[
 {id:'slope',title:'Slope / aspect'},{id:'profile',title:'Elevation profile'},{id:'contours',title:'Contours'},
 {id:'volume',title:'Cut / fill'},{id:'visibility',title:'Viewshed'},{id:'watershed',title:'Watershed (D8)'},{id:'mesh',title:'3D terrain'},
 {id:'distribution',title:'Elevation distribution'},
 {id:'elevation',title:'Elevation map'},{id:'slope_map',title:'Slope map'},{id:'aspect_map',title:'Aspect map'},{id:'hillshade',title:'Hillshade'},
 {id:'tri',title:'Ruggedness (TRI)'},{id:'tpi',title:'Position (TPI)'},{id:'curvature',title:'Curvature (Laplacian)'},
 {id:'flow_direction',title:'Flow direction'},{id:'flow_accumulation',title:'Flow accumulation'},{id:'streams',title:'Drainage network'},
 {id:'cutfill_map',title:'Cut / fill map'},{id:'suitability',title:'Site suitability'},{id:'least_cost',title:'Least-cost route'},{id:'cross_sections',title:'Cross sections'}
];
const units:Record<string,string>={cut_m3:'m³',fill_m3:'m³',net_cut_m3:'m³',covered_grid_area_m2:'m²',reference_elevation_m:'m',
 contour_lines:'',contour_levels:'',dataset_overlap_pct:'%',valid_grid_pct:'%',interval_m:'m',visible_cells:'',visible_grid_area_m2:'m²',unknown_cells:'',upstream_cells:'',upstream_grid_area_m2:'m²',minimum_m:'m',maximum_m:'m',mean_m:'m',median_m:'m',stddev_m:'m',p10_m:'m',p90_m:'m',relief_m:'m'};
const names:Record<string,string>={cut_m3:'Cut',fill_m3:'Fill',net_cut_m3:'Net cut',covered_grid_area_m2:'Grid area',reference_elevation_m:'Reference',
 contour_lines:'Contour paths',contour_levels:'Elevation levels',dataset_overlap_pct:'DEM footprint coverage',valid_grid_pct:'Valid grid coverage',interval_m:'Interval',visible_cells:'Visible cells',visible_grid_area_m2:'Visible area',unknown_cells:'Unknown cells',
 upstream_cells:'Upstream cells',upstream_grid_area_m2:'Catchment area',minimum_m:'Lowest elevation',maximum_m:'Highest elevation',mean_m:'Mean elevation',median_m:'Median elevation',stddev_m:'Standard deviation',p10_m:'10th percentile',p90_m:'90th percentile',relief_m:'Relief',hypsometric_integral:'Hypsometric integral'};
const fmt=(n:number)=>n.toLocaleString('en-US',{maximumFractionDigits:2});
interface Props{
 projectId:string|null;geometry:GeoJSON.Geometry|null;raster:RasterAsset|null;imageRaster?:RasterAsset|null;active:boolean;connected:boolean;
 viewport:[number,number,number,number]|null;
 localImport:boolean;refreshToken:number;origin:Position|null;picking:boolean;
 onSelectRaster:(r:RasterAsset)=>void;onDraw:(line:boolean)=>void;onUseExtent:()=>void;onPick:()=>void;
 extentMode:boolean;onUseSelection:()=>void;
 onHover:(point:Position|null)=>void;onPreview:(g:GeoJSON.Feature[])=>void;onRasterPreview?:(layers:TerrainRasterLayer[])=>void;onSaved:()=>void;
}
export default function TerrainWorkbench(p:Props){
 // Opening Terrain never preselects a calculation.
 const [operation,setOperation]=useState<Operation|null>(null);
 const [assets,setAssets]=useState<RasterAsset[]>([]),[token,setToken]=useState('');
 const [resolution,setResolution]=useState<1|3|10|30|90>(30),[fetching,setFetching]=useState(false),[sourceInfo,setSourceInfo]=useState('');
 const [interval,setInterval]=useState('10'),[reference,setReference]=useState('0');
 const [lon,setLon]=useState(''),[lat,setLat]=useState(''),[height,setHeight]=useState('1.7'),[target,setTarget]=useState('0');
 const [endLon,setEndLon]=useState(''),[endLat,setEndLat]=useState('');
 const [maxSlope,setMaxSlope]=useState('30'),[minElevation,setMinElevation]=useState('-12000'),[maxElevation,setMaxElevation]=useState('12000'),[maxTri,setMaxTri]=useState('100');
 const [streamCells,setStreamCells]=useState('100'),[azimuth,setAzimuth]=useState('315'),[altitude,setAltitude]=useState('45');
 const [sectionSpacing,setSectionSpacing]=useState('50'),[sectionWidth,setSectionWidth]=useState('20'),[drape,setDrape]=useState(false),[expanded,setExpanded]=useState(false);
 const [pickEnd,setPickEnd]=useState(false);
 const [records,setRecords]=useState<TerrainRecord[]>([]);
 const [selectedRecord,setSelectedRecord]=useState<string|null>(null);
 const selected=records.find(r=>r.id===selectedRecord);
 const result=selected?.advanced??null,slope=selected?.slope??null,profile=selected?.profile??null;
 const analysisRequest=useRef<AbortController|null>(null);
 const alive=useRef(true);
 const sourceIntent=useRef(0);
 const [verticalConfirmed,setVerticalConfirmed]=useState(false);
 const [live,setLive]=useState(false),[busy,setBusy]=useState(false),[importing,setImporting]=useState(false);
 const [error,setError]=useState(''),[info,setInfo]=useState('');
 const sequence=useRef(0),latest=useRef(p);latest.current=p;
 const area=p.geometry?.type==='Polygon'||p.geometry?.type==='MultiPolygon';
 const needsPoint=operation==='watershed'||operation==='visibility'||operation==='least_cost';
 const lineOperation=operation==='profile'||operation==='cross_sections';
 const correctShape=lineOperation?p.geometry?.type==='LineString':area;
 const dem=p.raster?.bands===1?p.raster:null;
 const verified=!!dem&&(/Copernicus DEM GLO-|USGS 3DEP Bare Earth DEM/.test(dem.provenance)||verticalConfirmed);
 const validNumber=(value:string,min:number,max:number)=>value.trim()!==''&&Number.isFinite(Number(value))&&Number(value)>=min&&Number(value)<=max;
 const parametersValid=(operation!=='cross_sections'||validNumber(sectionSpacing,1,10000)&&validNumber(sectionWidth,1,2000))&&
   (operation!=='contours'||validNumber(interval,.01,1e6))&&
   ((operation!=='volume'&&operation!=='cutfill_map')||validNumber(reference,-12000,12000))&&
   (operation!=='least_cost'||validNumber(endLon,-180,180)&&validNumber(endLat,-90,90)&&validNumber(maxSlope,.01,90))&&
   (operation!=='suitability'||validNumber(maxSlope,0,90)&&validNumber(minElevation,-12000,12000)&&validNumber(maxElevation,-12000,12000)&&Number(minElevation)<=Number(maxElevation)&&validNumber(maxTri,0,100000))&&
   (operation!=='streams'||validNumber(streamCells,1,1000000)&&Number.isInteger(Number(streamCells)))&&
   (operation!=='hillshade'||validNumber(azimuth,0,360)&&validNumber(altitude,0,90))&&
   (!needsPoint||validNumber(lon,-180,180)&&validNumber(lat,-90,90))&&
   (operation!=='visibility'||validNumber(height,0,1000)&&validNumber(target,0,1000));
 const canRun=operation!==null&&p.connected&&verified&&!!correctShape&&parametersValid;
 const inputKey=JSON.stringify([dem?.id,p.geometry,operation,interval,reference,lon,lat,height,target,endLon,endLat,maxSlope,minElevation,maxElevation,maxTri,streamCells,azimuth,altitude,sectionSpacing,sectionWidth,drape,drape?p.imageRaster?.id:null]);
 const inputsChanged=!!selected&&selected.inputKey!==inputKey;
 useEffect(()=>{setVerticalConfirmed(false);sourceIntent.current++;},[dem?.id]);
 // Published result layers are independent from the currently selected input.
 useEffect(()=>{latest.current.onPreview(records.filter(r=>r.visible).flatMap(r=>r.advanced?.features??[]));latest.current.onRasterPreview?.(records.flatMap(r=>r.visible&&r.advanced?.raster?[{id:r.id,raster:r.advanced.raster}]:[]));},[records]);
 useEffect(()=>{
   if(!p.active||!p.connected)return;
   let current=true;
   listImagery().then(list=>{if(current)setAssets(list.filter(a=>a.bands===1));})
     .catch(e=>{if(current)setError(e instanceof Error?e.message:String(e));});
   return()=>{current=false;};
 },[p.active,p.connected,p.refreshToken]);
 useEffect(()=>{if(p.origin){if(pickEnd){setEndLon(String(p.origin[0]));setEndLat(String(p.origin[1]));setPickEnd(false);}else{setLon(String(p.origin[0]));setLat(String(p.origin[1]));}}},[p.origin]);
 function cancelAnalysis(){
   sequence.current++;analysisRequest.current?.abort();analysisRequest.current=null;setBusy(false);
 }
 async function run(){
   if(!operation||!canRun||!dem||!p.geometry||busy)return;
   if(records.length>=24&&!records.some(r=>r.inputKey===inputKey&&!r.saved)){
     setLive(false);setError('Result limit reached (24). Export or remove a result before another calculation.');return;
   }
   // A live run replaces only the previous run with identical input, never
   // hidden or historical results from different source geometry.
   analysisRequest.current?.abort();
   const controller=new AbortController();analysisRequest.current=controller;
   const ticket=++sequence.current;setBusy(true);setError('');setInfo('');
   const record:TerrainRecord={id:crypto.randomUUID(),title:modes.find(m=>m.id===operation)!.title,
     operation,source:dem,geometry:structuredClone(p.geometry),inputKey,visible:true,createdAt:Date.now()};
   try{
     if(operation==='profile')record.profile=await terrainProfile(dem.id,p.geometry,controller.signal);
     else if(operation==='slope')record.slope=await analyzeTerrain(dem.id,p.geometry,controller.signal);
     else record.advanced=await advancedTerrain({image_id:dem.id,geometry:p.geometry,operation,
       interval:Number(interval),reference:Number(reference),point:needsPoint?[Number(lon),Number(lat)]:null,
       observer_height:Number(height),target_height:Number(target),end_point:operation==='least_cost'?[Number(endLon),Number(endLat)]:null,
       max_slope:Number(maxSlope),min_elevation:Number(minElevation),max_elevation:Number(maxElevation),max_tri:Number(maxTri),stream_cells:Number(streamCells),azimuth:Number(azimuth),altitude:Number(altitude),section_spacing:Number(sectionSpacing),section_width:Number(sectionWidth),texture_image_id:operation==='mesh'&&drape?p.imageRaster?.id??null:null},controller.signal);
     if(ticket!==sequence.current||controller.signal.aborted)return;
     setRecords(old=>{
       const kept=old.filter(r=>r.inputKey!==inputKey||r.saved);
       return [...kept,record];
     });
     setSelectedRecord(record.id);latest.current.onHover(null);
   }catch(e){if(ticket===sequence.current&&!controller.signal.aborted)setError(e instanceof Error?e.message:'Terrain analysis failed.');}
   finally{if(ticket===sequence.current){setBusy(false);analysisRequest.current=null;}}
 }
 useEffect(()=>{
   cancelAnalysis();setError('');setInfo('');latest.current.onHover(null);
   if(!live||!canRun||!p.active)return;
   const timer=window.setTimeout(()=>void run(),450);
   return()=>{window.clearTimeout(timer);sequence.current++;analysisRequest.current?.abort();};
 },[inputKey,live,p.connected,p.active,verified]);
 useEffect(()=>{
   alive.current=true;
   return()=>{alive.current=false;sequence.current++;sourceIntent.current++;analysisRequest.current?.abort();};
 },[]);
 async function importDEM(e:ChangeEvent<HTMLInputElement>){
   const file=e.target.files?.[0];e.target.value='';if(!file)return;
   const ticket=++sourceIntent.current;
   setImporting(true);setError('');
   try{
     if(!p.localImport&&!token.trim())throw Error('Enter import access token.');
     const item=await uploadImagery(file,token);
     if(!alive.current||ticket!==sourceIntent.current)return;
     if(item.bands!==1)throw Error('Select a single-band DEM, not RGB imagery.');
     setAssets(old=>[item,...old.filter(v=>v.id!==item.id)]);
     latest.current.onSelectRaster(item);
   }catch(e){if(alive.current&&ticket===sourceIntent.current)setError(e instanceof Error?e.message:String(e));}
   finally{if(alive.current)setImporting(false);}
 }
 async function fetchDEM(){
   if(!p.connected||fetching||importing)return;
   let bbox=p.viewport;
   if(p.geometry){
     const points=p.geometry.type==='LineString'?p.geometry.coordinates:p.geometry.type==='Polygon'?p.geometry.coordinates.flat():p.geometry.type==='MultiPolygon'?p.geometry.coordinates.flat(2):null;
     if(points?.length){
       const lon=points.map(pt=>pt[0]),lat=points.map(pt=>pt[1]);
       const w=Math.min(...lon),s=Math.min(...lat),e=Math.max(...lon),n=Math.max(...lat);
       bbox=[w-.0004,s-.0004,e+.0004,n+.0004];
     }
   }
   if(!bbox)return;
   const ticket=++sourceIntent.current;
   setFetching(true);setError('');setSourceInfo('');
   try{
     if(!p.localImport&&!token.trim())throw Error('Enter import access token.');
     const data=await fetchPublicDEM(bbox,resolution,token);
     if(!alive.current||ticket!==sourceIntent.current)return;
     setAssets(old=>[data.asset,...old.filter(item=>item.id!==data.asset.id)]);
     latest.current.onSelectRaster(data.asset);
     setSourceInfo((resolution<30?'USGS 3DEP · requested '+resolution+' m grid':'GLO-'+resolution+' · DSM')+' · '+data.valid_cells+'/'+data.total_cells+' cells'+(data.missing_tiles.length?' · partial coverage':''));
   }catch(e){if(alive.current&&ticket===sourceIntent.current)setError(e instanceof Error?e.message:String(e));}
   finally{if(alive.current)setFetching(false);}
 }
 async function save(){
   if(!p.projectId||!selected||selected.saved||busy||!result||result.features.length>512)return;
   const ticket=sequence.current;setBusy(true);setError('');
   const source=selected.source;
   try{
     const saved=await saveFeatureBatch(p.projectId,result.features.map((f,i)=>({
       geometry:f.geometry,name:String(f.properties.name||result.operation)+' '+(i+1),
       source:'DEM '+source.name,properties:{...f.properties,source_image:source.id,operation:result.operation}
     })));
     if(alive.current){setRecords(old=>old.map(r=>r.id===selected.id?{...r,saved:true}:r));latest.current.onSaved();if(ticket===sequence.current)setInfo('Saved '+saved.created+' terrain features.');}
   }catch(e){if(ticket===sequence.current)setError(e instanceof Error?e.message:'Save failed.');}
   finally{if(ticket===sequence.current)setBusy(false);}
 }
 function exportResult(){
   const payload=result?.features.length?{type:'FeatureCollection',features:result.features}:result??slope??profile;
   if(!payload)return;
   const link=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
   link.href=url;link.download='terrain-'+(selected?.operation??operation)+(result?.features.length?'.geojson':'.json');link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 return <div className="terrain-workbench professional-panel">
   <div className="terrain-source">
     <label>Elevation layer<select aria-label="DEM elevation layer" value={dem?.id??''}
       disabled={fetching||importing}
       onChange={e=>{const found=assets.find(item=>item.id===e.target.value);if(found){sourceIntent.current++;p.onSelectRaster(found);}}}>
       <option value="">Select DEM</option>
       {[...assets,...(dem&&!assets.some(a=>a.id===dem.id)?[dem]:[])].map(asset=><option key={asset.id} value={asset.id}>{asset.name}</option>)}
     </select></label>
     {!p.localImport&&<details className="access-settings"><summary>Import access</summary><input type="password" aria-label="DEM import token" value={token} onChange={e=>setToken(e.target.value)}/></details>}
     <label className="raster-upload" title="Single-band DEM GeoTIFF, projected in meters, with meter elevations"><Mountain size={14}/> {importing?'Importing…':'Import DEM'}
       <input type="file" aria-label="Import DEM" accept=".tif,.tiff" disabled={importing||fetching||!p.connected} onChange={e=>void importDEM(e)}/></label>
     <div className="area-fields">
       <select aria-label="Public DEM resolution" value={resolution} onChange={e=>setResolution(Number(e.target.value) as 1|3|10|30|90)}><option value={30}>GLO-30 · 30 m</option><option value={90}>GLO-90 · 90 m</option><option value={10}>USGS 3DEP · 10 m grid</option><option value={3}>USGS 3DEP · 3 m grid</option><option value={1}>USGS 3DEP · 1 m grid</option></select>
       <button disabled={!p.connected||!p.viewport||fetching||importing} title="Download a real elevation grid for the selected area" onClick={()=>void fetchDEM()}>{fetching?'Fetching…':'Fetch DEM'}</button>
     </div>
     {sourceInfo&&<small className="compact-notice" title="Copernicus is DSM; 3DEP is bare-earth DEM. Requested grid size is not native resolution.">{sourceInfo}</small>}
     {dem&&<small className="compact-notice" title={dem.provenance}>{dem.width} × {dem.height} · {dem.crs} · elevation m</small>}
     {dem&&!/Copernicus DEM GLO-|USGS 3DEP Bare Earth DEM/.test(dem.provenance)&&<label className="gis-check"><input aria-label="Confirm DEM meter elevations" type="checkbox" checked={verticalConfirmed} onChange={e=>setVerticalConfirmed(e.target.checked)}/> Confirm single-band meter elevations</label>}
   </div>
   <div className="terrain-command-grid" aria-label="Terrain tools">
     {modes.map(mode=><button key={mode.id} type="button" aria-pressed={operation===mode.id} onClick={()=>{setOperation(old=>old===mode.id?null:mode.id);if(operation===mode.id)setLive(false);}}>{mode.title}</button>)}
   </div>
   <select aria-label="Advanced terrain operation" className="visually-hidden" tabIndex={-1} value={operation??''} onChange={e=>setOperation(e.target.value?e.target.value as Operation:null)}>
     <option value="">Select operation</option>
     {modes.map(mode=><option key={mode.id} value={mode.id}>{mode.title}</option>)}
   </select>
   {operation&&<div className="professional-form">
     <div className="survey-action-bar">
       <button onClick={()=>p.onDraw(lineOperation)}>{lineOperation?'Draw profile line':'Draw study area'}</button>
       {!lineOperation&&<button disabled={!dem} aria-pressed={p.extentMode} onClick={p.onUseExtent}>DEM extent</button>}
       {p.extentMode&&<button onClick={p.onUseSelection}>Use selection</button>}
     </div>
     <small className="compact-notice">{correctShape?(p.extentMode?'✓ DEM footprint':'✓ Geometry selected'):lineOperation?'Select or draw a line':'Select or draw a polygon'}</small>
     {operation==='contours'&&<label>Interval (m)<input aria-label="Contour interval" type="number" min=".01" step="any" value={interval} onChange={e=>setInterval(e.target.value)}/></label>}
     {(operation==='volume'||operation==='cutfill_map')&&<label>Reference elevation (m)<input aria-label="Reference elevation" type="number" step="any" value={reference} onChange={e=>setReference(e.target.value)}/></label>}
     {operation==='cross_sections'&&<div className="area-fields"><label>Station spacing (m)<input type="number" value={sectionSpacing} onChange={e=>setSectionSpacing(e.target.value)}/></label><label>Half-width (m)<input type="number" value={sectionWidth} onChange={e=>setSectionWidth(e.target.value)}/></label></div>}
     {operation==='mesh'&&p.imageRaster&&p.imageRaster.bands>=3&&<label className="gis-check"><input type="checkbox" checked={drape} onChange={e=>setDrape(e.target.checked)}/> Drape selected RGB imagery</label>}
     {operation==='hillshade'&&<div className="area-fields"><label>Sun azimuth (°)<input type="number" value={azimuth} onChange={e=>setAzimuth(e.target.value)}/></label><label>Sun altitude (°)<input type="number" value={altitude} onChange={e=>setAltitude(e.target.value)}/></label></div>}
     {operation==='streams'&&<label>Minimum upstream cells<input type="number" min="1" step="1" value={streamCells} onChange={e=>setStreamCells(e.target.value)}/></label>}
     {(operation==='suitability'||operation==='least_cost')&&<label>Maximum slope (°)<input type="number" value={maxSlope} onChange={e=>setMaxSlope(e.target.value)}/></label>}
     {operation==='suitability'&&<><div className="area-fields"><label>Min elevation (m)<input type="number" value={minElevation} onChange={e=>setMinElevation(e.target.value)}/></label><label>Max elevation (m)<input type="number" value={maxElevation} onChange={e=>setMaxElevation(e.target.value)}/></label></div><label>Maximum TRI (m)<input type="number" value={maxTri} onChange={e=>setMaxTri(e.target.value)}/></label></>}
     {needsPoint&&<>
       <div className="survey-action-bar"><button className={p.picking?'active':''} disabled={!area} onClick={()=>{setPickEnd(false);p.onPick();}}>{p.picking?'Click map…':operation==='visibility'?'Pick observer':operation==='least_cost'?'Pick route start':'Pick outlet'}</button>
       <button disabled={!area} onClick={()=>{const center=p.geometry&&measurementAnchor(p.geometry);if(center){setLon(String(center[0]));setLat(String(center[1]));}}}>Area center</button></div>
       <div className="area-fields"><input aria-label="Terrain origin longitude" type="number" step="any" placeholder="Longitude" value={lon} onChange={e=>setLon(e.target.value)}/>
       <input aria-label="Terrain origin latitude" type="number" step="any" placeholder="Latitude" value={lat} onChange={e=>setLat(e.target.value)}/></div>
       {operation==='least_cost'&&<button disabled={!area||p.picking} onClick={()=>{setPickEnd(true);p.onPick();}}>Pick route end</button>}
       {operation==='least_cost'&&<div className="area-fields"><input aria-label="Route end longitude" type="number" step="any" placeholder="End longitude" value={endLon} onChange={e=>setEndLon(e.target.value)}/><input aria-label="Route end latitude" type="number" step="any" placeholder="End latitude" value={endLat} onChange={e=>setEndLat(e.target.value)}/></div>}
       {operation==='visibility'&&<div className="area-fields"><label>Observer (m)<input aria-label="Observer height" type="number" min="0" value={height} onChange={e=>setHeight(e.target.value)}/></label>
       <label>Target (m)<input aria-label="Target height" type="number" min="0" value={target} onChange={e=>setTarget(e.target.value)}/></label></div>}
     </>}
     <div className="terrain-run-row"><button className="primary-tool" disabled={!canRun||busy} onClick={()=>void run()}>{busy?'Calculating…':'Run terrain operation'}</button>
       {busy&&<button onClick={()=>{setLive(false);cancelAnalysis();setInfo('Analysis request cancelled.');}}>Cancel</button>}
       <label><input aria-label="Live terrain updates" type="checkbox" checked={live} onChange={e=>setLive(e.target.checked)}/> Live</label></div>
     {!p.connected&&<small className="compact-notice">API offline</small>}
     {!dem&&<small className="compact-notice">DEM required</small>}
     {dem&&!verified&&<small className="compact-notice">Confirm elevation units before analysis</small>}
     {!parametersValid&&<small className="discovery-error">Check numeric parameters</small>}
   </div>}
   {!!records.length&&<section className="terrain-run-list" aria-label="Analysis result layers">
     <div className="section-heading">Analysis results · {records.length}</div>
     {records.map(record=><div key={record.id} className={'scratch-row '+(selectedRecord===record.id?'active':'')}>
       <input type="checkbox" aria-label={'Show '+record.title+' '+record.id} checked={record.visible} disabled={!record.advanced?.features.length&&!record.advanced?.raster}
         onChange={e=>setRecords(old=>old.map(r=>r.id===record.id?{...r,visible:e.target.checked}:r))}/>
       <button title={record.source.name} onClick={()=>{setSelectedRecord(record.id);setInfo('');latest.current.onHover(null);}}>{record.title} · {new Date(record.createdAt).toLocaleTimeString()}</button>
       <button aria-label={'Remove result '+record.title} onClick={()=>{setRecords(old=>old.filter(r=>r.id!==record.id));if(selectedRecord===record.id)setSelectedRecord(null);}}>×</button>
     </div>)}
   </section>}
   {(result||slope||profile)&&<ResultPane expanded={expanded} onClose={()=>setExpanded(false)}>
     <div className="section-heading">{selected?.title} <span><button onClick={()=>setExpanded(!expanded)}>{expanded?'Close expanded':'Expand'}</button> <button onClick={exportResult} title="Export result data">Export</button></span></div>
     <small className="compact-notice">{selected?.source.name}{inputsChanged?' · previous inputs':''}</small>
     {slope&&<><div className="terrain-metrics">
       <div><span>Elevation range</span><strong>{fmt(slope.elevation_min_m)}–{fmt(slope.elevation_max_m)} m</strong></div>
       <div><span>Mean elevation</span><strong>{fmt(slope.elevation_mean_m)} m</strong></div>
       <div><span>Relief</span><strong>{fmt(slope.elevation_relief_m)} m</strong></div>
       <div><span>Mean slope</span><strong>{fmt(slope.mean_slope_deg)}°</strong></div>
       <div><span>Aspect</span><strong>{slope.mean_aspect_deg===null?'Flat':fmt(slope.mean_aspect_deg)+'°'}</strong></div>
     </div><MetricBars label="Slope (degrees)" max={90} values={[{name:'Mean',value:slope.mean_slope_deg,color:'#3977aa'},{name:'Maximum',value:slope.maximum_slope_deg,color:'#d18b31'}]}/>
     <small className="compact-notice" title={slope.warning}>{slope.valid_pixels} valid cells · {slope.engine}</small></>}
     {profile&&<ProfilePlot samples={profile.samples} length={profile.length_m} onHover={p.onHover}/>}
     {result&&<>
       <div className="terrain-metrics">{Object.entries(result.metrics).map(([k,v])=><div key={k}><span>{names[k]??k.replaceAll('_',' ')}</span><strong>{fmt(v)} {units[k]??''}</strong></div>)}</div>
       {result.operation==='volume'&&<MetricBars label="Earthwork volume (m³)" values={[{name:'Cut',value:result.metrics.cut_m3,color:'#b87848'},{name:'Fill',value:result.metrics.fill_m3,color:'#3b82ab'}]}/>}
       {result.operation==='visibility'&&<MetricBars label="Visibility (cells)" values={[{name:'Visible',value:result.metrics.visible_cells,color:'#34885c'},{name:'Unknown',value:result.metrics.unknown_cells,color:'#9099a2'},{name:'Hidden',value:Math.max(0,result.valid_cells-result.metrics.visible_cells-result.metrics.unknown_cells),color:'#c17d55'}]}/>}
       {result.operation==='watershed'&&<MetricBars label="Catchment (cells)" values={[{name:'Upstream',value:result.metrics.upstream_cells,color:'#3687b9'},{name:'Other',value:Math.max(0,result.valid_cells-result.metrics.upstream_cells),color:'#9ba7ad'}]}/>}
       {result.distribution&&<ElevationDistribution bins={result.distribution}/>}
       {result.raster&&<div className="terrain-profile-chart"><img src={result.raster.png} alt="Derived terrain raster" style={{width:'100%',maxHeight:180,objectFit:'contain'}}/><MetricBars label="Terrain class distribution (cells)" values={result.raster.legend.map(b=>({name:b.label,value:b.cells,color:b.color}))}/><button onClick={()=>{const a=document.createElement('a');const data=Uint8Array.from(atob(result.raster!.geotiff),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([data],{type:'image/tiff'}));a.href=url;a.download=result.operation+'.tif';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}}>GeoTIFF</button></div>}
       {result.operation==='aspect_map'&&result.raster&&<AspectRose bins={result.raster.legend}/>}
       {result.sections&&<SectionPlot sections={result.sections} onHover={p.onHover}/>}
       {result.mesh&&<GPUView mesh={result.mesh} fallback={<MeshView mesh={result.mesh}/>}/>}
       <small className="compact-notice" title={result.warning}>{result.valid_cells} valid · {result.missing_cells} missing · Method ⓘ</small>
       {result.features.length>0&&<div className="survey-action-bar"><button disabled={!p.projectId||busy||selected?.saved||result.features.length>512} title={result.features.length>512?'Export GeoJSON for results exceeding the atomic project batch limit.':'Save to project'} onClick={()=>void save()}>{selected?.saved?'Saved to project':'Save terrain features'}</button>
         <button onClick={()=>setRecords(old=>old.map(r=>r.id===selectedRecord?{...r,visible:true}:r))}>Show on map</button><button onClick={()=>setRecords(old=>old.map(r=>r.id===selectedRecord?{...r,visible:false}:r))}>Hide</button></div>}
     </>}
   </ResultPane>}
   {info&&<p className="project-info">{info}</p>}{error&&<p className="discovery-error" role="alert">{error}</p>}
 </div>;
}
