import {useEffect,useRef,useState,type ChangeEvent} from 'react';
import {importVectorFile,uploadImagery,saveFeatureBatch,
  type NetworkPolygonization,type NetworkFace,type GeoWorkspace,type RasterAsset} from './api';
import DataServicesPanel,{type ExternalTile} from './DataServicesPanel';
import ApiAccessPanel from './ApiAccessPanel';

type BBox=[number,number,number,number];
type DataPage='import'|'areas'|'sources'|'database'|'jobs'|'access';
interface Props{
 projectId:string|null;workspace:GeoWorkspace|null;viewport:BBox|null;
 geometry:GeoJSON.Geometry|null;network:NetworkPolygonization|null;
 networkNotice:string;sourceCount:number;connected:boolean;
 onRebuild:(tolerance:number,minArea:number)=>Promise<void>;
 onStoreAreas:(faces:NetworkFace[])=>void;onRefresh:()=>void;
 onTiles:(tiles:ExternalTile[])=>void;onPreview:(features:GeoJSON.Geometry[])=>void;
 onPage:(features:GeoWorkspace['features'])=>void;
 onRasterAdded:(asset:RasterAsset,kind:'dem'|'image')=>void;
 onOpenLayers:()=>void;
}
const fmt=(v:number)=>v.toLocaleString('en-US',{maximumFractionDigits:2});
export default function DataWorkbench(p:Props){
 const [page,setPage]=useState<DataPage>('areas');
 const [file,setFile]=useState<File|null>(null);
 const [kind,setKind]=useState<'vector'|'raster'>('vector');
 const [rasterKind,setRasterKind]=useState<'dem'|'image'>('dem');
 const [layer,setLayer]=useState('');
 const [token,setToken]=useState('');
 const [tolerance,setTolerance]=useState('1');
 const [minimum,setMinimum]=useState('0.01');
 const [areaPage,setAreaPage]=useState(0);
 const [busy,setBusy]=useState(false);
 const [status,setStatus]=useState('');
 const [error,setError]=useState('');
 const latest=useRef(p.projectId);latest.current=p.projectId;
 useEffect(()=>{setFile(null);setLayer('');setStatus('');setError('');},[p.projectId]);
 useEffect(()=>setAreaPage(0),[p.network?.faces]);
 async function action(task:()=>Promise<void>){
  if(busy)return;setBusy(true);setError('');setStatus('');
  try{await task();}
  catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 async function importDataset(){
  const source=file,scope=p.projectId;
  if(!source)throw Error('Choose a file.');
  if(kind==='vector'){
   if(!scope)throw Error('Select or create a project before vector import.');
   if(source.size===0||source.size>25*1024*1024)
    throw Error('Vector files must be non-empty and no larger than 25 MB.');
   if(!/\.(geojson|gpkg|kml|gpx|zip)$/i.test(source.name))
    throw Error('Supported: GeoJSON, GPKG, KML, GPX or zipped Shapefile.');
   const result=await importVectorFile(scope,source,layer||undefined);
   if(latest.current!==scope)return;
   p.onRefresh();setStatus('Imported '+result.created+' validated features.');
  }else{
   const asset=await uploadImagery(source,token);
   if(latest.current!==scope)return;
   p.onRasterAdded(asset,rasterKind);setStatus('Imported georeferenced raster: '+asset.name);
  }
  setFile(null);
 }
 function acceptFile(event:ChangeEvent<HTMLInputElement>){
  setFile(event.currentTarget.files?.[0]??null);
  setError('');setStatus('');
 }
 async function saveProjectFaces(){
  const faces=p.network?.faces??[],scope=p.projectId;
  if(!scope||!faces.length)throw Error('Create a project and detect enclosed areas first.');
  const selected=faces.filter(face=>!(p.workspace?.features??[]).some(saved=>
   saved.properties?.source_type==='polygonized_network'&&
   JSON.stringify(saved.geometry)===JSON.stringify(face.geometry)));
  if(!selected.length){setStatus('These enclosed areas are already saved in this project.');return;}
  if(selected.length>100)throw Error('Save up to 100 polygon faces at a time; subdivide the network first.');
  const output=await saveFeatureBatch(scope,selected.map(f=>({
   name:f.name,source:'GeoFathom network polygonization',geometry:f.geometry,
   properties:{...f.properties,method:p.network?.method},
  })),layer||undefined);
  if(latest.current!==scope)return;
  p.onRefresh();setStatus('Saved '+output.created+' independently measured polygon faces.');
 }
 return <div className="data-workbench">
  <nav aria-label="Data operations" className="data-page-buttons">
   {([['import','Import'],['areas','Areas'],['sources','Sources'],
      ['database','Database'],['jobs','Jobs'],['access','Access']] as const).map(([key,name])=>
      <button type="button" key={key} aria-pressed={page===key}
       onClick={()=>{setPage(key);setError('');}}>{name}</button>)}
  </nav>
  <div className="data-page" hidden={page!=='import'}>
   <strong>Import dataset</strong>
   <div className="data-choice-buttons">
    <button type="button" aria-pressed={kind==='vector'} onClick={()=>{setKind('vector');setFile(null);}}>Vector</button>
    <button type="button" aria-pressed={kind==='raster'} onClick={()=>{setKind('raster');setFile(null);}}>GeoTIFF</button>
   </div>
   <input aria-label="Import dataset file" type="file" value="" onChange={acceptFile}
    accept={kind==='vector'?'.geojson,.gpkg,.kml,.gpx,.zip':
      '.tif,.tiff,image/tiff'}/>
   {file&&<small>{file.name} · {fmt(file.size/1024/1024)} MB</small>}
   {kind==='raster'&&<label>Raster type
    <select aria-label="Imported raster kind" value={rasterKind}
     onChange={e=>setRasterKind(e.target.value as typeof rasterKind)}>
     <option value="dem">Elevation / DEM</option><option value="image">Imagery / other bands</option>
    </select>
   </label>}
   {kind==='vector'?<label>Target layer
    <select aria-label="Data import layer" value={layer} onChange={e=>setLayer(e.target.value)}>
     <option value="">Project default</option>
     {(p.workspace?.layers??[]).filter(l=>!l.locked).map(l=>
      <option value={l.id} key={l.id}>{l.name}</option>)}
    </select>
   </label>:<label>Import access token
    <input type="password" autoComplete="off" aria-label="Raster import token"
      value={token} onChange={e=>setToken(e.target.value)}/>
   </label>}
   <button className="data-primary" disabled={busy||!file||(kind==='vector'&&!p.projectId)}
    onClick={()=>void action(importDataset)}>{busy?'Importing…':'Import & validate'}</button>
   <button type="button" onClick={p.onOpenLayers}>Manage project layers</button>
  </div>
  <div className="data-page" hidden={page!=='areas'}>
   <div className="data-metric-band">
    <div><small>Closed areas</small><strong>{p.network?.count??0}</strong></div>
    <div><small>Total area</small><strong>{fmt((p.network?.area_m2??0)/1e6)} km²</strong></div>
   </div>
   <div className="data-input-pair">
    <label>Snap (m)<input aria-label="Network snap tolerance" type="number"
     value={tolerance} min="0" max="20" step=".1" onChange={e=>setTolerance(e.target.value)}/></label>
    <label>Min area (m²)<input aria-label="Network minimum area" type="number"
     value={minimum} min="0" step=".01" onChange={e=>setMinimum(e.target.value)}/></label>
   </div>
   <button type="button" className="data-primary" disabled={!p.connected||busy||p.sourceCount===0}
    onClick={()=>void action(async()=>{
     const t=Number(tolerance),a=Number(minimum);
     if(!Number.isFinite(t)||t<0||t>20||!Number.isFinite(a)||a<0||a>1e10)
      throw Error('Use a snap of 0–20 m and a nonnegative finite minimum area.');
     await p.onRebuild(t,a);
    })}>Detect enclosed areas</button>
   {p.network&&<>
    <div className="data-quality-strip">
     <span>Open ends: {p.network.dangles}</span><span>Cuts: {p.network.cuts}</span>
     <span>Invalid rings: {p.network.invalid_rings}</span>
    </div>
    <div className="data-area-rows">
     {p.network.faces.slice(areaPage*4,(areaPage+1)*4).map(f=>
      <div key={f.id}><strong>{f.name}</strong>
       <span>{fmt(f.measurement.area_m2/1e6)} km²</span>
       <small>{fmt(f.measurement.perimeter_m/1000)} km perimeter</small>
      </div>)}
    </div>
    {p.network.count>4&&<div className="gis-record-pager">
     <button type="button" disabled={areaPage===0} onClick={()=>setAreaPage(v=>v-1)}>Previous</button>
     <span>{areaPage+1} / {Math.ceil(p.network.count/4)}</span>
     <button type="button" disabled={(areaPage+1)*4>=p.network.count} onClick={()=>setAreaPage(v=>v+1)}>Next</button>
    </div>}
    <button type="button" disabled={busy||!p.network.count}
     onClick={()=>p.onStoreAreas(p.network!.faces)}>Keep areas locally</button>
    <button type="button" disabled={busy||!p.projectId||!p.network.count||p.network.count>100}
     onClick={()=>void action(saveProjectFaces)}>Save areas to project</button>
   </>}
   {p.networkNotice&&<small className="data-status">{p.networkNotice}</small>}
  </div>
  <div className="data-page data-services-page" hidden={!['sources','database','jobs'].includes(page)}>
   <DataServicesPanel key={p.projectId??'no-project'} view={
    page==='sources'?'sources':page==='database'?'database':'jobs'}
    projectId={p.projectId} viewport={p.viewport} drawnGeometry={p.geometry}
    onTiles={p.onTiles} onPreview={p.onPreview} onPage={p.onPage}
    onRefresh={p.onRefresh}/>
  </div>
  <div className="data-page" hidden={page!=='access'}>
   <ApiAccessPanel/>
  </div>
  {status&&<small className="project-info" role="status">{status}</small>}
  {error&&<small className="discovery-error" role="alert">{error}</small>}
 </div>;
}
