import {useEffect,useRef,useState} from 'react';
import {Mountain} from 'lucide-react';
import {advancedTerrain,saveFeatureBatch,type TerrainMesh,type TerrainOperation,type AdvancedTerrainResult,type RasterAsset} from './api';
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
export default function TerrainWorkbench(p:{projectId:string|null;geometry:GeoJSON.Geometry|null;raster:RasterAsset|null;
 onPreview:(g:GeoJSON.Geometry[])=>void;onSaved:()=>void}){
 const [operation,setOperation]=useState<TerrainOperation>('contours');
 const [interval,setInterval]=useState('10'),[reference,setReference]=useState('0');
 const [lon,setLon]=useState(''),[lat,setLat]=useState(''),[height,setHeight]=useState('1.7');
 const [target,setTarget]=useState('0'),[result,setResult]=useState<AdvancedTerrainResult|null>(null);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[info,setInfo]=useState('');
 const sequence=useRef(0);
 useEffect(()=>{sequence.current++;setResult(null);setError('');setInfo('');setBusy(false);p.onPreview([]);},
  [p.projectId,p.geometry,p.raster?.id,operation]);
 const area=p.geometry?.type==='Polygon'||p.geometry?.type==='MultiPolygon';
 async function run(){
   if(!p.raster||!p.geometry||!area)return;
   const ticket=++sequence.current;
   setBusy(true);setError('');setResult(null);setInfo('');
   try{
     const needsPoint=operation==='watershed'||operation==='visibility';
     if(needsPoint&&(!lon.trim()||!lat.trim()))throw new Error('Specify observer or outlet coordinates.');
     const value=await advancedTerrain({image_id:p.raster.id,geometry:p.geometry,operation,
       interval:Number(interval),reference:Number(reference),point:needsPoint?[Number(lon),Number(lat)]:null,
       observer_height:Number(height),target_height:Number(target)});
     if(ticket!==sequence.current)return;
     setResult(value);p.onPreview(value.features.map(f=>f.geometry));
   }catch(e){if(ticket===sequence.current)setError(e instanceof Error?e.message:'Terrain analysis failed.');}
   finally{if(ticket===sequence.current)setBusy(false);}
 }
 async function save(){
   if(!p.projectId||!p.raster||!result)return;
   const ticket=sequence.current;setBusy(true);setError('');
   try{
     const saved=await saveFeatureBatch(p.projectId,result.features.map((f,i)=>({
       geometry:f.geometry,name:String(f.properties.name||result.operation)+' '+(i+1),
       source:'DEM '+p.raster!.name,properties:{...f.properties,source_image:p.raster!.id,operation:result.operation}
     })));
     if(ticket===sequence.current){setInfo('Saved '+saved.created+' terrain features.');p.onSaved();}
   }catch(e){if(ticket===sequence.current)setError(e instanceof Error?e.message:'Save failed.');}
   finally{if(ticket===sequence.current)setBusy(false);}
 }
 return <details className="terrain-workbench professional-panel">
   <summary><Mountain size={14}/> Advanced DEM tools</summary>
   <div className="professional-form">
     <select aria-label="Advanced terrain operation" value={operation} onChange={e=>setOperation(e.target.value as TerrainOperation)}>
       <option value="contours">Contours</option><option value="volume">Cut / fill volume</option>
       <option value="visibility">Terrain visibility</option><option value="watershed">D8 contributing area</option>
       <option value="mesh">3D DEM preview</option>
     </select>
     <small>Input: {p.raster?.name||'Select a projected meter DEM'} · {area?'Area selected':'Draw an area'}</small>
     {operation==='contours'&&<label>Contour interval (m)<input aria-label="Contour interval" type="number" min=".01" step="any" value={interval} onChange={e=>setInterval(e.target.value)}/></label>}
     {operation==='volume'&&<label>Reference elevation (m)<input aria-label="Reference elevation" type="number" step="any" value={reference} onChange={e=>setReference(e.target.value)}/></label>}
     {(operation==='visibility'||operation==='watershed')&&<>
       <div className="area-fields"><input aria-label="Terrain origin longitude" type="number" step="any" placeholder="Longitude" value={lon} onChange={e=>setLon(e.target.value)}/>
       <input aria-label="Terrain origin latitude" type="number" step="any" placeholder="Latitude" value={lat} onChange={e=>setLat(e.target.value)}/></div>
       <button disabled={!area} onClick={()=>{const center=p.geometry&&measurementAnchor(p.geometry);if(center){setLon(String(center[0]));setLat(String(center[1]));}}}>Use area interior point</button>
       {operation==='visibility'&&<div className="area-fields"><label>Observer (m)<input aria-label="Observer height" type="number" min="0" value={height} onChange={e=>setHeight(e.target.value)}/></label>
       <label>Target (m)<input aria-label="Target height" type="number" min="0" value={target} onChange={e=>setTarget(e.target.value)}/></label></div>}
     </>}
     <button disabled={!area||!p.raster||busy} onClick={()=>void run()}>Run terrain operation</button>
     {result&&<><div className="terrain-metrics">{Object.entries(result.metrics).map(([k,v])=><div key={k}><span>{k.replaceAll('_',' ')}</span><strong>{v.toLocaleString('en-US',{maximumFractionDigits:2})}</strong></div>)}</div>
     {result.mesh&&<MeshView mesh={result.mesh}/>}
     <small>{result.warning}</small><small>{result.valid_cells} valid cells · {result.missing_cells} missing</small>
     {result.features.length>0&&<button disabled={!p.projectId||busy} onClick={()=>void save()}>Save terrain features</button>}</>}
     {info&&<p className="project-info">{info}</p>}{error&&<p className="discovery-error">{error}</p>}
   </div>
 </details>;
}
