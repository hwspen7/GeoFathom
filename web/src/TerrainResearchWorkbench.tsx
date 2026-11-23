import {useEffect,useRef,useState,type ChangeEvent} from 'react';
import {
 runTerrainResearch,checkTerrainCheckpointAccuracy,verifyTerrainResearchArchive,
 type RasterAsset,type TerrainResearchCriterion,type TerrainResearchResult,
 type CheckpointReport,type ElevationCheckpoint,
} from './api';

/** Research controls remain in one connected tool page. No arbitrary filesystem
 * paths are accepted: all inputs are selected from the managed raster library.
 */
type CriterionForm={
 name:string;image_id:string;direction:TerrainResearchCriterion['direction'];
 low:string;high:string;target:string;weight:string;sigma:string;weight_sigma:string;
 allowed_min:string;allowed_max:string;sampling:'nearest'|'bilinear';vertical_elevation:boolean;
};
const initial=(index:number,image_id=''):CriterionForm=>({
 name:index===0?'Terrain factor':'Supporting factor '+index,image_id,
 direction:index===0?'decreasing':'increasing',low:'0',high:'100',target:'50',
 weight:'1',sigma:'0',weight_sigma:'0',allowed_min:'',allowed_max:'',
 sampling:'bilinear',vertical_elevation:false,
});
const fmt=(value:number)=>Number.isFinite(value)
 ? value.toLocaleString('en-US',{maximumFractionDigits:4}):'—';
function saveFile(name:string,bytes:Uint8Array,mime:string){
 const blob=new Blob([Uint8Array.from(bytes)],{type:mime});
 const url=URL.createObjectURL(blob);
 const link=document.createElement('a');link.href=url;link.download=name;
 document.body.appendChild(link);link.click();link.remove();
 window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export default function TerrainResearchWorkbench({
 dem,geometry,assets,connected,
}:{
 dem:RasterAsset|null;geometry:GeoJSON.Geometry|null;assets:RasterAsset[];connected:boolean;
}){
 const [criteria,setCriteria]=useState<CriterionForm[]>(()=>[initial(0),initial(1)]);
 const [selected,setSelected]=useState(0);
 const [threshold,setThreshold]=useState('.65');
 const [sensitivity,setSensitivity]=useState('.2');
 const [trials,setTrials]=useState('64');
 const [seed,setSeed]=useState('42');
 const [ahp,setAhp]=useState(false);
 const [matrix,setMatrix]=useState('');
 const [result,setResult]=useState<TerrainResearchResult|null>(null);
 const [report,setReport]=useState<CheckpointReport|null>(null);
 const [message,setMessage]=useState('');
 const [busy,setBusy]=useState(false);
 const [validating,setValidating]=useState(false);
 const controller=useRef<AbortController|null>(null);
 const mounted=useRef(true);
 useEffect(()=>()=>{mounted.current=false;controller.current?.abort();},[]);
 useEffect(()=>{
  if(!dem)return;
  setCriteria(old=>old.map((row,i)=>row.image_id?row:{...row,image_id:i===0?dem.id:(assets.find(x=>x.id!==dem.id)?.id??dem.id)}));
 },[dem?.id,assets.length]); // A selected factor is never silently replaced.
 const all=[...assets,...(dem&&!assets.some(asset=>asset.id===dem.id)?[dem]:[])];
 const current=criteria[selected]??criteria[0];
 function change(index:number,key:keyof CriterionForm,value:string|boolean){
  setCriteria(old=>old.map((row,i)=>i===index?{...row,[key]:value}:row));
  setResult(null);setMessage('');
 }
 function add(){
  if(criteria.length>=8)return;
  setCriteria(old=>[...old,initial(old.length,dem?.id??'')]);
  setSelected(criteria.length);setResult(null);
 }
 function remove(){
  if(criteria.length<=2)return;
  setCriteria(old=>old.filter((_,i)=>i!==selected));
  setSelected(i=>Math.max(0,Math.min(i,criteria.length-2)));
  setResult(null);
 }
 async function run(){
  if(!connected||!dem||!geometry||!['Polygon','MultiPolygon'].includes(geometry.type)){
   setMessage('Select a DEM and polygon study area.');return;
  }
  let factors:TerrainResearchCriterion[];
  try{
   factors=criteria.map(row=>{
    if(!row.image_id||!row.name.trim()||!row.low.trim()||!row.high.trim())
     throw new Error('Every factor needs a raster, name and two value anchors.');
    for(const value of [row.low,row.high,row.weight,row.sigma,row.weight_sigma]){
     if(!Number.isFinite(Number(value)))throw new Error('Factor settings must be finite numbers.');
    }
    return {image_id:row.image_id,name:row.name.trim(),direction:row.direction,
      low:Number(row.low),high:Number(row.high),weight:Number(row.weight),
      sigma:Number(row.sigma),weight_sigma:Number(row.weight_sigma),
      ...(row.direction==='target'?{target:Number(row.target)}:{}),
      allowed_min:row.allowed_min.trim()?Number(row.allowed_min):null,
      allowed_max:row.allowed_max.trim()?Number(row.allowed_max):null,
      sampling:row.sampling,vertical_elevation:row.vertical_elevation};
   });
   if(factors.some(row=>row.allowed_min!==null&&!Number.isFinite(row.allowed_min)||
     row.allowed_max!==null&&!Number.isFinite(row.allowed_max)))
      throw new Error('Constraint bounds must be finite.');
   const pairwise=ahp?JSON.parse(matrix) as number[][]:null;
   const settings=[threshold,sensitivity,trials,seed].map(Number);
   if(settings.some(value=>!Number.isFinite(value)))throw new Error('Invalid analysis controls.');
   controller.current?.abort();const request=new AbortController();controller.current=request;
   setBusy(true);setMessage('');setResult(null);
   const answer=await runTerrainResearch({
    image_id:dem.id,geometry,criteria:factors,threshold:settings[0],
    sensitivity_fraction:settings[1],trials:settings[2],seed:settings[3],
    pairwise,
   },request.signal);
   if(mounted.current&&!request.signal.aborted)setResult(answer);
  }catch(error){
   if(mounted.current&&!(error instanceof DOMException&&error.name==='AbortError'))
    setMessage(error instanceof Error?error.message:String(error));
  }finally{if(mounted.current)setBusy(false);}
 }
 function exportArchive(){
  if(!result)return;
  try{
   const bytes=Uint8Array.from(atob(result.archive_base64),character=>character.charCodeAt(0));
   saveFile('geofathom-research-'+result.archive_sha256.slice(0,12)+'.zip',bytes,'application/zip');
  }catch{setMessage('Unable to decode the research ZIP. Run again or inspect the browser memory limit.');}
 }
 async function verify(){
  if(!result)return;
  setValidating(true);setMessage('');
  try{
   const reply=await verifyTerrainResearchArchive(result.archive_base64);
   if(mounted.current)setMessage(reply.valid?'Verified '+reply.files+' research artifacts against the SHA-256 manifest.':'Verification failed.');
  }catch(error){if(mounted.current)setMessage(String(error));}
  finally{if(mounted.current)setValidating(false);}
 }
 async function importCheckpoints(event:ChangeEvent<HTMLInputElement>){
  const file=event.currentTarget.files?.[0];
  if(!file||!dem)return;
  try{
   const rows=(await file.text()).replace(/\r/g,'').trim().split('\n');
   if(rows[0]?.trim().toLowerCase()!=='longitude,latitude,elevation_m')
    throw new Error('CSV header must be longitude,latitude,elevation_m');
   const points:ElevationCheckpoint[]=rows.slice(1).filter(Boolean).map(row=>{
    const cells=row.split(',').map(Number);
    if(cells.length!==3||cells.some(value=>!Number.isFinite(value)))
     throw new Error('Invalid checkpoint: '+row);
    return {longitude:cells[0],latitude:cells[1],elevation_m:cells[2]};
   });
   setReport(await checkTerrainCheckpointAccuracy(dem.id,points,dem.vertical_datum||undefined));
   setMessage('');
  }catch(error){setMessage(error instanceof Error?error.message:String(error));}
  finally{event.currentTarget.value='';}
 }
 return <div className="terrain-research-console" aria-label="Research study">
   <div className="terrain-research-row">
     <strong>Spatial model</strong>
     <button type="button" onClick={add} disabled={criteria.length>=8}>Add factor</button>
     <button type="button" onClick={remove} disabled={criteria.length<=2}>Remove</button>
   </div>
   <div className="terrain-research-factor-chooser">
     <label>Factor <select aria-label="Research factor" value={selected}
       onChange={event=>setSelected(Number(event.target.value))}>
       {criteria.map((row,i)=><option value={i} key={i}>{row.name||'Factor '+(i+1)}</option>)}
     </select></label>
     <span>{criteria.length} factors</span>
   </div>
   <div className="terrain-research-fields">
     <label>Name<input aria-label="Factor name" value={current.name}
       onChange={e=>change(selected,'name',e.target.value)}/></label>
     <label>Source<select aria-label="Factor raster" value={current.image_id}
       onChange={e=>change(selected,'image_id',e.target.value)}>
       <option value="">Select raster</option>
       {all.map(asset=><option key={asset.id} value={asset.id}>{asset.name}</option>)}
     </select></label>
     <label>Preference<select aria-label="Factor direction" value={current.direction}
       onChange={e=>change(selected,'direction',e.target.value)}>
       <option value="increasing">Higher is better</option>
       <option value="decreasing">Lower is better</option>
       <option value="target">Target is best</option>
     </select></label>
     <div className="terrain-research-two">
       <label>Low<input aria-label="Factor low" type="number" value={current.low} step="any" onChange={e=>change(selected,'low',e.target.value)}/></label>
       <label>High<input aria-label="Factor high" type="number" value={current.high} step="any" onChange={e=>change(selected,'high',e.target.value)}/></label>
     </div>
     {current.direction==='target'&&<label>Target<input aria-label="Factor target" type="number" value={current.target} step="any" onChange={e=>change(selected,'target',e.target.value)}/></label>}
     <div className="terrain-research-two">
       <label>Weight<input aria-label="Factor weight" type="number" min=".0001" step=".05" value={current.weight} onChange={e=>change(selected,'weight',e.target.value)}/></label>
       <label>Input σ<input aria-label="Factor input sigma" type="number" min="0" step=".1" value={current.sigma} onChange={e=>change(selected,'sigma',e.target.value)}/></label>
     </div>
     <details className="terrain-research-advanced">
       <summary>Factor constraints / error model</summary>
       <div className="terrain-research-two">
         <label>Min allowed<input aria-label="Factor minimum constraint" type="number" step="any" value={current.allowed_min} onChange={e=>change(selected,'allowed_min',e.target.value)}/></label>
         <label>Max allowed<input aria-label="Factor maximum constraint" type="number" step="any" value={current.allowed_max} onChange={e=>change(selected,'allowed_max',e.target.value)}/></label>
       </div>
       <label>Weight σ (relative)<input aria-label="Factor relative weight sigma" type="number" min="0" max="1" step=".05" value={current.weight_sigma} onChange={e=>change(selected,'weight_sigma',e.target.value)}/></label>
       <label>Grid sampling<select aria-label="Factor resampling" value={current.sampling} onChange={e=>change(selected,'sampling',e.target.value)}>
         <option value="bilinear">Bilinear (continuous)</option>
         <option value="nearest">Nearest (categorical)</option>
       </select></label>
       <label><input type="checkbox" checked={current.vertical_elevation} onChange={e=>change(selected,'vertical_elevation',e.target.checked)}/> Elevation: check vertical reference</label>
     </details>
   </div>
   <div className="terrain-research-two">
     <label>Threshold<input aria-label="Research score threshold" type="number" min="0" max="1" step=".05" value={threshold} onChange={e=>{setThreshold(e.target.value);setResult(null);}}/></label>
     <label>Simulations<input aria-label="Research trials" type="number" min="0" max="256" step="1" value={trials} onChange={e=>{setTrials(e.target.value);setResult(null);}}/></label>
   </div>
   <details className="terrain-research-advanced">
     <summary>Model validation & sensitivity</summary>
     <label>Weight perturbation<input aria-label="Research sensitivity" type="number" min=".01" max=".5" step=".05" value={sensitivity} onChange={e=>{setSensitivity(e.target.value);setResult(null);}}/></label>
     <label>Random seed<input aria-label="Research seed" type="number" min="0" step="1" value={seed} onChange={e=>{setSeed(e.target.value);setResult(null);}}/></label>
     <label><input type="checkbox" checked={ahp} onChange={e=>{setAhp(e.target.checked);setResult(null);}}/> AHP pairwise matrix</label>
     {ahp&&<textarea aria-label="Research AHP matrix JSON" value={matrix} rows={3}
       onChange={e=>{setMatrix(e.target.value);setResult(null);}}
       placeholder='[[1,2],[0.5,1]]'/>}
     <label className="terrain-research-checkpoint-input">Validate against GCP CSV
       <input type="file" accept=".csv,text/csv" aria-label="Independent elevation checkpoints" disabled={!dem}
         onChange={e=>void importCheckpoints(e)}/>
     </label>
     {report&&<div className="terrain-research-report">
       <span>RMSE {fmt(report.rmse_m)} m</span><span>MAE {fmt(report.mae_m)} m</span>
       <span>NMAD {fmt(report.nmad_m)} m</span><span>n = {report.sample_count}</span>
     </div>}
   </details>
   <div className="terrain-research-row">
     <button className="primary-tool" type="button" disabled={!connected||!dem||busy}
       onClick={()=>void run()}>{busy?'Computing…':'Run research model'}</button>
     {busy&&<button type="button" onClick={()=>controller.current?.abort()}>Cancel</button>}
   </div>
   {result&&<section className="terrain-research-outcome" aria-label="Research results">
     <div className="terrain-research-report">
       <span>Eligible <strong>{fmt(result.metrics.eligible_cells)}</strong></span>
       <span>Mean score <strong>{fmt(result.metrics.score_mean)}</strong></span>
       <span>Above threshold <strong>{fmt(result.metrics.eligible_above_threshold_pct)}%</strong></span>
       {result.model.uncertainty.score_sd_mean!==undefined&&
        <span>Mean σ <strong>{fmt(result.model.uncertainty.score_sd_mean)}</strong></span>}
     </div>
     <div className="terrain-research-row">
       <button type="button" onClick={exportArchive}>Research ZIP</button>
       <button type="button" disabled={validating} onClick={()=>void verify()}>Verify</button>
     </div>
   </section>}
   {message&&<small role="status" className="terrain-research-status">{message}</small>}
 </div>;
