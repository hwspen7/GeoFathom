import {useState} from 'react';
import {getTerrainComputeResources,setTerrainComputeResources,type TerrainComputePolicy,type TerrainComputeStatus} from './api';

const GiB=1024**3;
const gb=(n:number)=>(n/GiB).toFixed(1)+' GiB';
const n=(x:number)=>x.toLocaleString('en-US');
const groups=[
 ['slope_cells','Slope / DEM preparation',256000000],
 ['surface_cells','Local surfaces',32000000],
 ['global_cells','Global algorithms',8000000],
 ['visibility_cells','Viewshed',1048576],
 ['least_cost_cells','Least-cost path',2097152],
] as const;

export default function ComputingResources(){
 const [status,setStatus]=useState<TerrainComputeStatus|null>(null);
 const [draft,setDraft]=useState<TerrainComputePolicy|null>(null);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 const [saved,setSaved]=useState(false);
 async function refresh(){
  setBusy(true);setError('');setSaved(false);
  try{const s=await getTerrainComputeResources();setStatus(s);setDraft(s.policy);}
  catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 async function save(){
  if(!draft)return;
  setBusy(true);setError('');setSaved(false);
  try{const s=await setTerrainComputeResources(draft);setStatus(s);setDraft(s.policy);setSaved(true);}
  catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 const manual=draft?.mode==='manual';
 const e=status?.effective;
 return <details className="custom-basemap" onToggle={event=>{if(event.currentTarget.open&&!status&&!busy)void refresh();}}>
  <summary>Computing Resources</summary>
  {error&&<p role="alert" className="discovery-error">{error}</p>}
  {!status&&<button type="button" disabled={busy} onClick={()=>void refresh()}>{busy?'Detecting host…':'Detect host'}</button>}
  {status&&draft&&e&&<form className="professional-form compute-resource-form" aria-label="Terrain computing resources" onSubmit={event=>{event.preventDefault();void save();}}>
   <small>Backend CPU: {status.hardware.logical_cpus} logical cores · RAM: {gb(status.hardware.total_bytes)}</small>
   <small>Available: {gb(status.hardware.available_bytes)} · Disk: {gb(status.hardware.scratch_free_bytes)}</small>
   <small>GPU: {status.terrain_gpu==="available"?gb(status.hardware.gpu_total_bytes??0)+" VRAM":"CPU fallback"} · GPU budget: {gb(e.gpu_memory_bytes??0)}</small>
   <label>Compute backend <select aria-label="Compute backend" value={draft.backend??"auto"} onChange={event=>setDraft({...draft,backend:event.target.value as "auto"|"cpu"})}><option value="auto">Automatic CPU / CUDA</option><option value="cpu">CPU only</option></select></label>
   <label>OS-enforced memory <input aria-label="Hard memory isolation" type="checkbox" checked={draft.hard_memory??false} disabled={!status.hard_memory_available&&!draft.hard_memory} onChange={event=>setDraft({...draft,hard_memory:event.target.checked})}/></label>
   <small>{status.hard_memory_available?'Isolated worker available':'Hard memory isolation unavailable on this host'}</small>
   <small>Active tasks: {status.active_tasks} · Queued: {status.queued_tasks}</small>
   {status.reserved_bytes!==undefined&&<small>Reserved: {gb(status.reserved_bytes)}</small>}
   <label>Mode <select aria-label="Compute resource mode" value={draft.mode} onChange={event=>setDraft({...draft,mode:event.target.value as TerrainComputePolicy['mode']})}>
    <option value="automatic">Automatic</option><option value="manual">Manual</option>
   </select></label>
   {manual&&<fieldset disabled={busy}>
    <label>Memory budget (%) <input aria-label="Compute memory percent" type="number" min={10} max={85} step={1} required value={draft.memory_percent} onChange={event=>setDraft({...draft,memory_percent:event.target.valueAsNumber})}/></label>
    <label>GPU memory (%) <input aria-label="GPU memory percent" type="number" min={10} max={80} required value={draft.gpu_memory_percent??60} onChange={event=>setDraft({...draft,gpu_memory_percent:event.target.valueAsNumber})}/></label>
    <label>Concurrent tasks <input aria-label="Compute concurrent tasks" type="number" min={1} max={4} required value={draft.concurrent_tasks} onChange={event=>setDraft({...draft,concurrent_tasks:event.target.valueAsNumber})}/></label>
    <label>Tile size <select aria-label="Compute tile size" value={draft.tile_size} onChange={event=>setDraft({...draft,tile_size:Number(event.target.value) as TerrainComputePolicy['tile_size']})}>{[128,256,512,1024].map(v=><option key={v} value={v}>{v} × {v}</option>)}</select></label>
    {groups.map(([key,label,max])=><label key={key}>{label} cells <input aria-label={label+' cell ceiling'} type="number" min={9} max={max} required step={1} value={draft[key]} onChange={event=>setDraft({...draft,[key]:event.target.valueAsNumber})}/></label>)}
    <label>Viewshed extent (m) <input aria-label="Compute viewshed extent" type="number" min={100} max={100000} required value={draft.viewshed_distance_m} onChange={event=>setDraft({...draft,viewshed_distance_m:event.target.valueAsNumber})}/></label>
    <label>Total ray samples <input aria-label="Compute ray samples" type="number" min={1000} max={500000000} required value={draft.ray_samples} onChange={event=>setDraft({...draft,ray_samples:event.target.valueAsNumber})}/></label>
   </fieldset>}
   <div className="section-heading">Effective budget (current host)</div>
   <small>Per task: {gb(e.memory_bytes)} · {e.concurrent_tasks} concurrent · {e.tile_size} px tile</small>
   <table aria-label="Effective terrain cell limits"><tbody>{groups.map(([key,label])=><tr key={key}><th scope="row">{label}</th><td>{n(e[key])}</td></tr>)}
    <tr><th scope="row">Viewshed extent</th><td>{n(e.viewshed_distance_m)} m</td></tr><tr><th scope="row">Ray samples</th><td>{n(e.ray_samples)}</td></tr></tbody></table>
   <small>CUDA slope kernels where available · CPU fallback.</small>
   <button type="submit" disabled={busy}>Apply resources</button><button type="button" disabled={busy} onClick={()=>void refresh()}>Refresh hardware</button>
   {saved&&<small role="status">Resource settings saved.</small>}
  </form>}
 </details>;
}
