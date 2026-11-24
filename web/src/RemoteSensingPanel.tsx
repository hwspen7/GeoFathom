import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {getRemoteCatalog,runRemoteScience,getSpatialRasterSource,type RemoteSource,type RemoteMethod,type RemoteBinding,type RemoteEncoding,type RemoteQuality,type RemoteQualityScheme,type SpatialScienceResult,type SpatialFigureSource,type StudioRaster,type TerrainRasterLayer} from './api';
import {saveFigureBlob} from './figureExport';
import ScientificFigureStudio from './ScientificFigureStudio';

const emptyBinding=(source=-1):RemoteBinding=>({source,band:1,encoding:'metadata',scale:1,offset:0,unit:''});
const schemes:Array<[RemoteQualityScheme,string]>=[['binary','Binary (1 = retain)'],['sentinel_clear','Sentinel-2 SCL'],['landsat_clear','Landsat QA_PIXEL'],['landsat_unsaturated','Landsat QA_RADSAT']];
function readFile(file:File):Promise<string>{return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('Cannot read GeoTIFF.'));reader.readAsDataURL(file);});}
function input(r:StudioRaster):StudioRaster{return {name:r.name,data:r.data,unit:r.unit,band:r.band??1};}
function download(data:string,name:string,type:string){saveFigureBlob(new Blob([data],{type}),name);}
function rasterDownload(r:StudioRaster){saveFigureBlob(new Blob([Uint8Array.from(atob(r.data),c=>c.charCodeAt(0))],{type:'image/tiff'}),r.name+'.tif');}

export default function RemoteSensingPanel({active,connected,resultsTarget,assets=[],onPreview}:{
 active:boolean;connected:boolean;resultsTarget?:HTMLElement|null;assets?:Array<{id:string;name:string}>;onPreview:(layer:TerrainRasterLayer)=>void;
}){
 const [open,setOpen]=useState(false),[methods,setMethods]=useState<RemoteMethod[]>([]),[group,setGroup]=useState('Optical'),[op,setOp]=useState(''),[search,setSearch]=useState('');
 const [sources,setSources]=useState<RemoteSource[]>([]),[bindings,setBindings]=useState<Record<string,RemoteBinding>>({}),[quality,setQuality]=useState<RemoteQuality[]>([]),[params,setParams]=useState<Record<string,number>>({});
 const [asset,setAsset]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[result,setResult]=useState<SpatialScienceResult|null>(null);
 const [studio,setStudio]=useState(false),[plot,setPlot]=useState<SpatialFigureSource|null>(null);
 const request=useRef<AbortController|null>(null),dialog=useRef<HTMLDivElement>(null);
 const selected=methods.find(m=>m.id===op);
 const [seriesCount,setSeriesCount]=useState(6),[times,setTimes]=useState('0,30,60,90,120,150');
 const method=selected?.variable_series?{...selected,roles:Array.from({length:seriesCount},(_,i)=>({id:'date'+(i+1),quantity:'numeric'}))}:selected;
 const dates=times.split(',').map(x=>x.trim()?Number(x):NaN);
 const timeReady=!method?.variable_series||(dates.length===seriesCount&&dates.every((t,i)=>Number.isFinite(t)&&(i===0||t>dates[i-1])));
 const available=methods.filter(m=>search.trim()?(m.title+' '+m.group+' '+m.id).toLowerCase().includes(search.trim().toLowerCase()):m.group===group);
 const resultTitle=methods.find(m=>m.id===result?.operation)?.title??result?.operation;
 useEffect(()=>{if(!active&&!open)return;const ac=new AbortController();getRemoteCatalog(ac.signal).then(c=>{if(!ac.signal.aborted){setMethods(c.operations);setOp(old=>old||c.operations.find(m=>m.id==='ndvi')?.id||c.operations[0]?.id||'');}}).catch(e=>{if(!ac.signal.aborted)setError(String(e.message??e));});return()=>ac.abort();},[active,open]);
 useEffect(()=>()=>request.current?.abort(),[]);
 useEffect(()=>{if(!open)return;const last=document.activeElement as HTMLElement|null;dialog.current?.focus();return()=>last?.focus();},[open]);
 function choose(id:string){setOp(id);setParams({});setBindings({});setQuality([]);setResult(null);setError('');}
 function close(){request.current?.abort();request.current=null;setBusy(false);setOpen(false);}
 function binding(role:string){return bindings[role]??emptyBinding();}
 function changeBinding(role:string,patch:Partial<RemoteBinding>){setBindings(old=>({...old,[role]:{...(old[role]??emptyBinding()),...patch}}));setResult(null);}
 function appendSource(s:RemoteSource){setSources(old=>old.length<64?[...old,s]:old);setResult(null);}
 async function upload(file:File){setBusy(true);setError('');try{if(file.size>24_000_000)throw Error('GeoTIFF exceeds 24 MB.');appendSource({name:file.name,data:await readFile(file)});}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function managed(){if(!asset)return;setBusy(true);setError('');try{const s=await getSpatialRasterSource(asset);appendSource({name:s.name,data:s.data});}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 function removeSource(index:number){
  setSources(old=>old.filter((_,i)=>i!==index));setBindings(old=>Object.fromEntries(Object.entries(old).map(([k,b])=>[k,{...b,source:b.source===index?-1:b.source>index?b.source-1:b.source}])));setQuality(old=>old.filter(q=>q.source!==index).map(q=>({...q,source:q.source>index?q.source-1:q.source})));setResult(null);
 }
 function validBinding(b:RemoteBinding){return b.source>=0&&b.source<sources.length&&Number.isInteger(b.band)&&b.band>=1&&b.band<=1024&&Number.isFinite(b.scale)&&b.scale>0&&Number.isFinite(b.offset);}
 const ready=Boolean(method&&timeReady&&method.roles.every(r=>validBinding(binding(r.id))&&(r.quantity!=='numeric'||!!binding(r.id).unit.trim()))&&quality.every(q=>q.source>=0&&q.source<sources.length&&Number.isInteger(q.band)&&q.band>=1&&q.band<=1024)&&method.parameters.every(p=>{const v=params[p.name]??p.default;return Number.isFinite(v)&&v>=p.minimum&&v<=p.maximum&&(!p.integer||Number.isInteger(v));}));
 async function run(){if(!ready||!method||busy)return;setBusy(true);setError('');setResult(null);const ac=new AbortController();request.current=ac;
  try{const out=await runRemoteScience({operation:method.id,sources,bindings:Object.fromEntries(method.roles.map(r=>[r.id,binding(r.id)])),quality,parameters:params,times:method.variable_series?dates:[]},ac.signal);if(!ac.signal.aborted)setResult(out);}catch(e){if(!ac.signal.aborted)setError((e as Error).message);}finally{if(request.current===ac){request.current=null;setBusy(false);}}
 }
 function options(){return <><option value="-1">Select source</option>{sources.map((s,i)=><option value={i} key={i}>{s.name}</option>)}</>;}
 function updateQuality(i:number,patch:Partial<RemoteQuality>){setQuality(old=>old.map((q,j)=>i===j?{...q,...patch}:q));setResult(null);}
 return <><div className="spatial-launch"><button disabled={!connected} onClick={()=>setOpen(true)}>Open Remote Sensing</button>{result&&<button onClick={()=>setOpen(true)}>Review remote sensing result</button>}</div>
 {active&&resultsTarget&&result&&createPortal(<section className="panel-section spatial-monitor"><h3>{resultTitle}</h3>{result.preview&&<img src={result.preview.png} alt="Remote sensing result"/>}<p>{result.receipt.crs} · {result.rows.length} records</p><button onClick={()=>setOpen(true)}>Review remote sensing result</button></section>,resultsTarget)}
 {open&&createPortal(<div className="figure-studio-backdrop"><div ref={dialog} role="dialog" aria-modal="true" aria-label="Remote sensing workbench" tabIndex={-1} className="spatial-science-dialog" onKeyDown={e=>{if(e.key==='Escape'&&!studio){e.stopPropagation();close();}if(e.key==='Tab'&&!studio){const nodes=Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button:enabled,input:enabled,select:enabled')).filter(n=>n.getClientRects().length);if(e.shiftKey&&(document.activeElement===nodes[0]||document.activeElement===dialog.current)){e.preventDefault();nodes.at(-1)?.focus();}else if(!e.shiftKey&&document.activeElement===nodes.at(-1)){e.preventDefault();nodes[0]?.focus();}}}}>
 <header><strong>Remote Sensing · {methods.length||'…'} scientific methods</strong><button onClick={close}>Close</button></header>
 <div className="spatial-science-columns"><div className="spatial-science-input">
 <fieldset disabled={busy}><legend>Method</legend><label>Find remote sensing method<input type="search" value={search} onChange={e=>setSearch(e.target.value)}/></label>
 <label>Method group<select value={group} onChange={e=>{setGroup(e.target.value);setSearch('');choose(methods.find(m=>m.group===e.target.value)?.id??'');}}>{[...new Set(methods.map(m=>m.group))].map(g=><option key={g}>{g}</option>)}</select></label>
 <label>Remote sensing method<select value={op} onChange={e=>{const m=methods.find(x=>x.id===e.target.value);if(m)setGroup(m.group);choose(e.target.value);}}>{method&&!available.some(x=>x.id===op)&&<option value={op}>{method.title}</option>}{available.map(m=><option value={m.id} key={m.id}>{m.title}</option>)}</select></label><small>{method?.assumption}</small></fieldset>
 <fieldset disabled={busy}><legend>Sources</legend>{assets.length>0&&<><label>Managed imagery<select value={asset} onChange={e=>setAsset(e.target.value)}><option value="">Choose imagery</option>{assets.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label><button disabled={!asset||sources.length>=64} onClick={()=>void managed()}>Add imagery</button></>}
 <label>GeoTIFF source<input type="file" accept=".tif,.tiff" disabled={sources.length>=64} onChange={e=>{const f=e.target.files?.[0];if(f)void upload(f);e.target.value='';}}/></label>
 {sources.map((s,i)=><div key={i} className="spatial-science-source">{s.name} <button onClick={()=>removeSource(i)}>Remove {s.name}</button></div>)}</fieldset>
 <fieldset disabled={busy}><legend>Band mapping and calibration</legend>{method?.variable_series&&<><label>Acquisition count<input type="number" min="6" max="64" value={seriesCount} onChange={e=>{const n=Math.min(64,Math.max(6,Math.trunc(Number(e.target.value)||6)));setSeriesCount(n);setBindings({});setQuality([]);setResult(null);}}/></label><label>Acquisition times (comma separated)<input value={times} onChange={e=>{setTimes(e.target.value);setResult(null);}}/></label></>}{method?.roles.map(r=>{const b=binding(r.id);return <div key={r.id} className="spatial-science-source"><strong>{r.id.replaceAll('_',' ')} · {r.quantity}</strong>
 <label>{r.id} source<select value={b.source} onChange={e=>changeBinding(r.id,{source:Number(e.target.value)})}>{options()}</select></label>
 <label>{r.id} band<input type="number" min="1" max="1024" step="1" value={b.band} onChange={e=>changeBinding(r.id,{band:Number(e.target.value)})}/></label>
 <label>{r.id} calibration<select value={b.encoding} onChange={e=>changeBinding(r.id,{encoding:e.target.value as RemoteEncoding})}><option value="metadata">GeoTIFF scale / offset</option><option value="raw">Already physical / raw class</option>{r.quantity==='reflectance'&&<option value="landsat_sr">Landsat C2 surface reflectance DN</option>}{r.quantity==='kelvin'&&<option value="landsat_st">Landsat C2 surface temperature DN</option>}{r.quantity!=='class'&&<option value="custom">Explicit scale and offset</option>}</select></label>
 {b.encoding==='custom'&&<><label>{r.id} scale<input type="number" step="any" value={b.scale} onChange={e=>changeBinding(r.id,{scale:Number(e.target.value)})}/></label><label>{r.id} offset<input type="number" step="any" value={b.offset} onChange={e=>changeBinding(r.id,{offset:Number(e.target.value)})}/></label></>}
 {r.quantity==='numeric'&&<label>{r.id} physical unit<input value={b.unit} onChange={e=>changeBinding(r.id,{unit:e.target.value})}/></label>}</div>;})}</fieldset>
 <fieldset disabled={busy}><legend>Quality masks</legend><button disabled={!sources.length||quality.length>=64} onClick={()=>{setQuality(old=>[...old,{source:0,band:1,scheme:'binary',roles:[]}]);setResult(null);}}>Add quality mask</button>
 {quality.map((q,i)=><div key={i} className="spatial-science-source"><label>Mask source<select value={q.source} onChange={e=>updateQuality(i,{source:Number(e.target.value)})}>{options()}</select></label><label>Mask band<input type="number" min="1" max="1024" value={q.band} onChange={e=>updateQuality(i,{band:Number(e.target.value)})}/></label><label>Quality scheme<select value={q.scheme} onChange={e=>updateQuality(i,{scheme:e.target.value as RemoteQualityScheme})}>{schemes.map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label>
 <label>Apply to<select value={q.roles[0]??''} onChange={e=>updateQuality(i,{roles:e.target.value?[e.target.value]:[]})}><option value="">All bands</option>{method?.roles.map(r=><option key={r.id} value={r.id}>{r.id}</option>)}</select></label><button onClick={()=>{setQuality(old=>old.filter((_,j)=>j!==i));setResult(null);}}>Remove mask</button></div>)}</fieldset>
 <fieldset disabled={busy}><legend>Parameters</legend>{method?.parameters.map(p=><label key={p.name}>{p.label}<input type="number" min={p.minimum} max={p.maximum} step={p.integer?1:'any'} value={params[p.name]??p.default} onChange={e=>{setParams(old=>({...old,[p.name]:Number(e.target.value)}));setResult(null);}}/></label>)}
 <button disabled={!ready||busy} onClick={()=>void run()}>Run remote sensing</button></fieldset>
 {busy&&<><p role="status">Computing…</p>{request.current&&<button onClick={()=>{request.current?.abort();request.current=null;setBusy(false);}}>Cancel request</button>}</>}{error&&<p role="alert">{error}</p>}</div>
 <div className="spatial-science-output">{result?<><h3>{resultTitle}</h3><p>{result.receipt.crs} · {result.rows.length} records</p><div className="spatial-science-actions">
 {result.raster&&<><button onClick={()=>rasterDownload(result.raster!)}>GeoTIFF</button>{result.preview&&<button onClick={()=>{const p=result.preview!,r=result.raster!;onPreview({id:'remote-'+r.sha256,title:resultTitle??r.name,raster:{png:p.png,geotiff:r.data,corners:p.corners,width:p.width,height:p.height,valid_cells:p.valid_cells,unit:r.unit,legend:[]},opacity:.85,resampling:'nearest'});close();}}>Show remote raster on map</button>}<button disabled={sources.length>=64} onClick={()=>{const r=result.raster!;appendSource({name:r.name,data:r.data});}}>Reuse result as source</button></>}
 {result.csv&&<button onClick={()=>download(result.csv,result.operation+'.csv','text/csv')}>CSV</button>}<button onClick={()=>download(JSON.stringify(result.receipt,null,2),result.operation+'-receipt.json','application/json')}>Research receipt</button>
 {(result.csv||result.raster)&&<button onClick={()=>{setPlot(null);setStudio(true);}}>Scientific Figure Studio</button>}</div>
 {!!result.figures?.length&&<section aria-label="Remote sensing research figures"><h4>Research figures</h4><div className="spatial-science-actions">{result.figures.map((p,i)=><button key={i} onClick={()=>{setPlot(p);setStudio(true);}}>{p.title}</button>)}</div></section>}
 {result.preview&&<><img alt="Georeferenced remote sensing preview" src={result.preview.png} style={{maxWidth:'100%',maxHeight:320,objectFit:'contain'}}/><p>{result.preview.minimum.toPrecision(6)} – {result.preview.maximum.toPrecision(6)} {result.preview.unit}</p></>}
 <table><tbody>{Object.entries(result.receipt.metrics).map(([k,v])=><tr key={k}><th>{k.replaceAll('_',' ')}</th><td>{typeof v==='number'?v.toPrecision(7):JSON.stringify(v)}</td></tr>)}</tbody></table>
 {!!result.columns.length&&<div className="spatial-table"><table><thead><tr>{result.columns.map(c=><th key={c}>{c}</th>)}</tr></thead><tbody>{result.rows.slice(0,200).map((row,i)=><tr key={i}>{row.map((v,j)=><td key={j}>{v===null?'NoData':typeof v==='number'?v.toPrecision(7):v}</td>)}</tr>)}</tbody></table><small>Showing {Math.min(result.rows.length,200)} of {result.rows.length}; CSV contains all rows.</small></div>}
 <details><summary>Calculation provenance</summary><pre>{JSON.stringify(result.receipt,null,2)}</pre></details></>:<p>Choose sources and map the required bands.</p>}</div></div></div></div>,document.body)}
 {studio&&result&&<ScientificFigureStudio initialTier="all" source={{name:plot?.title??result.operation,csv:plot?plot.csv??undefined:result.csv||undefined,rasters:(!plot||plot.raster)&&result.raster?(plot?.bands??(result.raster.band_count===3?[1,2,3]:[result.raster.band??1])).map(b=>({...input(result.raster!),band:b,name:result.raster!.name+' band '+b})):[],provenance:result.receipt,initialRecipe:plot?.recipe??(result.raster?.band_count===3?'spectral_rgb':undefined),initialBindings:plot?.bindings}} onClose={()=>setStudio(false)}/>}</>;
}
