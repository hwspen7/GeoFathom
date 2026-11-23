import {useEffect,useRef,useState} from 'react';
import {inspectDatasetFiles,inspectDatasetOptions,discardDatasetUpload,startDatasetImport,
 getGISJob,cancelGISJob,downloadExchangeJob,restoreProjectPackage,
 type ExchangeUpload,type ImportDatasetOptions,type GISJob,type GeoWorkspace,type RasterAsset} from './api';
interface Props {projectId:string|null;workspace:GeoWorkspace|null;onRefresh:()=>void;onRasterAdded:(asset:RasterAsset,kind:'image'|'dem')=>void}
export default function DatasetImport(p:Props){
 const [mode,setMode]=useState<'batch'|'restore'>('batch');
 const [upload,setUpload]=useState<ExchangeUpload|null>(null);
 const [options,setOptions]=useState<Record<string,ImportDatasetOptions>>({});
 const [index,setIndex]=useState(0),[view,setView]=useState<'layers'|'fields'|'coordinates'>('layers');
 const [field,setField]=useState(''),[layer,setLayer]=useState('');
 const [job,setJob]=useState<GISJob|null>(null),[busy,setBusy]=useState(false);
 const [error,setError]=useState(''),[notice,setNotice]=useState(''),[token,setToken]=useState('');
 const epoch=useRef(0),controller=useRef<AbortController|null>(null);
 const staged=useRef<{project:string;id:string}|null>(null),running=useRef<{project:string;id:string}|null>(null);
 useEffect(()=>{
  epoch.current++;setUpload(null);setOptions({});setJob(null);setBusy(false);setError('');setNotice('');setLayer('');setIndex(0);setField('');
  return ()=>{
   epoch.current++;controller.current?.abort();
   const active=running.current;running.current=null;
   if(active)void cancelGISJob(active.project,active.id).catch(()=>{});
   const pending=staged.current;staged.current=null;
   if(pending)void discardDatasetUpload(pending.project,pending.id).catch(()=>{});
  };
 },[p.projectId]);
 useEffect(()=>{
  if(!job||!p.projectId||!['queued','running'].includes(job.status))return;
  let live=true;const project=p.projectId,id=job.id,generation=epoch.current;
  const timer=window.setTimeout(()=>{void getGISJob(project,id).then(next=>{
   if(!live||epoch.current!==generation)return;setJob(next);
   if(next.status==='completed'){
    running.current=null;p.onRefresh();const r=next.result as {created?:number;rejected?:number};
    setNotice(`Imported ${r.created??0} features · ${r.rejected??0} rejected. Download the validation report for row details.`);
   }else if(['failed','cancelled','interrupted'].includes(next.status)){
    running.current=null;setError(next.error||'Import '+next.status+'. No uncommitted features were saved.');
   }
  }).catch(e=>{if(live)setError(String(e));});},700);
  return ()=>{live=false;window.clearTimeout(timer);};
 },[job,p.projectId,p.onRefresh]);
 const current=upload?.files[index],opts=current?options[current.id]??{}:{};
 const fields=current?.layers.flatMap(l=>l.fields).filter((f,i,a)=>a.findIndex(v=>v.name===f.name)===i)??[];
 const activeField=field||fields[0]?.name||'';
 const active=busy||Boolean(job&&['queued','running'].includes(job.status));
 function change(next:Partial<ImportDatasetOptions>){if(current)setOptions(old=>({...old,[current.id]:{...opts,...next}}));}
 async function inspect(files:File[]){
  if(!p.projectId||!files.length)return;
  if(files.length>20||files.some(f=>!f.size||f.size>128*1024*1024)){setError('Choose 1–20 nonempty files, each at most 128 MB.');return;}
  const project=p.projectId,generation=epoch.current;setBusy(true);setError('');setJob(null);setNotice('');
  controller.current?.abort();const abort=new AbortController();controller.current=abort;
  try{
   if(staged.current){await discardDatasetUpload(staged.current.project,staged.current.id);staged.current=null;}
   const result=await inspectDatasetFiles(project,files,abort.signal);
   if(epoch.current!==generation){void discardDatasetUpload(project,result.upload_id).catch(()=>{});return;}
   staged.current={project,id:result.upload_id};setUpload(result);setOptions({});setIndex(0);setField('');
  }catch(e){if(epoch.current===generation)setError(e instanceof Error?e.message:String(e));}
  finally{if(epoch.current===generation)setBusy(false);}
 }
 async function submit(){
  if(!p.projectId||!upload)return;const project=p.projectId,generation=epoch.current;
  setBusy(true);setError('');
  try{
   const result=await startDatasetImport(project,upload.upload_id,upload.files.map(f=>({id:f.id,options:options[f.id]??{}})),layer);
   staged.current=null;
   if(epoch.current!==generation){void cancelGISJob(project,result.id).catch(()=>{});return;}
   running.current={project,id:result.id};setJob(result);setUpload(null);
   if(result.status==='completed'){running.current=null;p.onRefresh();const r=result.result as {created:number;rejected:number};setNotice(`Imported ${r.created} features · ${r.rejected} rejected. Download the validation report for row details.`);}
  }catch(e){if(epoch.current===generation)setError(e instanceof Error?e.message:String(e));}
  finally{if(epoch.current===generation)setBusy(false);}
 }
 return <div className="dataset-exchange">
  <div className="data-choice-buttons">
   <button type="button" disabled={active} aria-pressed={mode==='batch'} onClick={()=>setMode('batch')}>Batch / layers</button>
   <button type="button" disabled={active} aria-pressed={mode==='restore'} onClick={()=>setMode('restore')}>Restore project</button>
  </div>
  {!p.projectId&&<small>Create or select a project first.</small>}
  {mode==='batch'?<>
   <input aria-label="Batch dataset files" type="file" multiple disabled={!p.projectId||active}
    accept=".json,.geojson,.csv,.gpkg,.kml,.gpx,.zip" onChange={e=>{void inspect(Array.from(e.target.files??[]));e.target.value='';}}/>
   {!upload&&!job&&<small>Inspect up to 20 files · 128 MB/file · 100,000 features/batch. Strict validation commits the whole batch together.</small>}
   {upload&&current&&<>
    <div className="gis-record-pager">
     <button type="button" disabled={!index||active} onClick={()=>{setIndex(i=>i-1);setField('');}}>Previous file</button>
     <span>{index+1} / {upload.files.length}</span>
     <button type="button" disabled={index+1===upload.files.length||active} onClick={()=>{setIndex(i=>i+1);setField('');}}>Next file</button>
    </div>
    <strong className="exchange-filename">{current.name}</strong>
    <select aria-label="Import configuration" value={view} onChange={e=>setView(e.target.value as typeof view)}>
     <option value="layers">Layers & validation</option><option value="fields">Field names & types</option><option value="coordinates">CSV & source coordinates</option>
    </select>
    {view==='layers'&&<>
     <label>Source layers<select aria-label="Source layers" multiple size={Math.min(3,Math.max(1,current.layers.length))}
      value={opts.layers??current.layers.map(l=>l.name)} onChange={e=>change({layers:Array.from(e.target.selectedOptions,o=>o.value)})}>
      {current.layers.map(l=><option key={l.name} value={l.name}>{l.name} · {l.feature_count<0?'unknown':l.feature_count} features · {l.source_crs??'CRS missing'}</option>)}
     </select></label>
     {current.error&&<small role="alert">{current.error}</small>}
     {Boolean(current.errors?.length)&&<small>{current.errors!.length} preview validation errors; full row report is available after import with skip enabled.</small>}
     <label>Invalid rows<select aria-label="Import error policy" value={opts.error_policy??'strict'} onChange={e=>change({error_policy:e.target.value as 'strict'|'skip'})}>
      <option value="strict">Reject entire batch</option><option value="skip">Skip invalid rows & report</option>
     </select></label>
     <label>Destination<select aria-label="Batch target layer" value={layer} onChange={e=>setLayer(e.target.value)}>
      <option value="">New layer per source layer</option>
      {(p.workspace?.layers??[]).filter(l=>!l.locked).map(l=><option key={l.id} value={l.id}>{l.name}</option>)}
     </select></label>
    </>}
    {view==='fields'&&<>
     <label>Source field<select aria-label="Import source field" value={activeField} onChange={e=>setField(e.target.value)}>
      {fields.map(f=><option key={f.name} value={f.name}>{f.name} · {f.type??f.types?.join('/')}</option>)}
     </select></label>
     <label>Output field name<input aria-label="Import field name" maxLength={64} disabled={!activeField}
      value={opts.field_map?.[activeField]??activeField} onChange={e=>change({field_map:{...opts.field_map,[activeField]:e.target.value}})}/></label>
     <label>Output type<select aria-label="Import field type" disabled={!activeField} value={opts.field_types?.[opts.field_map?.[activeField]??activeField]??''}
      onChange={e=>{const key=opts.field_map?.[activeField]??activeField;const types={...opts.field_types};if(e.target.value)types[key]=e.target.value;else delete types[key];change({field_types:types});}}>
      <option value="">Preserve source</option>{['string','integer','number','boolean','json'].map(t=><option key={t} value={t}>{t}</option>)}
     </select></label>
    </>}
    {view==='coordinates'&&<>
     <label>Missing / text source CRS<input aria-label="Import source EPSG" placeholder="EPSG:4326" value={opts.source_crs??''} onChange={e=>change({source_crs:e.target.value||undefined})}/></label>
     <div className="data-input-pair">
      <label>Longitude field<input aria-label="CSV longitude field" value={opts.longitude_field??'longitude'} onChange={e=>change({longitude_field:e.target.value})}/></label>
      <label>Latitude field<input aria-label="CSV latitude field" value={opts.latitude_field??'latitude'} onChange={e=>change({latitude_field:e.target.value})}/></label>
     </div>
     <label>WKT field (optional)<input aria-label="CSV WKT field" value={opts.geometry_field??''} onChange={e=>change({geometry_field:e.target.value||undefined})}/></label>
     <div className="data-input-pair">
      <label>Encoding<select aria-label="Dataset encoding" value={opts.encoding??'utf-8'} onChange={e=>change({encoding:e.target.value})}>
       {['utf-8','utf-8-sig','utf-16','cp1252','gb18030'].map(v=><option key={v}>{v}</option>)}
      </select></label>
      <label>CSV separator<select aria-label="CSV delimiter" value={opts.delimiter??','} onChange={e=>change({delimiter:e.target.value})}>
       <option value=",">Comma</option><option value=";">Semicolon</option><option value={'\t'}>Tab</option><option value="|">Pipe</option>
      </select></label>
     </div>
    </>}
    <div className="data-choice-buttons">
     <button type="button" disabled={active} onClick={()=>{const generation=epoch.current;setBusy(true);setError('');void inspectDatasetOptions(p.projectId!,upload.upload_id,current.id,opts).then(r=>{
      if(epoch.current===generation)setUpload(old=>old&&({...old,files:old.files.map(f=>f.id===current.id?{...f,...r,error:undefined}:f)}));
     }).catch(e=>{if(epoch.current===generation)setError(String(e));}).finally(()=>{if(epoch.current===generation)setBusy(false);});}}>Recheck options</button>
     <button type="button" className="data-primary" disabled={active||upload.files.some(f=>Boolean(f.error))} onClick={()=>void submit()}>Import batch</button>
    </div>
   </>}
  </>:<>
   <small>Restore saved features, layers, styles, CRS and history into a new empty project. Included GeoTIFFs are validated and assigned new IDs.</small>
   <label>Operator import token<input type="password" autoComplete="off" aria-label="Package import token" value={token} onChange={e=>setToken(e.target.value)}/></label>
   <input aria-label="Restore project package" type="file" accept=".zip" disabled={!p.projectId||active||Boolean(p.workspace?.total)} onChange={e=>{
    const file=e.target.files?.[0];e.target.value='';if(!file||!p.projectId)return;
    if(file.size>128*1024*1024){setError('Compressed packages must be at most 128 MB.');return;}
    const generation=epoch.current;controller.current?.abort();controller.current=new AbortController();setBusy(true);setError('');
    void restoreProjectPackage(p.projectId,file,token,controller.current.signal).then(r=>{
     if(epoch.current!==generation)return;p.onRefresh();r.rasters.forEach(v=>p.onRasterAdded(v.asset,v.kind));setNotice(`Restored ${r.created} features, ${r.layers} layers and ${r.rasters.length} rasters.`);
    }).catch(e=>{if(epoch.current===generation)setError(String(e));}).finally(()=>{if(epoch.current===generation)setBusy(false);});
   }}/>
  </>}
  {job&&<div role="status"><span>{job.status} · {job.progress}%</span>
   <progress aria-label="Dataset import progress" value={job.progress} max={100}/>
   {['queued','running'].includes(job.status)&&<button type="button" onClick={()=>void cancelGISJob(p.projectId!,job.id).then(setJob).catch(e=>setError(String(e)))}>Cancel import</button>}
   {job.status==='completed'&&<button type="button" onClick={()=>void downloadExchangeJob(p.projectId!,job.id).catch(e=>setError(String(e)))}>Download import report</button>}
  </div>}
  {busy&&<small role="status">Validating dataset…</small>}
  {notice&&<small role="status">{notice}</small>}{error&&<small className="discovery-error" role="alert">{error}</small>}
 </div>;
}
