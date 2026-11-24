import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {getNetworkScienceCatalog,runNetworkScience,getSpatialLayerSource,getSpatialRasterSource,type NetworkMethod,type NetworkScienceResult,type NetworkScienceInput,type SpatialFigureSource} from './api';
import {saveFigureBlob} from './figureExport';
import ScientificFigureStudio from './ScientificFigureStudio';

const ids=(text:string)=>text.split(/\n/).map(x=>x.trim()).filter(Boolean);
function numericMap(text:string):Record<string,number>{
 const value=JSON.parse(text||'{}');
 if(!value||typeof value!=='object'||Array.isArray(value)||Object.values(value).some(x=>typeof x!=='number'||!Number.isFinite(x)||x<=0))throw Error('Use a JSON object of positive numeric weights.');
 return value;
}
function download(text:string,name:string,type:string){saveFigureBlob(new Blob([text],{type}),name);}
function graph(raw:unknown):GeoJSON.FeatureCollection{
 const x=raw as GeoJSON.FeatureCollection;
 if(x?.type!=='FeatureCollection'||!Array.isArray(x.features)||!x.features.length||x.features.some(f=>f.geometry?.type!=='LineString'))throw Error('Use a WGS84 GeoJSON FeatureCollection of pre-noded LineStrings.');
 return x;
}
export default function NetworkSciencePanel({active,connected,resultsTarget,projectId,layers,assets,onPreview}:{active:boolean;connected:boolean;resultsTarget?:HTMLElement|null;projectId?:string|null;layers:Array<{id:string;name:string}>;assets:Array<{id:string;name:string}>;onPreview:(features:GeoJSON.Feature[])=>void}){
 const [open,setOpen]=useState(false),[methods,setMethods]=useState<NetworkMethod[]>([]),[operation,setOperation]=useState('topology');
 const [network,setNetwork]=useState<GeoJSON.FeatureCollection|null>(null),[name,setName]=useState(''),[layer,setLayer]=useState(''),[asset,setAsset]=useState('');
 const [raster,setRaster]=useState<{data:string;name:string}|null>(null),[band,setBand]=useState(1);
 const [cost,setCost]=useState('length_m'),[unit,setUnit]=useState('cost'),[origins,setOrigins]=useState(''),[destinations,setDestinations]=useState('');
 const [demand,setDemand]=useState('{}'),[supply,setSupply]=useState('{}'),[closed,setClosed]=useState(''),[multipliers,setMultipliers]=useState('{}');
 const [threshold,setThreshold]=useState(1000),[beta,setBeta]=useState(.001),[spacing,setSpacing]=useState(30),[coverage,setCoverage]=useState(1),[hazard,setHazard]=useState(.5);
 const [testEdges,setTestEdges]=useState(''),[failure,setFailure]=useState('{}'),[trials,setTrials]=useState(200),[seed,setSeed]=useState(42);
 const [result,setResult]=useState<NetworkScienceResult|null>(null),[nodeIds,setNodeIds]=useState<string[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const [figure,setFigure]=useState<SpatialFigureSource|null>(null),[studio,setStudio]=useState(false);
 const request=useRef<AbortController|null>(null),dialog=useRef<HTMLDivElement>(null),mounted=useRef(true);
 const method=methods.find(m=>m.id===operation);
 const usesOrigin=['shortest_path','od_matrix','service_area','nearest_facility','gravity_access','two_step_fca','scenario_impact','circuity','edge_criticality','stochastic_reliability'].includes(operation);
 const usesDest=usesOrigin&&operation!=='service_area',usesSupply=['gravity_access','two_step_fca'].includes(operation),usesRaster=['hazard_exposure','scenario_impact'].includes(operation);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;request.current?.abort();};},[]);
 useEffect(()=>{if(!active&&!open)return;const ac=new AbortController();getNetworkScienceCatalog(ac.signal).then(x=>{if(!ac.signal.aborted)setMethods(x.operations);}).catch(e=>{if(!ac.signal.aborted)setError(String(e.message));});return()=>ac.abort();},[active,open]);
 useEffect(()=>{if(!open)return;const previous=document.activeElement as HTMLElement|null;dialog.current?.focus();return()=>previous?.focus();},[open]);
 function invalidate(){setResult(null);setError('');}
 function load(raw:unknown,label:string){setNetwork(graph(raw));setName(label);setNodeIds([]);setOrigins('');setDestinations('');invalidate();onPreview([]);}
 function close(){request.current?.abort();request.current=null;setBusy(false);setOpen(false);}
 async function importGraph(file:File){try{if(file.size>8_000_000)throw Error('Network exceeds 8 MB.');const raw=JSON.parse(await file.text());if(mounted.current)load(raw,file.name);}catch(e){if(mounted.current)setError(String((e as Error).message));}}
 async function importRaster(file:File){try{if(file.size>12_000_000)throw Error('Raster exceeds 12 MB.');const reader=new FileReader();reader.onload=()=>{if(mounted.current){setRaster({name:file.name,data:String(reader.result).split(',')[1]});setBand(1);invalidate();}};reader.onerror=()=>setError('Raster read failed.');reader.readAsDataURL(file);}catch(e){setError(String((e as Error).message));}}
 async function run(kind=operation){
  if(!network||busy)return;const ac=new AbortController();request.current=ac;setBusy(true);setError('');setResult(null);
  try{
   const analyze=kind!=='topology',scenario=kind==='scenario_impact',exposure=kind==='hazard_exposure'||scenario;
   const body:NetworkScienceInput={operation:kind,network,cost_field:cost,cost_unit:unit,origins:analyze&&usesOrigin?ids(origins):[],destinations:analyze&&usesDest?ids(destinations):[],demand:analyze&&kind==='two_step_fca'?numericMap(demand):{},supply:analyze&&usesSupply?numericMap(supply):{},threshold,beta,closed_edges:scenario?ids(closed):[],multipliers:scenario?numericMap(multipliers):{},test_edges:kind==='edge_criticality'?ids(testEdges):[],failure_probability:kind==='stochastic_reliability'?JSON.parse(failure):{},trials,seed,spacing_m:spacing,minimum_coverage:coverage,hazard_threshold:hazard,...(exposure&&raster?{raster:{data:raster.data,band}}:{})};
   const out=await runNetworkScience(body,ac.signal);if(ac.signal.aborted||!mounted.current)return;
   setResult(out);if(kind==='topology'){setNodeIds(out.rows.map(r=>String(r[0])));setOperation('topology');}
  }catch(e){if(!ac.signal.aborted&&mounted.current)setError(String((e as Error).message));}finally{if(request.current===ac){request.current=null;setBusy(false);}}
 }
 return <><div className="spatial-launch"><button disabled={!connected} onClick={()=>setOpen(true)}>Open Network Analysis</button></div>
 {active&&resultsTarget&&result&&createPortal(<section className="panel-section spatial-monitor"><h3>{methods.find(m=>m.id===result.operation)?.title??result.operation}</h3><p>{result.receipt.nodes} nodes · {result.receipt.edges} edges · {result.rows.length} records</p><button onClick={()=>setOpen(true)}>Review network results</button></section>,resultsTarget)}
 {open&&createPortal(<div className="figure-studio-backdrop"><div ref={dialog} role="dialog" aria-modal="true" aria-label="Network science workbench" tabIndex={-1} className="spatial-science-dialog" onKeyDown={e=>{if(e.key==='Escape'&&!studio){e.stopPropagation();close();}if(e.key==='Tab'&&!studio){const nodes=Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button:enabled,input:enabled,select:enabled,textarea:enabled')).filter(n=>n.getClientRects().length);if(e.shiftKey&&(document.activeElement===nodes[0]||document.activeElement===dialog.current)){e.preventDefault();nodes.at(-1)?.focus();}else if(!e.shiftKey&&document.activeElement===nodes.at(-1)){e.preventDefault();nodes[0]?.focus();}}}}>
 <header><strong>Network Analysis · {methods.length} scientific methods</strong><button onClick={close}>Close</button></header>
 <div className="spatial-science-columns"><div className="spatial-science-input"><fieldset disabled={busy}><legend>Network source</legend>
 <label>Network GeoJSON<input type="file" accept=".geojson,.json" onChange={e=>{const file=e.target.files?.[0];if(file)void importGraph(file);}}/></label>
 {projectId&&<><label>Project line layer<select value={layer} onChange={e=>setLayer(e.target.value)}><option value="">Select layer</option>{layers.map(l=><option key={l.id} value={l.id}>{l.name}</option>)}</select></label><button disabled={!layer} onClick={()=>{setBusy(true);getSpatialLayerSource(projectId,layer).then(x=>{if(mounted.current)load(x,layers.find(l=>l.id===layer)?.name??layer);}).catch(e=>setError(String(e.message))).finally(()=>{if(mounted.current)setBusy(false);});}}>Load project network</button></>}
 {network&&<p>{name} · {network.features.length} edges</p>}
 <label>Cost property<input value={cost} onChange={e=>{setCost(e.target.value);invalidate();}}/></label>{cost!=='length_m'&&<label>Cost unit<input value={unit} onChange={e=>{setUnit(e.target.value);invalidate();}}/></label>}
 <button disabled={!network||!cost.trim()} onClick={()=>void run('topology')}>Inspect topology and node IDs</button>
 <details><summary>Node IDs ({nodeIds.length})</summary><textarea readOnly rows={4} value={nodeIds.join('\n')}/></details>
 </fieldset><fieldset disabled={busy}><legend>Research method</legend>
 <label>Network algorithm<select value={operation} onChange={e=>{setOperation(e.target.value);invalidate();}}>{methods.map(m=><option key={m.id} value={m.id}>{m.title}</option>)}</select></label>
 {usesOrigin&&<label>Origin node IDs (one per line)<textarea rows={3} value={origins} onChange={e=>{setOrigins(e.target.value);invalidate();}}/></label>}
 {usesDest&&<label>Destination node IDs (one per line)<textarea rows={3} value={destinations} onChange={e=>{setDestinations(e.target.value);invalidate();}}/></label>}
 {['service_area','two_step_fca'].includes(operation)&&<label>Cost threshold<input type="number" min=".000001" value={threshold} onChange={e=>{setThreshold(Number(e.target.value));invalidate();}}/></label>}
 {operation==='gravity_access'&&<label>Exponential decay coefficient<input type="number" min=".000001" step=".001" value={beta} onChange={e=>{setBeta(Number(e.target.value));invalidate();}}/></label>}
 {usesSupply&&<label>Facility supply (JSON)<textarea rows={3} value={supply} onChange={e=>{setSupply(e.target.value);invalidate();}}/></label>}
 {operation==='two_step_fca'&&<label>Origin demand (JSON)<textarea rows={3} value={demand} onChange={e=>{setDemand(e.target.value);invalidate();}}/></label>}
 {operation==='scenario_impact'&&<><label>Closed edge IDs (one per line)<textarea rows={3} value={closed} onChange={e=>{setClosed(e.target.value);invalidate();}}/></label><label>Cost multipliers (JSON)<textarea rows={3} value={multipliers} onChange={e=>{setMultipliers(e.target.value);invalidate();}}/></label></>}
 {operation==='edge_criticality'&&<label>Candidate edge IDs (optional, one per line)<textarea rows={3} value={testEdges} onChange={e=>{setTestEdges(e.target.value);invalidate();}}/></label>}
 {operation==='stochastic_reliability'&&<><label>Independent edge failure probabilities (JSON)<textarea rows={3} value={failure} onChange={e=>{setFailure(e.target.value);invalidate();}}/></label><label>Monte Carlo trials<input type="number" min="20" max="2000" value={trials} onChange={e=>{setTrials(Number(e.target.value));invalidate();}}/></label><label>Random seed<input type="number" min="0" value={seed} onChange={e=>{setSeed(Number(e.target.value));invalidate();}}/></label></>}
 {usesRaster&&<><label>Exposure GeoTIFF<input type="file" accept=".tif,.tiff" onChange={e=>{const file=e.target.files?.[0];if(file)void importRaster(file);}}/></label><label>Managed imagery<select value={asset} onChange={e=>setAsset(e.target.value)}><option value="">Select imagery</option>{assets.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label><button disabled={!asset} onClick={()=>{setBusy(true);getSpatialRasterSource(asset).then(x=>{if(mounted.current){setRaster({data:x.data,name:x.name});setBand(x.band??1);invalidate();}}).catch(e=>setError(String(e.message))).finally(()=>{if(mounted.current)setBusy(false);});}}>Load exposure imagery</button>{raster&&<><p>{raster.name}</p><button onClick={()=>{setRaster(null);invalidate();}}>Remove raster</button><label>Raster band<input type="number" min="1" max="1024" value={band} onChange={e=>{setBand(Number(e.target.value));invalidate();}}/></label><label>Sample spacing (m)<input type="number" min="1" value={spacing} onChange={e=>{setSpacing(Number(e.target.value));invalidate();}}/></label>{operation==='scenario_impact'&&<><label>Closure threshold (raster units)<input type="number" value={hazard} onChange={e=>{setHazard(Number(e.target.value));invalidate();}}/></label><label>Minimum valid coverage<input type="number" min=".01" max="1" step=".01" value={coverage} onChange={e=>{setCoverage(Number(e.target.value));invalidate();}}/></label></>}</>}</>}
 <button disabled={!network||!method||!cost.trim()||(usesOrigin&&!ids(origins).length)||(usesDest&&!ids(destinations).length)||(operation==='hazard_exposure'&&!raster)} onClick={()=>void run()}>Run network analysis</button></fieldset>
 {busy&&<p role="status">Calculating network results…</p>}{error&&<p role="alert">{error}</p>}</div>
 <div className="spatial-science-output">{result?<><h3>{methods.find(m=>m.id===result.operation)?.title??result.operation}</h3><div className="spatial-science-actions">
 <button onClick={()=>{onPreview(result.features.features);close();}}>Show network results on map</button><button onClick={()=>download(result.csv,'network-result.csv','text/csv')}>CSV</button><button onClick={()=>download(JSON.stringify(result.features),'network-result.geojson','application/geo+json')}>GeoJSON</button><button onClick={()=>download(JSON.stringify(result.receipt,null,2),'network-receipt.json','application/json')}>Research receipt</button><button onClick={()=>{setFigure(null);setStudio(true);}}>Scientific Figure Studio</button></div>
 {result.figures.map((p,i)=><button key={i} onClick={()=>{setFigure(p);setStudio(true);}}>{p.title}</button>)}
 <table><tbody>{Object.entries(result.receipt.metrics).map(([k,v])=><tr key={k}><th>{k.replaceAll('_',' ')}</th><td>{typeof v==='number'?v.toPrecision(7):JSON.stringify(v)}</td></tr>)}</tbody></table>
 <div className="spatial-table"><table><thead><tr>{result.columns.map(c=><th key={c}>{c}</th>)}</tr></thead><tbody>{result.rows.slice(0,200).map((r,i)=><tr key={i}>{r.map((v,j)=><td key={j}>{v===null?'Unreachable / NoData':typeof v==='number'?v.toPrecision(7):v}</td>)}</tr>)}</tbody></table><small>{Math.min(result.rows.length,200)} / {result.rows.length} rows</small></div></>:<p>Choose a network and run an analysis.</p>}</div>
 </div></div></div>,document.body)}
 {studio&&result&&<ScientificFigureStudio initialTier="all" source={{name:figure?.title??result.operation,csv:figure?.csv??result.csv,provenance:result.receipt,initialRecipe:figure?.recipe,initialBindings:figure?.bindings}} onClose={()=>setStudio(false)}/>}</>;
}
