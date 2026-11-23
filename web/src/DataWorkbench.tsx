import {useEffect,useRef,useState,type ChangeEvent} from 'react';
import {importVectorFile,uploadImagery,saveFeatureBatch,
 bufferGeometry,applyOverlay,transformProjectCoordinates,
 type NetworkPolygonization,type NetworkFace,type GeoWorkspace,type RasterAsset,
 type Measurement} from './api';
import DataServicesPanel,{type ExternalTile} from './DataServicesPanel';
import ApiAccessPanel from './ApiAccessPanel';
import DatasetImport from './DatasetImport';

type BBox=[number,number,number,number];
type DataPage='import'|'areas'|'process'|'sources'|'system';
interface Props{
 projectId:string|null;workspace:GeoWorkspace|null;viewport:BBox|null;
 geometry:GeoJSON.Geometry|null;network:NetworkPolygonization|null;
 networkNotice:string;sourceCount:number;connected:boolean;
 onRebuild:(tolerance:number,minArea:number)=>Promise<void>;
 onStoreAreas:(faces:NetworkFace[])=>void;onSelectArea:(id:string)=>void;onRefresh:()=>void;
 onTiles:(tiles:ExternalTile[])=>void;onPreview:(features:GeoJSON.Geometry[])=>void;
 onPage:(features:GeoWorkspace['features'])=>void;
 onRasterAdded:(asset:RasterAsset,kind:'dem'|'image')=>void;
 onOpenLayers:()=>void;
 vectorSources:Array<{id:string;name:string;geometry:GeoJSON.Geometry}>;
 onDerived:(geometry:GeoJSON.Geometry,measurement:Measurement,name:string)=>void;
}
const fmt=(v:number)=>v.toLocaleString('en-US',{maximumFractionDigits:2});
export default function DataWorkbench(p:Props){
 const [page,setPage]=useState<DataPage>('areas');
 const [systemView,setSystemView]=useState<'database'|'jobs'|'access'>('database');
 const [operation,setOperation]=useState<'union'|'intersection'|'difference'|'buffer'|'reproject'>('union');
 const [reference,setReference]=useState('');
 const [bufferMeters,setBufferMeters]=useState('100');
 const [longitude,setLongitude]=useState('');
 const [latitude,setLatitude]=useState('');
 const [targetCRS,setTargetCRS]=useState('EPSG:3857');
 const [projected,setProjected]=useState<{crs:string;x:number;y:number}|null>(null);
 const [file,setFile]=useState<File|null>(null);
 const [kind,setKind]=useState<'vector'|'raster'|'batch'>('vector');
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
 const epoch=useRef(0);
 useEffect(()=>{epoch.current++;setBusy(false);setReference('');setProjected(null);setFile(null);setLayer('');setStatus('');setError('');},[p.projectId]);
 useEffect(()=>setAreaPage(0),[p.network?.faces]);
 async function action(task:()=>Promise<void>){
  if(busy)return;setBusy(true);setError('');setStatus('');
  const generation=epoch.current;
  try{await task();}
  catch(e){if(epoch.current===generation)setError(e instanceof Error?e.message:String(e));}
  finally{if(epoch.current===generation)setBusy(false);}
 }
 async function importDataset(){
  const source=file,scope=p.projectId,generation=epoch.current;
  if(!source)throw Error('Choose a file.');
  if(kind==='vector'){
   if(!scope)throw Error('Select or create a project before vector import.');
   if(source.size===0||source.size>128*1024*1024)
    throw Error('Vector files must be non-empty and no larger than 128 MB.');
   if(!/\.(json|geojson|csv|gpkg|kml|gpx|zip)$/i.test(source.name))
    throw Error('Supported: GeoJSON, CSV, GPKG, KML, GPX or zipped Shapefile.');
   const result=await importVectorFile(scope,source,layer||undefined);
   if(latest.current!==scope||epoch.current!==generation)return;
   p.onRefresh();setStatus('Imported '+result.created+' validated features.');
  }else{
   const asset=await uploadImagery(source,token);
   if(latest.current!==scope||epoch.current!==generation)return;
   p.onRasterAdded(asset,rasterKind);setStatus('Imported georeferenced raster: '+asset.name);
  }
  setFile(null);
 }
 function acceptFile(event:ChangeEvent<HTMLInputElement>){
  setFile(event.currentTarget.files?.[0]??null);
  setError('');setStatus('');
 }
 async function saveProjectFaces(){
  const faces=p.network?.faces??[],scope=p.projectId,generation=epoch.current;
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
  if(latest.current!==scope||epoch.current!==generation)return;
  p.onRefresh();setStatus('Saved '+output.created+' independently measured polygon faces.');
 }
 return <div className="data-workbench">
  <nav aria-label="Data operations" className="data-page-buttons">
   {([['import','Import'],['areas','Areas'],['process','Process'],
      ['sources','Sources'],['system','System']] as const).map(([key,name])=>
      <button type="button" key={key} aria-pressed={page===key}
       onClick={()=>{setPage(key);setError('');}}>{name}</button>)}
  </nav>
  <div className="data-page" hidden={page!=='import'}>
   <strong>Import dataset</strong>
   <div className="data-choice-buttons">
    <button type="button" aria-pressed={kind==='vector'} onClick={()=>{setKind('vector');setFile(null);}}>Vector</button>
    <button type="button" aria-pressed={kind==='raster'} onClick={()=>{setKind('raster');setFile(null);}}>GeoTIFF</button>
    <button type="button" aria-pressed={kind==='batch'} onClick={()=>{setKind('batch');setFile(null);}}>Advanced import</button>
   </div>
   {kind==='batch'?<DatasetImport projectId={p.projectId} workspace={p.workspace} onRefresh={p.onRefresh} onRasterAdded={p.onRasterAdded}/>:<>
   <input aria-label="Import dataset file" type="file" value="" onChange={acceptFile}
    accept={kind==='vector'?'.json,.geojson,.csv,.gpkg,.kml,.gpx,.zip':
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
   </>}
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
       <span>{fmt((f.measurement.area_m2??0)/1e6)} km²</span>
       <small>{fmt((f.measurement.perimeter_m??0)/1000)} km perimeter</small>
        <button type="button" aria-label={'Select enclosed area '+f.name}
          onClick={()=>p.onSelectArea(f.id)}>Select & measure</button>
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
  <div className="data-page" hidden={page!=='process'}>
   <label>Operation
    <select aria-label="Data processing operation" value={operation}
     onChange={e=>{setOperation(e.target.value as typeof operation);setProjected(null);}}>
     <option value="union">Merge / union polygons</option>
     <option value="intersection">Intersect polygons</option>
     <option value="difference">Subtract polygon</option>
     <option value="buffer">Geodesic buffer</option>
     <option value="reproject">Convert coordinates</option>
    </select>
   </label>
   {(['union','intersection','difference'].includes(operation))&&<label>Second polygon
    <select aria-label="Processing reference feature" value={reference}
     onChange={e=>setReference(e.target.value)}>
     <option value="">Select another polygon</option>
     {p.vectorSources.filter(item=>
       (item.geometry.type==='Polygon'||item.geometry.type==='MultiPolygon')&&
       JSON.stringify(item.geometry)!==JSON.stringify(p.geometry))
       .map(item=><option value={item.id} key={item.id}>{item.name}</option>)}
    </select>
   </label>}
   {operation==='buffer'&&<label>Distance (meters)
    <input aria-label="Processing buffer distance" type="number" min=".001" max="100000"
     value={bufferMeters} onChange={e=>setBufferMeters(e.target.value)}/>
   </label>}
   {operation==='reproject'&&<>
    <div className="data-input-pair">
     <label>Longitude<input aria-label="Source longitude" type="number" step="any"
      value={longitude} onChange={e=>setLongitude(e.target.value)}/></label>
     <label>Latitude<input aria-label="Source latitude" type="number" step="any"
      value={latitude} onChange={e=>setLatitude(e.target.value)}/></label>
    </div>
    <label>Target CRS<input aria-label="Target EPSG" value={targetCRS}
     onChange={e=>setTargetCRS(e.target.value)} placeholder="EPSG:3857"/></label>
    {projected&&<div className="data-area-rows"><div>
     <strong>{projected.crs}</strong><span>{fmt(projected.x)}, {fmt(projected.y)}</span>
    </div></div>}
   </>}
   <button type="button" className="data-primary" disabled={busy||!p.connected||
     (operation==='reproject'?!p.projectId:
      !p.geometry||(['union','intersection','difference'].includes(operation)&&!reference))}
    onClick={()=>void action(async()=>{
      const current=p.projectId,generation=epoch.current;
      if(operation==='reproject'){
       if(!p.projectId)throw Error('Select a project to use the CRS conversion service.');
       if(!longitude.trim()||!latitude.trim()||
          !Number.isFinite(Number(longitude))||!Number.isFinite(Number(latitude)))
        throw Error('Enter valid geographic coordinates.');
       if(Math.abs(Number(longitude))>180||Math.abs(Number(latitude))>90)
        throw Error('Source WGS84 longitude/latitude is out of range.');
       if(!/^EPSG:\d{3,6}$/i.test(targetCRS.trim()))
        throw Error('Target CRS must be an EPSG code.');
       const result=await transformProjectCoordinates(p.projectId,
        [[Number(longitude),Number(latitude)]],targetCRS.toUpperCase());
       if(latest.current!==current||epoch.current!==generation)return;
       setProjected({crs:result.target,x:result.coordinates[0][0],y:result.coordinates[0][1]});
       setStatus('Coordinate transformed. Source remains unchanged.');
      }else{
       if(!p.geometry)throw Error('Select a geometry to process.');
       const result=operation==='buffer'?
        await bufferGeometry(p.geometry,Number(bufferMeters)):
        await applyOverlay(operation,p.geometry,
         p.vectorSources.find(item=>item.id===reference)!.geometry);
       if(latest.current!==current||epoch.current!==generation)return;
       if(!result.geometry||!result.measurement)
        throw Error('Operation returned no valid area.');
       p.onDerived(result.geometry,result.measurement,operation+' derived feature');
       setStatus('Created independent output; source geometries are unchanged.');
      }
    })}>{busy?'Processing…':'Run '+operation}</button>
  </div>
  <div className="data-page" hidden={page!=='system'}>
   <label>System operation<select aria-label="Data system operation" value={systemView}
    onChange={e=>setSystemView(e.target.value as typeof systemView)}>
    <option value="database">Spatial index / PostGIS</option>
    <option value="jobs">Background jobs</option>
    <option value="access">API access</option>
   </select></label>
   <div hidden={systemView!=='access'}><ApiAccessPanel/></div>
  </div>
  <div className="data-page data-services-page" hidden={
    !((page==='sources')||(page==='system'&&systemView!=='access'))}>
   <DataServicesPanel key={p.projectId??'no-project'}
    view={page==='sources'?'sources':systemView==='database'?'database':'jobs'}
    projectId={p.projectId} viewport={p.viewport} drawnGeometry={p.geometry}
    onTiles={p.onTiles} onPreview={p.onPreview} onPage={p.onPage}
    onRefresh={p.onRefresh}/>
  </div>
  {status&&<small className="project-info" role="status">{status}</small>}
  {error&&<small className="discovery-error" role="alert">{error}</small>}
 </div>;
}
