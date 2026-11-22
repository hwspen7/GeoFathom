import {useEffect,useRef,useState,type ChangeEvent} from 'react';
import {Mountain} from 'lucide-react';
import {advancedTerrain,saveFeatureBatch,analyzeTerrain,terrainProfile,listImagery,uploadImagery,fetchPublicDEM,type TerrainResult,type TerrainMesh,type TerrainOperation,type AdvancedTerrainResult,type RasterAsset} from './api';
import {ProfilePlot,MetricBars} from './TerrainCharts';
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
    <small>Drag to rotate · elevations in meters</small>
  </div>;
}

type Operation=TerrainOperation|'slope'|'profile';
const modes:Array<{id:Operation;title:string}>=[
 {id:'slope',title:'Slope / aspect'},{id:'profile',title:'Elevation profile'},{id:'contours',title:'Contours'},
 {id:'volume',title:'Cut / fill'},{id:'visibility',title:'Viewshed'},{id:'watershed',title:'Watershed (D8)'},{id:'mesh',title:'3D terrain'}
];
const units:Record<string,string>={cut_m3:'m³',fill_m3:'m³',net_cut_m3:'m³',covered_grid_area_m2:'m²',reference_elevation_m:'m',
 contour_lines:'',interval_m:'m',visible_cells:'',visible_grid_area_m2:'m²',unknown_cells:'',upstream_cells:'',upstream_grid_area_m2:'m²',minimum_m:'m',maximum_m:'m'};
const names:Record<string,string>={cut_m3:'Cut',fill_m3:'Fill',net_cut_m3:'Net cut',covered_grid_area_m2:'Grid area',reference_elevation_m:'Reference',
 contour_lines:'Contour lines',interval_m:'Interval',visible_cells:'Visible cells',visible_grid_area_m2:'Visible area',unknown_cells:'Unknown cells',
 upstream_cells:'Upstream cells',upstream_grid_area_m2:'Catchment area',minimum_m:'Lowest elevation',maximum_m:'Highest elevation'};
const fmt=(n:number)=>n.toLocaleString('en-US',{maximumFractionDigits:2});
interface Props{
 projectId:string|null;geometry:GeoJSON.Geometry|null;raster:RasterAsset|null;active:boolean;connected:boolean;
 viewport:[number,number,number,number]|null;
 localImport:boolean;refreshToken:number;origin:Position|null;picking:boolean;
 onSelectRaster:(r:RasterAsset)=>void;onDraw:(line:boolean)=>void;onUseExtent:()=>void;onPick:()=>void;
 onHover:(point:Position|null)=>void;onPreview:(g:GeoJSON.Feature[])=>void;onSaved:()=>void;
}
export default function TerrainWorkbench(p:Props){
 const [operation,setOperation]=useState<Operation>('slope');
 const [assets,setAssets]=useState<RasterAsset[]>([]),[token,setToken]=useState('');
 const [resolution,setResolution]=useState<30|90>(30),[fetching,setFetching]=useState(false),[sourceInfo,setSourceInfo]=useState('');
 const [interval,setInterval]=useState('10'),[reference,setReference]=useState('0');
 const [lon,setLon]=useState(''),[lat,setLat]=useState(''),[height,setHeight]=useState('1.7'),[target,setTarget]=useState('0');
 const [result,setResult]=useState<AdvancedTerrainResult|null>(null),[slope,setSlope]=useState<TerrainResult|null>(null);
 const [profile,setProfile]=useState<Awaited<ReturnType<typeof terrainProfile>>|null>(null);
 const [live,setLive]=useState(false),[busy,setBusy]=useState(false),[importing,setImporting]=useState(false);
 const [error,setError]=useState(''),[info,setInfo]=useState('');
 const sequence=useRef(0),latest=useRef(p);latest.current=p;
 const area=p.geometry?.type==='Polygon'||p.geometry?.type==='MultiPolygon';
 const needsPoint=operation==='watershed'||operation==='visibility';
 const correctShape=operation==='profile'?p.geometry?.type==='LineString':area;
 const dem=p.raster?.bands===1?p.raster:null;
 const canRun=p.connected&&!!dem&&!!correctShape&&(!needsPoint||!!lon.trim()&&!!lat.trim());
 useEffect(()=>{
   if(!p.active||!p.connected)return;
   let current=true;
   listImagery().then(list=>{if(current)setAssets(list.filter(a=>a.bands===1));})
     .catch(e=>{if(current)setError(e instanceof Error?e.message:String(e));});
   return()=>{current=false;};
 },[p.active,p.connected,p.refreshToken]);
 useEffect(()=>{if(p.origin){setLon(String(p.origin[0]));setLat(String(p.origin[1]));}},[p.origin]);
 function resetResult(){
   setResult(null);setSlope(null);setProfile(null);setInfo('');
   latest.current.onPreview([]);latest.current.onHover(null);
 }
 async function run(){
   if(!canRun||!dem||!p.geometry)return;
   const ticket=++sequence.current;setBusy(true);setError('');resetResult();
   try{
     if(operation==='profile'){
       const value=await terrainProfile(dem.id,p.geometry);
       if(ticket===sequence.current)setProfile(value);
     }else if(operation==='slope'){
       const value=await analyzeTerrain(dem.id,p.geometry);
       if(ticket===sequence.current)setSlope(value);
     }else{
       const value=await advancedTerrain({image_id:dem.id,geometry:p.geometry,operation,
         interval:Number(interval),reference:Number(reference),point:needsPoint?[Number(lon),Number(lat)]:null,
         observer_height:Number(height),target_height:Number(target)});
       if(ticket!==sequence.current)return;
       setResult(value);latest.current.onPreview(value.features);
     }
   }catch(e){if(ticket===sequence.current)setError(e instanceof Error?e.message:'Terrain analysis failed.');}
   finally{if(ticket===sequence.current)setBusy(false);}
 }
 useEffect(()=>{
   sequence.current++;setBusy(false);setError('');resetResult();
   if(!live||!canRun)return;
   const timer=window.setTimeout(()=>void run(),450);
   return()=>{window.clearTimeout(timer);sequence.current++;};
 },[p.projectId,p.geometry,dem?.id,operation,interval,reference,lon,lat,height,target,live,p.connected]);
 useEffect(()=>()=>{sequence.current++;},[]);
 async function importDEM(e:ChangeEvent<HTMLInputElement>){
   const file=e.target.files?.[0];e.target.value='';if(!file)return;
   setImporting(true);setError('');
   try{
     if(!p.localImport&&!token.trim())throw Error('Enter import access token.');
     const item=await uploadImagery(file,token);
     if(item.bands!==1)throw Error('Select a single-band DEM, not RGB imagery.');
     setAssets(old=>[item,...old.filter(v=>v.id!==item.id)]);
     latest.current.onSelectRaster(item);
   }catch(e){setError(e instanceof Error?e.message:String(e));}
   finally{setImporting(false);}
 }
 async function fetchDEM(){
   if(!p.connected||fetching)return;
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
   setFetching(true);setError('');setSourceInfo('');
   try{
     if(!p.localImport&&!token.trim())throw Error('Enter import access token.');
     const data=await fetchPublicDEM(bbox,resolution,token);
     setAssets(old=>[data.asset,...old.filter(item=>item.id!==data.asset.id)]);
     latest.current.onSelectRaster(data.asset);
     setSourceInfo('GLO-'+resolution+' · '+data.valid_cells+'/'+data.total_cells+' cells · DSM'+(data.missing_tiles.length?' · partial coverage':''));
   }catch(e){setError(e instanceof Error?e.message:String(e));}
   finally{setFetching(false);}
 }
 async function save(){
   if(!p.projectId||!dem||!result)return;
   const ticket=sequence.current;setBusy(true);setError('');
   try{
     const saved=await saveFeatureBatch(p.projectId,result.features.map((f,i)=>({
       geometry:f.geometry,name:String(f.properties.name||result.operation)+' '+(i+1),
       source:'DEM '+dem.name,properties:{...f.properties,source_image:dem.id,operation:result.operation}
     })));
     if(ticket===sequence.current){setInfo('Saved '+saved.created+' terrain features.');latest.current.onSaved();}
   }catch(e){if(ticket===sequence.current)setError(e instanceof Error?e.message:'Save failed.');}
   finally{if(ticket===sequence.current)setBusy(false);}
 }
 function exportResult(){
   const payload=result?.features.length?{type:'FeatureCollection',features:result.features}:result??slope??profile;
   if(!payload)return;
   const link=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
   link.href=url;link.download='terrain-'+operation+(result?.features.length?'.geojson':'.json');link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 return <div className="terrain-workbench professional-panel">
   <div className="terrain-source">
     <label>Elevation layer<select aria-label="DEM elevation layer" value={dem?.id??''}
       onChange={e=>{const found=assets.find(item=>item.id===e.target.value);if(found)p.onSelectRaster(found);}}>
       <option value="">Select DEM</option>
       {[...assets,...(dem&&!assets.some(a=>a.id===dem.id)?[dem]:[])].map(asset=><option key={asset.id} value={asset.id}>{asset.name}</option>)}
     </select></label>
     {!p.localImport&&<details className="access-settings"><summary>Import access</summary><input type="password" aria-label="DEM import token" value={token} onChange={e=>setToken(e.target.value)}/></details>}
     <label className="raster-upload" title="Single-band DEM GeoTIFF, projected in meters, with meter elevations"><Mountain size={14}/> {importing?'Importing…':'Import DEM'}
       <input type="file" aria-label="Import DEM" accept=".tif,.tiff" disabled={importing||!p.connected} onChange={e=>void importDEM(e)}/></label>
     <div className="area-fields">
       <select aria-label="Public DEM resolution" value={resolution} onChange={e=>setResolution(Number(e.target.value) as 30|90)}><option value={30}>GLO-30 · 30 m</option><option value={90}>GLO-90 · 90 m</option></select>
       <button disabled={!p.connected||!p.viewport||fetching||importing} title="Download real Copernicus DEM for selected shape or current map extent" onClick={()=>void fetchDEM()}>{fetching?'Fetching…':'Fetch DEM'}</button>
     </div>
     {sourceInfo&&<small className="compact-notice" title="Copernicus DEM is a digital surface model including buildings and vegetation. Public coverage varies.">{sourceInfo}</small>}
     {dem&&<small className="compact-notice" title={dem.provenance}>{dem.width} × {dem.height} · {dem.crs} · m</small>}
   </div>
   <div className="terrain-command-grid" aria-label="Terrain tools">
     {modes.map(mode=><button key={mode.id} type="button" aria-pressed={operation===mode.id} onClick={()=>setOperation(mode.id)}>{mode.title}</button>)}
   </div>
   <select aria-label="Advanced terrain operation" className="visually-hidden" tabIndex={-1} value={operation} onChange={e=>setOperation(e.target.value as Operation)}>
     {modes.map(mode=><option key={mode.id} value={mode.id}>{mode.title}</option>)}
   </select>
   <div className="professional-form">
     <div className="survey-action-bar">
       <button onClick={()=>p.onDraw(operation==='profile')}>{operation==='profile'?'Draw profile line':'Draw study area'}</button>
       {operation!=='profile'&&<button disabled={!dem} onClick={p.onUseExtent}>DEM extent</button>}
     </div>
     <small className="compact-notice">{correctShape?'✓ Geometry selected':operation==='profile'?'Select or draw a line':'Select or draw a polygon'}</small>
     {operation==='contours'&&<label>Interval (m)<input aria-label="Contour interval" type="number" min=".01" step="any" value={interval} onChange={e=>setInterval(e.target.value)}/></label>}
     {operation==='volume'&&<label>Reference elevation (m)<input aria-label="Reference elevation" type="number" step="any" value={reference} onChange={e=>setReference(e.target.value)}/></label>}
     {needsPoint&&<>
       <div className="survey-action-bar"><button className={p.picking?'active':''} disabled={!area} onClick={p.onPick}>{p.picking?'Click map…':operation==='visibility'?'Pick observer':'Pick outlet'}</button>
       <button disabled={!area} onClick={()=>{const center=p.geometry&&measurementAnchor(p.geometry);if(center){setLon(String(center[0]));setLat(String(center[1]));}}}>Area center</button></div>
       <div className="area-fields"><input aria-label="Terrain origin longitude" type="number" step="any" placeholder="Longitude" value={lon} onChange={e=>setLon(e.target.value)}/>
       <input aria-label="Terrain origin latitude" type="number" step="any" placeholder="Latitude" value={lat} onChange={e=>setLat(e.target.value)}/></div>
       {operation==='visibility'&&<div className="area-fields"><label>Observer (m)<input aria-label="Observer height" type="number" min="0" value={height} onChange={e=>setHeight(e.target.value)}/></label>
       <label>Target (m)<input aria-label="Target height" type="number" min="0" value={target} onChange={e=>setTarget(e.target.value)}/></label></div>}
     </>}
     <div className="terrain-run-row"><button className="primary-tool" disabled={!canRun||busy} onClick={()=>void run()}>{busy?'Calculating…':'Run terrain operation'}</button>
       <label><input aria-label="Live terrain updates" type="checkbox" checked={live} onChange={e=>setLive(e.target.checked)}/> Live</label></div>
     {!p.connected&&<small className="compact-notice">API offline</small>}
     {!dem&&<small className="compact-notice">DEM required</small>}
   </div>
   {(result||slope||profile)&&<section className="terrain-output" aria-label="Terrain results">
     <div className="section-heading">Results <button onClick={exportResult} title="Export result data">Export</button></div>
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
       {operation==='volume'&&<MetricBars label="Earthwork volume (m³)" values={[{name:'Cut',value:result.metrics.cut_m3,color:'#b87848'},{name:'Fill',value:result.metrics.fill_m3,color:'#3b82ab'}]}/>}
       {operation==='visibility'&&<MetricBars label="Visibility (cells)" values={[{name:'Visible',value:result.metrics.visible_cells,color:'#34885c'},{name:'Unknown',value:result.metrics.unknown_cells,color:'#9099a2'},{name:'Hidden',value:Math.max(0,result.valid_cells-result.metrics.visible_cells-result.metrics.unknown_cells),color:'#c17d55'}]}/>}
       {operation==='watershed'&&<MetricBars label="Catchment (cells)" values={[{name:'Upstream',value:result.metrics.upstream_cells,color:'#3687b9'},{name:'Other',value:Math.max(0,result.valid_cells-result.metrics.upstream_cells),color:'#9ba7ad'}]}/>}
       {result.mesh&&<MeshView mesh={result.mesh}/>}
       <small className="compact-notice" title={result.warning}>{result.valid_cells} valid · {result.missing_cells} missing · Method ⓘ</small>
       {result.features.length>0&&<div className="survey-action-bar"><button disabled={!p.projectId||busy} onClick={()=>void save()}>Save terrain features</button>
         <button onClick={()=>p.onPreview(result.features)}>Show on map</button><button onClick={()=>p.onPreview([])}>Hide</button></div>}
     </>}
   </section>}
   {info&&<p className="project-info">{info}</p>}{error&&<p className="discovery-error" role="alert">{error}</p>}
 </div>;
}
