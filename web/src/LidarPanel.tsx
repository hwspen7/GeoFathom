import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {getLidarCatalog,runLidar,type LidarMethod,type LidarResult} from './api';
import {saveFigureBlob} from './figureExport';
import ScientificFigureStudio from './ScientificFigureStudio';
import LidarCloudView from './LidarCloudView';

export default function LidarPanel({active,connected,resultsTarget}:{active:boolean;connected:boolean;resultsTarget?:HTMLElement|null}){
 const [methods,setMethods]=useState<LidarMethod[]>([]),[operation,setOperation]=useState('quality');
 const [cloud,setCloud]=useState<File|null>(null),[reference,setReference]=useState<File|null>(null);
 const [epsg,setEpsg]=useState(''),[datum,setDatum]=useState(''),[confirmed,setConfirmed]=useState(false);
 const [k,setK]=useState(16),[size,setSize]=useState(1),[radius,setRadius]=useState(2),[edge,setEdge]=useState(10);
 const [result,setResult]=useState<LidarResult|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[studio,setStudio]=useState(false);
 const request=useRef<AbortController|null>(null);
 const [trim,setTrim]=useState(.8),[iterations,setIterations]=useState(60),[tolerance,setTolerance]=useState(.00001),[sigma,setSigma]=useState(.05),[minimum,setMinimum]=useState(5),[threshold,setThreshold]=useState(3.5);
 const needsReference=['cloud_distance','surface_change','ground_height','rigid_registration','normal_change','canopy_structure','point_plane_icp','crown_candidates','correlated_change','coarse_pca','generalized_icp'].includes(operation);
 useEffect(()=>()=>request.current?.abort(),[]);
 useEffect(()=>{if(!active||!connected)return;const ac=new AbortController();getLidarCatalog(ac.signal).then(x=>{if(!ac.signal.aborted)setMethods(x.operations);}).catch(e=>{if(!ac.signal.aborted)setError(String(e.message));});return()=>ac.abort();},[active,connected]);
 function invalidate(){request.current?.abort();request.current=null;setBusy(false);setResult(null);setStudio(false);setError('');}
 async function run(){
   if(!cloud||!confirmed||!datum.trim()||!epsg.trim()||(needsReference&&!reference))return;
   invalidate();const ac=new AbortController();request.current=ac;setBusy(true);
   try{
     const r=await runLidar({operation,epsg,vertical_datum:datum,k:String(k),size:String(size),radius:String(radius),max_edge:String(edge),trim_fraction:String(trim),max_iterations:String(iterations),tolerance:String(tolerance),registration_sigma:String(sigma),min_neighbors:String(minimum),threshold:String(threshold)},cloud,needsReference?reference:null,ac.signal);
     if(!ac.signal.aborted)setResult(r);
   }catch(e){if(!ac.signal.aborted)setError(e instanceof Error?e.message:String(e));}
   finally{if(!ac.signal.aborted)setBusy(false);}
 }
 const columns=result?.columns??[];
 const zField=columns.includes('z_m')?'z_m':columns.includes('current_z_m')?'current_z_m':columns.includes('p95_m')?'p95_m':'';
 const xyz=columns.includes('x_m')&&columns.includes('y_m')&&Boolean(zField);
 const output=result&&<section className="panel-section" aria-label="3D and LiDAR results">
   <div className="section-heading"><span>{methods.find(m=>m.id===result.operation)?.title??result.operation}</span></div>
   <small>{result.assumption}</small>
   <dl>{Object.entries(result.metrics).map(([key,val])=><div key={key}><dt>{key.replaceAll('_',' ')}</dt><dd>{JSON.stringify(val)}</dd></div>)}</dl>
   {xyz&&<LidarCloudView csv={result.figure_csv} columns={columns} zField={zField}/>}
   <small>{result.row_count.toLocaleString()} result rows · preview up to 10</small>
   <div style={{overflowX:'auto'}}><table><thead><tr>{columns.map(c=><th key={c}>{c}</th>)}</tr></thead><tbody>{result.rows.slice(0,10).map((r,i)=><tr key={i}>{r.map((v,j)=><td key={j}>{v===null?'—':Number(v.toPrecision(7))}</td>)}</tr>)}</tbody></table></div>
   <button onClick={()=>saveFigureBlob(new Blob([result.csv],{type:'text/csv'}),'lidar-'+result.operation+'.csv')}>Export full CSV</button>
   <button onClick={()=>saveFigureBlob(new Blob([JSON.stringify(result.receipt,null,2)],{type:'application/json'}),'lidar-receipt.json')}>Export provenance</button>
   {result.mesh_obj&&<button onClick={()=>saveFigureBlob(new Blob([result.mesh_obj!],{type:'text/plain'}),'lidar-'+result.operation+'.obj')}>Export mesh OBJ</button>}
   {result.raster_geotiff&&<button onClick={()=>saveFigureBlob(new Blob([Uint8Array.from(atob(result.raster_geotiff!),c=>c.charCodeAt(0))],{type:'image/tiff'}),'lidar-'+result.operation+'.tif')}>Export GeoTIFF</button>}
   <button onClick={()=>setStudio(true)}>Scientific Figure Studio</button>
   {studio&&<ScientificFigureStudio initialTier="all" source={{name:'LiDAR '+result.operation,csv:result.figure_csv,provenance:result.receipt,initialRecipe:xyz?'scatter_3d':undefined,initialBindings:xyz?{x:'x_m',y:'y_m',z:zField}:undefined}} onClose={()=>setStudio(false)}/>}
 </section>;
 return <>
   <label>Point cloud (LAS or XYZ CSV)<input type="file" accept=".las,.laz,.csv" onChange={e=>{setCloud(e.target.files?.[0]??null);setConfirmed(false);invalidate();}}/></label>
   <label>Analysis method<select value={operation} onChange={e=>{const op=e.target.value;setOperation(op);setThreshold(op==='generalized_icp' ? .01 : op==='roof_planes' ? .1 : ['ground_filter','progressive_morphology','progressive_tin'].includes(op) ? .3 : ['canopy_structure','crown_candidates'].includes(op) ? 2 : 3.5);invalidate();}}>{methods.map(m=><option key={m.id} value={m.id}>{m.title}</option>)}</select></label>
   {needsReference&&<label>Reference cloud (ground points for normalized height)<input type="file" accept=".las,.laz,.csv" onChange={e=>{setReference(e.target.files?.[0]??null);setConfirmed(false);invalidate();}}/></label>}
   <label>Projected EPSG (metres)<input type="number" min="1" value={epsg} onChange={e=>{setEpsg(e.target.value);setConfirmed(false);invalidate();}}/></label>
   <label>Vertical datum / height reference<input value={datum} onChange={e=>{setDatum(e.target.value);setConfirmed(false);invalidate();}}/></label>
   <label><input type="checkbox" checked={confirmed} onChange={e=>{setConfirmed(e.target.checked);invalidate();}}/> All input XYZ coordinates are in metres and share this horizontal CRS and vertical reference.</label>
   {['local_geometry','robust_outlier','normal_change','point_plane_icp','roof_planes','generalized_icp','poisson_grid'].includes(operation)&&<label>{operation==='roof_planes'?'Maximum planes (capped at 32)':'Neighbors'}<input type="number" min="3" max="64" value={k} onChange={e=>{setK(Number(e.target.value));invalidate();}}/></label>}
   {['voxel','vertical_profile','surface_change','normal_change','canopy_structure','ground_filter','crown_candidates','stream_voxels','correlated_change','progressive_morphology','progressive_tin','poisson_grid'].includes(operation)&&<label>Grid / bin size (m)<input type="number" min=".001" step="any" value={size} onChange={e=>{setSize(Number(e.target.value));invalidate();}}/></label>}
   {['density','rigid_registration','normal_change','point_plane_icp','ground_filter','alpha_boundary','crown_candidates','correlated_change','progressive_morphology','coarse_pca','generalized_icp','progressive_tin'].includes(operation)&&<label>{['rigid_registration','point_plane_icp','coarse_pca','generalized_icp'].includes(operation)?'Maximum correspondence distance (m)':operation==='normal_change'?'Cylinder radius (m)':operation==='alpha_boundary'?'Alpha radius (m)':operation==='correlated_change'?'Registration correlation length (m)':operation==='crown_candidates'?'Apex suppression / assignment radius (m)':'Neighborhood radius (m)'}<input type="number" min=".001" step="any" value={radius} onChange={e=>{setRadius(Number(e.target.value));invalidate();}}/></label>}
   {['ground_height','canopy_structure','normal_change','tin_mesh','crown_candidates'].includes(operation)&&<label>{operation==='normal_change'?'Cylinder half depth (m)':'Maximum triangle edge (m)'}<input type="number" min=".001" step="any" value={edge} onChange={e=>{setEdge(Number(e.target.value));invalidate();}}/></label>}
   {['rigid_registration','point_plane_icp','coarse_pca','generalized_icp'].includes(operation)&&<><label>Trim fraction<input type="number" min=".5" max="1" step=".05" value={trim} onChange={e=>{setTrim(Number(e.target.value));invalidate();}}/></label><label>Maximum iterations<input type="number" min="1" max="100" value={iterations} onChange={e=>{setIterations(Number(e.target.value));invalidate();}}/></label><label>Convergence tolerance (m)<input type="number" min=".000000001" step="any" value={tolerance} onChange={e=>{setTolerance(Number(e.target.value));invalidate();}}/></label></>}
   {['normal_change','correlated_change'].includes(operation)&&<><label>Registration uncertainty, one sigma (m)<input type="number" min="0" step="any" value={sigma} onChange={e=>{setSigma(Number(e.target.value));invalidate();}}/></label><label>Minimum returns per epoch<input type="number" min="3" max="1000" value={minimum} onChange={e=>{setMinimum(Number(e.target.value));invalidate();}}/></label></>}
   {['robust_outlier','canopy_structure','ground_filter','roof_planes','crown_candidates','progressive_morphology','generalized_icp','progressive_tin'].includes(operation)&&<label>{operation==='robust_outlier'?'Robust z threshold':operation==='roof_planes'?'Plane residual tolerance (m)':operation==='generalized_icp'?'Covariance noise floor (m)': ['ground_filter','progressive_morphology','progressive_tin'].includes(operation)?'Ground height tolerance (m)':'Height threshold (m)'}<input type="number" min="0" step="any" value={threshold} onChange={e=>{setThreshold(Number(e.target.value));invalidate();}}/></label>}
   {operation==='roof_planes'&&<><label>RANSAC trials per plane<input type="number" min="1" max="100" value={iterations} onChange={e=>{setIterations(Number(e.target.value));invalidate();}}/></label><label>Minimum plane points<input type="number" min="3" max="1000" value={minimum} onChange={e=>{setMinimum(Number(e.target.value));invalidate();}}/></label></>}
   <small>{operation==='stream_voxels'?'LAS/LAZ: up to 10 million points, 512 MiB and 100,000 occupied voxels. Requires LiDAR extension.':'100,000 points and 16 MiB per file; LAZ requires LiDAR extension.'} No automatic vertical datum conversion.</small>
   <button disabled={!connected||busy||!cloud||!epsg||!datum.trim()||!confirmed||!methods.length||(needsReference&&!reference)} onClick={()=>void run()}>{busy?'Analyzing…':'Run 3D analysis'}</button>
   {busy&&<button onClick={invalidate}>Cancel request</button>}{error&&<p role="alert">{error}</p>}
   {active&&output&&(resultsTarget?createPortal(output,resultsTarget):output)}
 </>;
}
