import {useEffect,useRef,useState} from 'react';
import {downloadMapPDF,downloadDatasetExport,preflightDatasetExport,startDatasetExport,
 getGISJob,cancelGISJob,downloadExchangeJob,downloadProjectPackage,
 type DatasetExportOptions,type ExportPreflight,type GISJob,
 type GeoWorkspace,type Measurement,type NetworkFace,type TerrainRasterLayer} from './api';
import type {ScratchFeature} from './scratch';

type ExportScope='selection'|'local'|'areas'|'project'|'layer'|'viewport';
type ExportFormat='geojson'|'gpkg'|'kml'|'gpx'|'shapefile'|'csv'|'report'|'pdf'|'geotiff'|'package';
interface Props{
 projectId:string|null;workspace:GeoWorkspace|null;selected:GeoJSON.Geometry|null;
 selectedProperties?:Record<string,unknown>;
 measurement:Measurement|null;scratch:ScratchFeature[];faces:NetworkFace[];
 rasterSources?:Array<{id:string;kind:'image'|'dem'}>;
 terrainRasters:TerrainRasterLayer[];viewport:[number,number,number,number]|null;
}
const fileSave=(filename:string,blob:Blob)=>{
 const url=URL.createObjectURL(blob);
 const link=document.createElement('a');link.href=url;link.download=filename;
 document.body.appendChild(link);link.click();link.remove();
 window.setTimeout(()=>URL.revokeObjectURL(url),1500);
};
const jsonSave=(name:string,value:unknown)=>
 fileSave(name,new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
/** CSV imports may execute spreadsheet formulae even in quoted fields.
 * Quote every cell and prefix potentially executable *text* with an apostrophe.
 * Typed numeric measurements remain numeric, including legitimate negatives.
 */
const csvCell=(value:unknown)=>{
 let content=String(value??'');
 if(typeof value==='string'&&/^[\s\uFEFF]*[=+\-@]/.test(content))
  content="'"+content;
 return '"'+content.replace(/"/g,'""')+'"';
};
function collectionFromScope(scope:ExportScope,p:Props):GeoJSON.FeatureCollection{
 const items:GeoJSON.Feature[]=
  scope==='selection'?(p.selected?[{type:'Feature',geometry:p.selected,
   properties:{name:'Selected geometry',
    area_m2:p.measurement?.area_m2,perimeter_m:p.measurement?.perimeter_m,
    length_m:p.measurement?.length_m,method:p.measurement?.method,...p.selectedProperties}}]:[]):
  scope==='areas'?p.faces.map(f=>({type:'Feature',geometry:f.geometry,
   properties:{name:f.name,...f.properties,measurement_method:f.measurement.method}})):
  p.scratch.map(f=>({type:'Feature',geometry:f.geometry,properties:{
   name:f.name,source:f.source,area_m2:f.measurement.area_m2,
   perimeter_m:f.measurement.perimeter_m,length_m:f.measurement.length_m,
   measurement_method:f.measurement.method,...f.properties}}));
 return {type:'FeatureCollection',features:items};
}
export default function ExportWorkbench(p:Props){
 const [scope,setScope]=useState<ExportScope>('selection');
 const [format,setFormat]=useState<ExportFormat>('geojson');
 const [title,setTitle]=useState('GeoFathom survey');
 const [paper,setPaper]=useState<'a4'|'a3'|'letter'>('a4');
 const [orientation,setOrientation]=useState<'landscape'|'portrait'>('landscape');
 const [extent,setExtent]=useState<'all'|'viewport'>('all');
 const [grid,setGrid]=useState(true);
 const [legend,setLegend]=useState(true);
 const [rasterIndex,setRasterIndex]=useState(0);
 const [busy,setBusy]=useState(false),[jobStarting,setJobStarting]=useState(false);
 const [message,setMessage]=useState('');
 const [error,setError]=useState('');
 const [jobError,setJobError]=useState(''),[pollAttempt,setPollAttempt]=useState(0);
 const [layer,setLayer]=useState(''),[targetCRS,setTargetCRS]=useState('EPSG:4326');
 const [precision,setPrecision]=useState(''),[fields,setFields]=useState<string[]|null>(null);
 const [preview,setPreview]=useState<ExportPreflight|null>(null),[job,setJob]=useState<GISJob|null>(null);
 const [setup,setSetup]=useState<'scope'|'fields'|'delivery'>('scope');
 const [background,setBackground]=useState(false),[includeRasters,setIncludeRasters]=useState(false);
 const epoch=useRef(0),projectEpoch=useRef(0),abort=useRef<AbortController|null>(null);
 useEffect(()=>{epoch.current++;projectEpoch.current++;abort.current?.abort();setPreview(null);setJob(null);setJobStarting(false);setJobError('');setPollAttempt(0);setFields(null);setLayer('');setMessage('');setError('');setBusy(false);},[p.projectId]);
 const savedScope=['project','layer','viewport'].includes(scope);
 const signature=JSON.stringify([scope,layer,format,targetCRS,precision,p.selected,p.scratch,p.faces,p.viewport,p.workspace?.total]);
 useEffect(()=>{epoch.current++;abort.current?.abort();setBusy(false);setPreview(null);setMessage('');setError('');},[signature]);
 useEffect(()=>()=>abort.current?.abort(),[]);
 useEffect(()=>{
  if(!job||!p.projectId||!['queued','running'].includes(job.status))return;
  // Queued jobs belong to the project, independently of editable export inputs.
  let live=true;const generation=projectEpoch.current,project=p.projectId;
  const timer=window.setTimeout(()=>{void getGISJob(project,job.id).then(next=>{
   if(live&&projectEpoch.current===generation){
    setJob(next);setJobError(next.status==='failed'?next.error||'Export failed.':'');
   }
  }).catch(e=>{if(live&&projectEpoch.current===generation){setJobError(String(e));setPollAttempt(n=>n+1);}});},700);
  return ()=>{live=false;window.clearTimeout(timer);};
 },[job,p.projectId,pollAttempt]);
 useEffect(()=>{setFields(null);},[scope,layer,p.selected]);
 const count=scope==='selection'?Number(Boolean(p.selected)):
  scope==='local'?p.scratch.length:scope==='areas'?p.faces.length:
  preview?.count??(p.workspace?.total??0);
 const vectorFormat=['geojson','gpkg','kml','gpx','shapefile','csv','report'].includes(format);
 function options():DatasetExportOptions{
  return {format:format as DatasetExportOptions['format'],target_crs:['geojson','kml','gpx','report'].includes(format)?'EPSG:4326':targetCRS,
   include_measurements:format==='csv',...(precision.trim()?{precision:Number(precision)}:{}),...(fields?{fields}:{}),
   ...(scope==='layer'?{layer_ids:[layer]}:{}),...(scope==='viewport'&&p.viewport?{viewport:p.viewport}:{}),
   ...(!savedScope?{collection:collectionFromScope(scope,p)}:{})};
 }
 const canExport=format==='package'?Boolean(p.projectId):format==='geotiff'?p.terrainRasters.length>0:
  format==='pdf'?Boolean(p.projectId&&title.trim()&&(extent!=='viewport'||p.viewport)):
  savedScope?Boolean(p.projectId&&count&&(scope!=='layer'||layer)&&(scope!=='viewport'||p.viewport)):
  Boolean(count&&(p.projectId||['geojson','csv','report'].includes(format)));
 async function run(){
  if(!canExport||busy||jobStarting)return;setBusy(true);setError('');setMessage('');
  const generation=epoch.current,jobGeneration=projectEpoch.current;abort.current?.abort();abort.current=new AbortController();
  try{
   if(format==='package'){
    await downloadProjectPackage(p.projectId!,includeRasters?p.rasterSources??[]:[],abort.current.signal);
   }else if(format==='geotiff'){
    const raster=p.terrainRasters[rasterIndex];
    if(!raster?.raster.geotiff)throw Error('No georeferenced raster result selected.');
    const bytes=Uint8Array.from(atob(raster.raster.geotiff),c=>c.charCodeAt(0));
    fileSave('geofathom-'+raster.title.replace(/[^a-z0-9_-]/gi,'-')+'.tif',
      new Blob([Uint8Array.from(bytes)],{type:'image/tiff'}));
   }else if(format==='pdf'){
    if(!p.projectId)throw Error('Open a project for a printable map.');
    await downloadMapPDF(p.projectId,{
      title,paper,orientation,extent:extent==='viewport'?p.viewport:null,
      show_grid:grid,show_legend:legend,layer_ids:null,
    });
   }else if(p.projectId&&vectorFormat){
    if(background&&savedScope){
     setJobStarting(true);
     try{
      const result=await startDatasetExport(p.projectId,options());
      if(projectEpoch.current!==jobGeneration)return;setJob(result);setJobError('');
     }catch(e){
      if(projectEpoch.current===jobGeneration)setError(e instanceof Error?e.message:String(e));
      return;
     }finally{if(projectEpoch.current===jobGeneration)setJobStarting(false);}
    }else await downloadDatasetExport(p.projectId,options(),abort.current.signal);
   }else{
    // CSV / scientific reports use authoritative persisted measurements.
    // A generic vector-only GeoJSON export need not carry those attributes.
    const featureCollection=collectionFromScope(scope,p);
    if(!featureCollection.features.length)throw Error('No features in the selected export scope.');
    if(format==='geojson'){
     fileSave('geofathom-'+scope+'.geojson',new Blob([
      JSON.stringify(featureCollection,null,2)],{type:'application/geo+json'}));
    }else if(format==='csv'){
     const headers=Array.from(new Set(featureCollection.features.flatMap(f=>Object.keys(f.properties??{}))));
     headers.push('geometry_geojson','coordinate_system');
     const lines=[headers.map(csvCell).join(',')];
     for(const f of featureCollection.features){
      const props:Record<string,unknown>=f.properties??{};
      const values=headers.slice(0,-2).map(key=>{const value=props[key];return typeof value==='object'&&value!==null?JSON.stringify(value):value;});
      lines.push([...values,JSON.stringify(f.geometry),'EPSG:4326'].map(csvCell).join(','));
     }
     fileSave('geofathom-'+scope+'-measurements.csv',
       new Blob(['\ufeff'+lines.join('\r\n')+'\r\n'],{type:'text/csv;charset=utf-8'}));
    }else if(format==='report'){
     const measurements=featureCollection.features.map(f=>({
       name:f.properties?.name??'Unnamed',type:f.geometry.type,
       area_m2:f.properties?.area_m2??null,
       perimeter_m:f.properties?.perimeter_m??null,
       length_m:f.properties?.length_m??null,
       method:(f.properties as Record<string,unknown>)?.measurement_method??
        (f.properties as Record<string,unknown>)?.method??null,
     }));
     jsonSave('geofathom-'+scope+'-report.json',{
      schema:'geofathom.export-report.v1',created_utc:new Date().toISOString(),
      scope,project_id:p.projectId,feature_count:featureCollection.features.length,
      measurements,coordinate_system:'EPSG:4326',
      limitations:'Results retain original source accuracy. CSV/report are not independent survey certifications.',
     });
    }else throw Error('This format requires a saved project.');
   }
   if(epoch.current===generation)setMessage(background&&savedScope&&vectorFormat?'Export queued. The artifact will be available when complete.':'Export generated: '+format.toUpperCase()+'.');
  }catch(e){if(epoch.current===generation)setError(e instanceof Error?e.message:String(e));}
  finally{if(epoch.current===generation)setBusy(false);}
 }
 return <div className="export-workbench">
  <div className="data-metric-band">
   <div><small>Source</small><strong>{scope==='selection'?'Selection':
     scope==='local'?'Local drawings':scope==='areas'?'Enclosed areas':scope==='layer'?'Layer':scope==='viewport'?'Map view':'Project'}</strong></div>
   <div><small>Features</small><strong>{savedScope&&!preview&&scope!=='project'?'Inspect scope':count}</strong></div>
  </div>
  <label>Export scope
   <select aria-label="Export scope" value={scope} onChange={e=>setScope(e.target.value as ExportScope)}>
    <option value="selection">Current selection</option>
    <option value="areas">Detected closed areas</option>
    <option value="local">All local drawings</option>
    <option value="project" disabled={!p.projectId}>Active project · all records</option>
    <option value="layer" disabled={!p.projectId}>Project layer</option>
    <option value="viewport" disabled={!p.projectId||!p.viewport}>Project features in map view</option>
   </select>
  </label>
  {scope==='layer'&&<label>Project layer<select aria-label="Export project layer" value={layer} onChange={e=>setLayer(e.target.value)}>
   <option value="">Choose layer</option>{p.workspace?.layers.map(l=><option key={l.id} value={l.id}>{l.name}</option>)}
  </select></label>}
  <label>Output
   <select aria-label="Export format" value={format} onChange={e=>setFormat(e.target.value as ExportFormat)}>
    <optgroup label="Vector datasets">
     <option value="geojson">GeoJSON · WGS84</option>
     <option value="gpkg">GeoPackage</option>
     <option value="shapefile">Shapefile ZIP</option>
     <option value="kml">KML</option>
     <option value="gpx">GPX · points & lines</option>
    </optgroup>
    <optgroup label="Research outputs">
     <option value="csv">Attributes & measurements CSV</option>
     <option value="report">Measurements report JSON</option>
     <option value="pdf">Printable map PDF</option>
     <option value="geotiff">Analysis GeoTIFF</option>
     <option value="package">Portable project ZIP</option>
    </optgroup>
   </select>
  </label>
  {vectorFormat&&p.projectId&&<>
   <select aria-label="Export setup" value={setup} onChange={e=>setSetup(e.target.value as typeof setup)}>
    <option value="scope">Coordinates & precision</option><option value="fields">Attributes & checks</option><option value="delivery">Delivery</option>
   </select>
   {setup==='scope'&&<div className="data-input-pair">
    <label>Output CRS<input aria-label="Export target EPSG" value={['geojson','kml','gpx','report'].includes(format)?'EPSG:4326':targetCRS}
     disabled={['geojson','kml','gpx','report'].includes(format)} onChange={e=>setTargetCRS(e.target.value)}/></label>
    <label>Decimals<input aria-label="Export coordinate precision" type="number" min="0" max="15" placeholder="Full precision" value={precision} onChange={e=>setPrecision(e.target.value)}/></label>
   </div>}
   {setup==='fields'&&<>
    <small>{fields===null?'All source attributes are included.':fields.length+' fields selected.'}</small>
    {preview&&<label>Fields<select aria-label="Export attribute fields" multiple size={3} value={fields??preview.schema.map(f=>f.name)}
     onChange={e=>setFields(Array.from(e.target.selectedOptions,o=>o.value))}>
     {preview.schema.map(f=><option key={f.name}>{f.name}</option>)}
    </select></label>}
    <button type="button" onClick={()=>setFields(null)}>Include all fields</button>
   </>}
   {setup==='delivery'&&<label><input aria-label="Background dataset export" type="checkbox" disabled={!savedScope} checked={background&&savedScope} onChange={e=>setBackground(e.target.checked)}/> Prepare as background job</label>}
   <button type="button" disabled={busy||!canExport} onClick={()=>{
    const generation=epoch.current;abort.current?.abort();abort.current=new AbortController();setBusy(true);setError('');
    void preflightDatasetExport(p.projectId!,options(),abort.current.signal).then(r=>{if(epoch.current===generation)setPreview(r);})
     .catch(e=>{if(epoch.current===generation)setError(e instanceof Error?e.message:String(e));}).finally(()=>{if(epoch.current===generation)setBusy(false);});
   }}>Inspect export</button>
   {preview&&<small role="status">{preview.count.toLocaleString()} features · {preview.geometry_types.join(', ')} · {preview.target_crs}</small>}
   {preview?.warnings.map(w=><small key={w}>{w}</small>)}
  </>}
  {format==='package'&&<>
   <small>Saved features, layers, styles, CRS and revisions. Restore into a new empty project. Local unsaved drawings and browser analysis caches are excluded.</small>
   <label><input type="checkbox" aria-label="Include source GeoTIFFs" checked={includeRasters} onChange={e=>setIncludeRasters(e.target.checked)}/> Include loaded source GeoTIFFs ({p.rasterSources?.length??0})</label>
  </>}
  {format==='geotiff'&&<label>Raster result
   <select aria-label="GeoTIFF result" value={rasterIndex}
    onChange={e=>setRasterIndex(Number(e.target.value))}>
    {p.terrainRasters.map((r,i)=><option value={i} key={r.id}>{r.title}</option>)}
   </select>
  </label>}
  {format==='pdf'&&<div className="export-layout-options">
   <label>Title<input aria-label="Export map title" value={title} maxLength={120} onChange={e=>setTitle(e.target.value)}/></label>
   <div className="data-input-pair">
    <label>Paper<select aria-label="Export paper" value={paper} onChange={e=>setPaper(e.target.value as typeof paper)}>
     <option value="a4">A4</option><option value="a3">A3</option><option value="letter">Letter</option>
    </select></label>
    <label>Orientation<select aria-label="Export orientation" value={orientation} onChange={e=>setOrientation(e.target.value as typeof orientation)}>
     <option value="landscape">Landscape</option><option value="portrait">Portrait</option>
    </select></label>
   </div>
   <label>Extent<select aria-label="Export extent" value={extent} onChange={e=>setExtent(e.target.value as typeof extent)}>
    <option value="all">All visible features</option><option value="viewport">Current map view</option>
   </select></label>
   <div className="data-choice-buttons">
    <label><input type="checkbox" checked={grid} onChange={e=>setGrid(e.target.checked)}/> Grid</label>
    <label><input type="checkbox" checked={legend} onChange={e=>setLegend(e.target.checked)}/> Legend</label>
   </div>
  </div>}
  <button type="button" className="data-primary" onClick={()=>void run()}
   disabled={!canExport||busy||jobStarting||Boolean(job&&['queued','running'].includes(job.status))}>{busy||jobStarting?'Preparing…':'Export '+format.toUpperCase()}</button>
  {format!=='geotiff'&&count===0&&<small>No features in the current scope.</small>}
  {!p.projectId&&['gpkg','kml','gpx','shapefile'].includes(format)&&
    <small>Open a project to use the GIS conversion service.</small>}
  {job&&<div role="status">{job.status} · {job.progress}%
   <progress aria-label="Dataset export progress" max={100} value={job.progress}/>
   {['queued','running'].includes(job.status)&&<button type="button" onClick={()=>void cancelGISJob(p.projectId!,job.id).then(setJob).catch(e=>setError(String(e)))}>Cancel export</button>}
   {job.status==='completed'&&<button type="button" onClick={()=>void downloadExchangeJob(p.projectId!,job.id).catch(e=>setError(String(e)))}>Download dataset</button>}
  </div>}
  {message&&<small className="project-info" role="status">{message}</small>}
  {error&&<small className="discovery-error" role="alert">{error}</small>}
  {jobError&&<small className="discovery-error" role="alert">{jobError}</small>}
 </div>;
}
