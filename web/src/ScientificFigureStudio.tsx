import {useEffect,useMemo,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {getStudioCatalog,renderStudio,type StudioInput,type StudioOutput,type StudioRaster,type StudioRecipe} from './api';
import {saveFigureBlob} from './figureExport';
import {tableCSV} from './figureLibrary';

export interface StudioSource {name:string;csv?:string;rasters?:StudioRaster[];provenance?:unknown}
const empty:StudioInput={recipe:'',csv:'',rasters:[],x:'',y:'',z:'',group:'',low:'',high:'',columns:[],title:'',x_label:'',y_label:'',parameter:null,maximize_x:false,maximize_y:false,palette:'color',font:'sans',font_size:10,grid:true,width_mm:180,height_mm:125,dpi:120,format:'png'};
const fieldLabels:Record<string,string>={x:'X / category / design A',y:'Y / response / design B',z:'Z / secondary quantity',group:'Group',low:'Lower bound / low-setting response',high:'Upper bound / high-setting response'};
function columns(csv:string):string[]{
 // Parse quoted CSV header, including commas and escaped double quotes.
 const out:string[]=[];let cell='',quoted=false;
 for(let i=0;i<csv.length;i++){const c=csv[i];if(c==='"'){if(quoted&&csv[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}
 else if(!quoted&&(c===','||c==='\r'||c==='\n')){out.push(cell.trim().replace(/^\uFEFF/,''));cell='';if(c!==',')return out.filter(Boolean);}
 else cell+=c;
 }if(cell)out.push(cell.trim());return out.filter(Boolean);
}
export function studioHeader(csv:string){return columns(csv);}
export function studioRequest(settings:StudioInput,recipe:StudioRecipe,rasters:StudioRaster[],format:StudioInput['format'],dpi:StudioInput['dpi']):StudioInput{
 return {...settings,recipe:recipe.id,csv:recipe.source==='table'?settings.csv:'',rasters:recipe.source==='raster'?rasters:[],format,dpi};
}
function readBase64(file:File):Promise<string>{
 return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',',2)[1]??'');r.onerror=()=>reject(new Error('Unable to read raster.'));r.readAsDataURL(file);});
}
function downloadEncoded(data:string,mime:string,name:string){
 const binary=atob(data);const bytes=new Uint8Array(binary.length);for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
 saveFigureBlob(new Blob([bytes],{type:mime}),name);
}
function jsonFile(value:unknown,name:string){saveFigureBlob(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}),name);}
export default function ScientificFigureStudio({source,onClose}:{source:StudioSource;onClose:()=>void}){
 const [recipes,setRecipes]=useState<StudioRecipe[]>([]),[family,setFamily]=useState('All'),[search,setSearch]=useState('');
 const [settings,setSettings]=useState<StudioInput>(()=>({...empty,csv:source.csv??'',title:''}));
 const [rasters,setRasters]=useState<StudioRaster[]>(()=>source.rasters??[]),[selected,setSelected]=useState<number[]>(()=>source.rasters?.length?[0]:[]);
 const [output,setOutput]=useState<StudioOutput|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[dpi,setDpi]=useState<300|600>(300);
 const [completed,setCompleted]=useState<StudioInput|null>(null),[fileName,setFileName]=useState(source.csv?'Current result data table':'No CSV selected');
 const active=recipes.find(r=>r.id===settings.recipe),headers=useMemo(()=>columns(settings.csv),[settings.csv]);
 const chosen=selected.flatMap(i=>rasters[i]?[rasters[i]]:[]);
 const dialog=useRef<HTMLDivElement>(null),controller=useRef<AbortController|null>(null);
 useEffect(()=>{const previous=document.activeElement as HTMLElement|null;dialog.current?.focus();const ac=new AbortController();
  getStudioCatalog(ac.signal).then(r=>{if(ac.signal.aborted)return;setRecipes(r.recipes);const first=source.rasters?.length?r.recipes.find(x=>x.id==='raster_continuous'):r.recipes.find(x=>x.source==='table');if(first)setSettings(s=>({...s,recipe:first.id}));}).catch(e=>{if(!ac.signal.aborted)setError(String(e.message??e));});
  return()=>{ac.abort();controller.current?.abort();previous?.focus();};
 },[]);
 function change<K extends keyof StudioInput>(k:K,v:StudioInput[K]){setSettings(s=>({...s,[k]:v}));setOutput(null);setCompleted(null);setError('');}
 function selectRecipe(r:StudioRecipe){setSettings(s=>({...s,recipe:r.id,parameter:r.option?.[1]??null,title:'',x_label:'',y_label:''}));setOutput(null);setCompleted(null);setError('');}
 function invalidate(){setOutput(null);setCompleted(null);}
 async function csvFile(file?:File){if(!file)return;try{if(file.size>5_000_000)throw Error('CSV exceeds 5 MB.');const text=await file.text();setFileName(file.name);setSettings(s=>({...s,csv:text,x:'',y:'',z:'',group:'',low:'',high:'',columns:[]}));invalidate();setError('');}catch(e){setError((e as Error).message);}}
 async function rasterFiles(files:FileList|null){if(!files)return;try{
  if(rasters.length+files.length>64)throw Error('Maximum 64 available raster inputs. Select at most eight per figure.');const add:StudioRaster[]=[];
  for(const file of Array.from(files)){if(file.size>24_000_000)throw Error('GeoTIFF exceeds 24 MB.');add.push({name:file.name,data:await readBase64(file),unit:''});}
  setSelected(s=>[...s,...add.map((_,i)=>rasters.length+i)].slice(0,8));setRasters(r=>[...r,...add]);invalidate();setError('');
 }catch(e){setError((e as Error).message);}}
 const required=active?.fields??[];
 const canRender=!!active&&(active.source==='table'?!!settings.csv&&required.every(f=>f==='columns'?settings.columns.length>0:!!settings[f as keyof StudioInput]):chosen.length>=active.minimum_rasters&&chosen.length<=8);
 const families=['All',...new Set(recipes.map(r=>r.family))];
 const visible=recipes.filter(r=>(family==='All'||r.family===family)&&(!search||r.title.toLowerCase().includes(search.toLowerCase())));
 async function render(format:StudioInput['format']='png',preview=true){
  if(!active||!canRender||busy)return;const ac=new AbortController();controller.current=ac;setBusy(true);setError('');
  const input=studioRequest(settings,active,chosen,format,preview?120:dpi);
  try{const value=await renderStudio(input,ac.signal);if(ac.signal.aborted)return;
   if(preview){setOutput(value);setCompleted(input);}else downloadEncoded(value.figure,value.media_type,'geofathom-'+active.id+'.'+format);
  }catch(e){if(!ac.signal.aborted)setError((e as Error).message);}finally{if(controller.current===ac){controller.current=null;setBusy(false);}}
 }
 function cancel(){controller.current?.abort();controller.current=null;setBusy(false);}
 function exportData(){if(!output?.table.length)return;saveFigureBlob(new Blob([tableCSV({columns:output.table[0].map(String),rows:output.table.slice(1),x_label:'',y_label:'',unit:''})],{type:'text/csv;charset=utf-8'}),'geofathom-'+active?.id+'-plot-data.csv');}
 return createPortal(<div className="figure-studio-backdrop"><div className="figure-studio" role="dialog" aria-modal="true" aria-label="Scientific figure studio" tabIndex={-1} ref={dialog} onKeyDown={e=>{
  e.stopPropagation();if(e.key==='Escape'){e.preventDefault();if(busy)cancel();else onClose();}
  if(e.key==='Tab'){const nodes=Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button:enabled,input:enabled,select:enabled,textarea:enabled')).filter(n=>n.getClientRects().length>0);const first=nodes[0],last=nodes[nodes.length-1];if(e.shiftKey&&(document.activeElement===first||document.activeElement===dialog.current)){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}
 }}>
 <header><div><strong>Scientific figure studio</strong><small>{source.name} · Extended scientific recipes</small></div><button type="button" onClick={()=>{cancel();onClose();}}>Close studio</button></header>
 <div className="figure-studio-layout">
  <aside className="studio-recipes"><label>Figure category<select aria-label="Figure category" value={family} onChange={e=>setFamily(e.target.value)}>{families.map(f=><option key={f}>{f}</option>)}</select></label>
  <label>Search figures<input aria-label="Search figures" value={search} onChange={e=>setSearch(e.target.value)}/></label>
  <small>{visible.length} / {recipes.length} recipes</small>
  <div className="studio-recipe-list">{visible.map(r=><button type="button" key={r.id} disabled={busy} aria-pressed={r.id===settings.recipe} onClick={()=>selectRecipe(r)}><strong>{r.title}</strong><small>{r.family} · {r.source==='raster'?'GeoTIFF':'Data table'}</small></button>)}</div></aside>
  <aside className="studio-config">
   {active&&<fieldset disabled={busy}><legend>Data and figure settings</legend>{active.note&&<small>{active.note}</small>}
    {active.source==='table'?<>
      <label>Import CSV<input type="file" accept=".csv,text/csv" aria-label="Import figure CSV" onChange={e=>void csvFile(e.target.files?.[0])}/></label>
      <small>{fileName}</small><label>CSV data<textarea aria-label="Figure CSV data" rows={4} value={settings.csv} onChange={e=>{change('csv',e.target.value);setFileName('Edited data table');}}/></label>
      {required.filter(f=>f!=='columns').map(f=><label key={f}>{fieldLabels[f]??f}<select aria-label={'Figure field '+f} value={String(settings[f as keyof StudioInput]??'')} onChange={e=>change(f as 'x'|'y'|'z'|'group'|'low'|'high',e.target.value)}><option value="">Select column</option>{headers.map(h=><option key={h}>{h}</option>)}</select></label>)}
      {required.includes('columns')&&<label>Numeric series<select multiple size={Math.min(6,Math.max(2,headers.length))} aria-label="Figure numeric series" value={settings.columns} onChange={e=>change('columns',Array.from(e.target.selectedOptions,o=>o.value))}>{headers.map(h=><option key={h}>{h}</option>)}</select></label>}
    </>:<>
      <label>Import GeoTIFF<input type="file" multiple accept=".tif,.tiff" aria-label="Import figure GeoTIFF" onChange={e=>void rasterFiles(e.target.files)}/></label>
      <small>Select in input order; maps preserve the original grid.</small>
      {rasters.map((r,i)=><div className="studio-raster" key={i}><label><input type="checkbox" checked={selected.includes(i)} disabled={!selected.includes(i)&&selected.length>=8} onChange={e=>{setSelected(s=>e.target.checked?[...s,i]:s.filter(n=>n!==i));invalidate();}}/>{selected.includes(i)?String(selected.indexOf(i)+1)+'. ':''}{r.name}</label>
       <label>Unit<input aria-label={'Raster unit '+(i+1)} value={r.unit} placeholder="e.g. m" onChange={e=>{setRasters(old=>old.map((item,j)=>j===i?{...item,unit:e.target.value}:item));invalidate();}}/></label></div>)}
      {chosen.length<active.minimum_rasters&&<small>Requires at least {active.minimum_rasters} raster inputs.</small>}
    </>}
    {active.id==='pareto'&&<><label><input type="checkbox" checked={settings.maximize_x} onChange={e=>change('maximize_x',e.target.checked)}/> Maximize X objective</label><label><input type="checkbox" checked={settings.maximize_y} onChange={e=>change('maximize_y',e.target.checked)}/> Maximize Y objective</label></>}
    {active.option&&<label>{active.option[0]}<input aria-label="Figure parameter" type="number" step="any" min={active.option[2]} max={active.option[3]} value={settings.parameter??active.option[1]} onChange={e=>change('parameter',Number(e.target.value))}/></label>}
    <label>Title<input aria-label="Studio figure title" value={settings.title} maxLength={200} placeholder={active.title} onChange={e=>change('title',e.target.value)}/></label>
    <label>X label<input value={settings.x_label} onChange={e=>change('x_label',e.target.value)}/></label><label>Y label<input value={settings.y_label} onChange={e=>change('y_label',e.target.value)}/></label>
    <label>Palette<select value={settings.palette} onChange={e=>change('palette',e.target.value as StudioInput['palette'])}><option value="color">Scientific color</option><option value="mono">Monochrome</option><option value="earth">Earth</option></select></label>
    <label>Font<select value={settings.font} onChange={e=>change('font',e.target.value as StudioInput['font'])}><option value="sans">Sans-serif</option><option value="serif">Serif</option></select></label>
    <label>Font size (pt)<input type="number" min="6" max="18" value={settings.font_size} onChange={e=>change('font_size',Number(e.target.value))}/></label>
    <label><input type="checkbox" checked={settings.grid} onChange={e=>change('grid',e.target.checked)}/> Grid</label>
    <div className="studio-size"><label>Width (mm)<input type="number" min="60" max="300" value={settings.width_mm} onChange={e=>change('width_mm',Number(e.target.value))}/></label><label>Height (mm)<input type="number" min="40" max="250" value={settings.height_mm} onChange={e=>change('height_mm',Number(e.target.value))}/></label></div>
   </fieldset>}
  </aside>
  <section className="studio-preview" aria-label="Studio figure preview">
   {error&&<p role="alert" className="discovery-error">{error}</p>}{busy&&<p role="status">Rendering the selected data…</p>}
   {output?<><img alt={active?.title+' preview'} src={'data:'+output.media_type+';base64,'+output.figure}/><div className="studio-receipt"><strong>Numerical population</strong><p>{String(output.metadata.used_count)} used / {String(output.metadata.input_count)} input observations or cells</p>{Boolean(output.metadata.method_note)&&<small>{String(output.metadata.method_note)}</small>}</div>
    {!!output.table.length&&<details><summary>Computed plot data ({output.table.length-1} rows)</summary><table><thead><tr>{output.table[0].map((v,i)=><th key={i}>{v}</th>)}</tr></thead><tbody>{output.table.slice(1,11).map((row,i)=><tr key={i}>{row.map((v,j)=><td key={j}>{v??'Missing'}</td>)}</tr>)}</tbody></table></details>}
   </>:<div className="studio-empty">Select a recipe, bind the required data and render a scientific figure.</div>}
  </section>
 </div>
 <footer><button type="button" disabled={!canRender||busy} onClick={()=>void render()}>Render figure</button>{busy&&<button type="button" onClick={cancel}>Cancel render</button>}<label>Export resolution<select aria-label="Studio export DPI" value={dpi} onChange={e=>setDpi(Number(e.target.value) as 300|600)}><option value={300}>300 DPI</option><option value={600}>600 DPI</option></select></label>
  {(['png','svg','pdf','tiff'] as const).map(format=><button type="button" key={format} disabled={!output||busy} onClick={()=>void render(format,false)}>{format.toUpperCase()}</button>)}
  <button type="button" disabled={!output?.table.length||busy} onClick={exportData}>Plot CSV</button>
  <button type="button" disabled={!output||!completed||busy} onClick={()=>jsonFile({schema:'geofathom-studio-reproduction-1',input:completed,metadata:output?.metadata,table:output?.table,provenance:source.provenance},'geofathom-'+active?.id+'-reproduction.json')}>Reproduction JSON</button>
 </footer>
 </div></div>,document.body);
}
