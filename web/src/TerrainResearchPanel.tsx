import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import FigureGallery from './FigureGallery';
import {researchFigureData,type ResearchFigureSource} from './researchFigureData';
import {analyzeResearch,getResearchCatalog,type ResearchCatalog,type ResearchExperiment,type ResearchResult,type TerrainRasterLayer,type PlotData} from './api';
import type {PersistedTerrainResult} from './terrainResultStore';
import {researchBase,parseParameter,parseSweep,downloadResearch,loadResearch,saveResearch} from './terrainResearch';
const fmt=(n:number|null|undefined)=>n==null?'Undefined':n.toLocaleString('en-US',{maximumSignificantDigits:7});
const label=(s:string)=>s.replaceAll('_',' ');
type Page='experiment'|'comparison'|'figures'|'report';
function ResponsePlot({points,parameter,metric}:{points:Array<[number,number]>;parameter:string;metric:string}){
 if(!points.length)return null;
 const sorted=[...points].sort((a,b)=>a[0]-b[0]),xs=sorted.map(p=>p[0]),ys=sorted.map(p=>p[1]);
 const lo=Math.min(...ys),hi=Math.max(...ys),xmin=Math.min(...xs),xmax=Math.max(...xs);
 const xy=([x,y]:[number,number])=>[65+480*(x-xmin)/(xmax-xmin||1),190-140*(y-lo)/(hi-lo||1)];
 return <svg viewBox="0 0 600 240" role="img" aria-label={'Sensitivity response: '+metric} className="research-response-plot">
  <path d="M65 45 V190 H550" fill="none" stroke="#87959a"/>
  <polyline points={sorted.map(p=>xy(p).join(',')).join(' ')} fill="none" stroke="#236c79" strokeWidth="2"/>
  {sorted.map((p,i)=>{const [x,y]=xy(p);return <circle key={i} cx={x} cy={y} r="4" fill="#236c79"><title>{fmt(p[0])+': '+fmt(p[1])}</title></circle>;})}
  <text x="65" y="215">{fmt(xmin)}</text><text x="545" y="215" textAnchor="end">{fmt(xmax)}</text>
  <text x="58" y="190" textAnchor="end">{fmt(lo)}</text><text x="58" y="50" textAnchor="end">{fmt(hi)}</text>
  <text x="65" y="24">{label(metric)}</text><text x="300" y="236" textAnchor="middle">{label(parameter)}</text>
 </svg>;
}
export default function TerrainResearchPanel(p:{projectId:string|null;record:PersistedTerrainResult|null;connected:boolean;
 onClose:()=>void;onLayer:(layer:TerrainRasterLayer|null)=>void}){
 const [page,setPage]=useState<Page>('experiment'),[catalog,setCatalog]=useState<ResearchCatalog|null>(null);
 const [title,setTitle]=useState('Terrain research experiment'),[mode,setMode]=useState<ResearchExperiment['mode']>('comparison');
 const [scenarios,setScenarios]=useState<ResearchExperiment['scenarios']>([{name:'Alternative',parameters:{}}]);
 const [scenarioIndex,setScenarioIndex]=useState(0),[parameter,setParameter]=useState(''),[parameterValue,setParameterValue]=useState('');
 const [sweep,setSweep]=useState(''),[sigma,setSigma]=useState('1'),[samples,setSamples]=useState('100');
 const [seed,setSeed]=useState('42'),[coverage,setCoverage]=useState('0.95');
 const [errorModel,setErrorModel]=useState<'independent'|'common_offset'>('independent');
 const [result,setResult]=useState<ResearchResult|null>(null),[error,setError]=useState(''),[cacheWarning,setCacheWarning]=useState(''),[busy,setBusy]=useState(false);
 const [metric,setMetric]=useState(''),[productIndex,setProductIndex]=useState(0),[wipe,setWipe]=useState(50);
 const [galleryData,setGalleryData]=useState<PlotData|null>(null);
 const [metricFigureSource,setMetricFigureSource]=useState<ResearchFigureSource>('values');
 const [figureMode,setFigureMode]=useState<'difference'|'swipe'|'response'|'metric'|'matrix'>('difference');
 const controller=useRef<AbortController|null>(null),dialog=useRef<HTMLDivElement>(null),interacted=useRef(false);
 const base=p.record?researchBase(p.record):null,supported=!!base&&!!catalog?.sweep_parameters[base.operation];
 const scenario=scenarios[scenarioIndex];
 const parameters=mode==='sensitivity'?(catalog?.sweep_parameters[base?.operation??'']??[]):(catalog?.scenario_parameters[base?.operation??'']??[]);
 const parameterChoice=parameters.includes(parameter)?parameter:parameters[0]??'';
 const spec=catalog?.parameter_specs?.[parameterChoice];
 const baselineValue=base?.[parameterChoice]??spec?.default;
 const products=result?[...result.differences,...result.products]:[];
 const availableProducts=figureMode==='swipe'?products.filter(item=>item.role==='scenario'):products;
 const activeProductIndex=Math.min(productIndex,Math.max(0,availableProducts.length-1));
 const product=availableProducts[activeProductIndex];
 const metrics=result?.metric_table.map(row=>row.metric)??[];
 const metricChoice=metrics.includes(metric)?metric:metrics.find(m=>['product_mean','cut_m3','net_cut_m3'].includes(m))??metrics[0]??'';
 const row=result?.metric_table.find(row=>row.metric===metricChoice),interval=result?.uncertainty?.metrics[metricChoice];
 const metricSources:ResearchFigureSource[]=result?.mode==='uncertainty'?['interval','realizations']:result?.mode==='sensitivity'?['response','derivative','values','delta','relative']:['values','delta','relative'];
 const sourceChoice=metricSources.includes(metricFigureSource)?metricFigureSource:metricSources[0];
 const metricFigure=result&&metricChoice&&sourceChoice?researchFigureData(result,metricChoice,sourceChoice):null;
 useEffect(()=>{
  let current=true;
  getResearchCatalog().then(value=>{if(current)setCatalog(value);}).catch(e=>{if(current)setError(String(e.message??e));});
  loadResearch(p.projectId).then(value=>{if(current&&value&&!interacted.current)setResult(value.result);})
   .catch(()=>{if(current)setCacheWarning('Saved experiment could not be restored. You can still run and export a new experiment.');});
  return()=>{current=false;controller.current?.abort();};
 },[p.projectId]);
 useEffect(()=>{const previous=document.activeElement as HTMLElement|null;dialog.current?.focus();return()=>previous?.focus();},[]);
 function cancel(){controller.current?.abort();controller.current=null;setBusy(false);}
 async function run(){
  if(!base||busy)return;interacted.current=true;setError('');setCacheWarning('');
  let input:ResearchExperiment;
  try{
   input={title,baseline_name:'Baseline',base,mode,scenarios:mode==='comparison'?scenarios:[],
    ...(mode==='sensitivity'?{parameter:parameterChoice,values:parseSweep(sweep)}:{}),
    sigma_m:Number(sigma),samples:Number(samples),seed:Number(seed),error_model:errorModel,coverage:Number(coverage),expected_source_sha256:p.record?.source.sha256};
   if(mode==='comparison'&&scenarios.some(s=>Object.keys(s.parameters).length===0))throw new Error('Apply at least one parameter to each alternative scenario.');
  }catch(e){setError((e as Error).message);return;}
  const request=new AbortController();controller.current=request;setBusy(true);
  try{
   const output=await analyzeResearch(input,request.signal);if(request.signal.aborted)return;
   setResult(output);setProductIndex(0);setFigureMode('difference');setMetric('');setPage('comparison');
   try{await saveResearch(p.projectId,input,output);}catch(e){if(!request.signal.aborted)setCacheWarning('Cache: '+(e as Error).message);}
  }catch(e){if(!request.signal.aborted)setError((e as Error).message);}
  finally{if(controller.current===request){controller.current=null;setBusy(false);}}
 }
 function applyParameter(){try{
  const value=parseParameter(parameterValue);setScenarios(old=>old.map((s,i)=>i===scenarioIndex?{...s,parameters:{...s.parameters,[parameterChoice]:value}}:s));setError('');
 }catch(e){setError((e as Error).message);}}
 function exportJson(){if(!result)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(result.manifest.input,null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download='experiment.json';link.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 const metricSelect=<label>Result metric<select aria-label="Result metric" value={metricChoice} onChange={e=>setMetric(e.target.value)}>{metrics.map(key=><option key={key} value={key}>{label(key)}</option>)}</select></label>;
 return createPortal(<div className="research-dialog-backdrop"><div role="dialog" aria-modal="true" aria-label="Terrain research analysis" className="research-dialog" tabIndex={-1} ref={dialog} onKeyDown={e=>{
  e.stopPropagation();
  if(e.key==='Escape'){e.preventDefault();if(busy)cancel();else p.onClose();}
  if(e.key==='Tab'){
   const items=Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button:enabled,input:enabled,select:enabled,a[href]')).filter(x=>x.getClientRects().length>0);
   if(!items.length)return;const first=items[0],last=items[items.length-1];
   if(e.shiftKey&&(document.activeElement===first||document.activeElement===dialog.current)){e.preventDefault();last.focus();}
   else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
  }
 }}>
 <header><div><strong>Research analysis</strong><small>{p.record?.title??'Select a terrain result to begin'} · {p.record?.source.name??'No source selected'}</small></div><button type="button" onClick={()=>{cancel();p.onClose();}} aria-label="Close research analysis">Close</button></header>
 <nav aria-label="Research analysis pages">{(['experiment','comparison','figures','report'] as Page[]).map(item=><button key={item} type="button" aria-pressed={page===item} disabled={item!=='experiment'&&!result} onClick={()=>setPage(item)}>{{experiment:'Experiment',comparison:'Results',figures:'Figures',report:'Report'}[item]}</button>)}</nav>
 {error&&<p role="alert" className="discovery-error">{error}</p>}{cacheWarning&&<p role="status">{cacheWarning}</p>}
 <main className="research-page">
 {page==='experiment'&&<>
  <h3>Matched experiments</h3><p>Compare named scenarios, sweep one parameter, or propagate an assumed DEM error. Source and study boundary stay fixed.</p>
  {!supported&&<p role="status">Select a supported surface, hydrology, visibility or earthwork result before running an experiment.</p>}
  <fieldset disabled={busy} className="research-form">
  <label>Experiment title<input aria-label="Experiment title" value={title} maxLength={160} onChange={e=>setTitle(e.target.value)}/></label>
  <label>Analysis method<select aria-label="Analysis method" value={mode} onChange={e=>{setMode(e.target.value as typeof mode);setParameter('');}}><option value="comparison">Scenario comparison and spatial difference</option><option value="sensitivity">Parameter sensitivity</option><option value="uncertainty" disabled={!catalog?.uncertainty_operations.includes(base?.operation??'')}>Uncertainty propagation</option></select></label>
  {mode==='comparison'&&<section className="research-scenarios" aria-label="Named scenarios">
   <label>Scenario<select aria-label="Scenario" value={scenarioIndex} onChange={e=>setScenarioIndex(Number(e.target.value))}>{scenarios.map((s,i)=><option key={i} value={i}>{s.name}</option>)}</select></label>
   <div className="research-actions"><button type="button" disabled={scenarios.length>=8} onClick={()=>{setScenarios(old=>[...old,{name:'Alternative '+(old.length+1),parameters:{}}]);setScenarioIndex(scenarios.length);}}>Add scenario</button><button type="button" disabled={scenarios.length<=1} onClick={()=>{setScenarios(old=>old.filter((_,i)=>i!==scenarioIndex));setScenarioIndex(0);}}>Remove scenario</button></div>
   <label>Scenario name<input aria-label="Scenario name" value={scenario?.name??''} maxLength={80} onChange={e=>setScenarios(old=>old.map((s,i)=>i===scenarioIndex?{...s,name:e.target.value}:s))}/></label>
   <label>Parameter<select aria-label="Parameter" value={parameterChoice} onChange={e=>setParameter(e.target.value)}>{parameters.map(key=><option key={key} value={key}>{label(key)}</option>)}</select></label>
   <label>Parameter value{spec?.choices.length?<select aria-label="Parameter value" value={parameterValue} onChange={e=>setParameterValue(e.target.value)}><option value="">Choose a value</option>{spec.choices.map(value=><option key={String(value)} value={String(value)}>{label(String(value))}</option>)}</select>:<input aria-label="Parameter value" value={parameterValue} onChange={e=>setParameterValue(e.target.value)} placeholder="Number or comma-separated weights"/>}<small>Baseline: {String(baselineValue??'Not set')}</small></label><button type="button" disabled={!parameterChoice||(Object.keys(scenario?.parameters??{}).length>=6&&!(parameterChoice in (scenario?.parameters??{})))} onClick={applyParameter}>Apply parameter</button>
   <div className="research-overrides">{Object.entries(scenario?.parameters??{}).map(([key,value])=><span key={key}>{label(key)}: {String(value)} <button type="button" aria-label={'Remove '+key} onClick={()=>setScenarios(old=>old.map((s,i)=>{if(i!==scenarioIndex)return s;const parameters={...s.parameters};delete parameters[key];return {...s,parameters};}))}>×</button></span>)}</div>
  </section>}
  {mode==='sensitivity'&&<><label>Sweep parameter<select aria-label="Sweep parameter" value={parameterChoice} onChange={e=>setParameter(e.target.value)}>{parameters.map(key=><option key={key} value={key}>{label(key)}</option>)}</select></label><label>Sweep values<input aria-label="Sweep values" value={sweep} onChange={e=>setSweep(e.target.value)} placeholder="e.g. 95, 100, 105"/></label><p>Enter two to eight values. Response slopes use the recorded baseline.</p></>}
  {mode==='uncertainty'&&<>
   <label>DEM vertical standard deviation (m)<input aria-label="DEM vertical standard deviation (m)" type="number" min="0.001" max="1000" step="any" value={sigma} onChange={e=>setSigma(e.target.value)}/></label>
   <label>Spatial error model<select aria-label="Spatial error model" value={errorModel} onChange={e=>setErrorModel(e.target.value as typeof errorModel)}><option value="independent">Independent cell errors</option><option value="common_offset">Common vertical offset</option></select></label>
   <label>Realizations<input aria-label="Realizations" type="number" min="20" max="500" value={samples} onChange={e=>setSamples(e.target.value)}/></label><label>Random seed<input aria-label="Random seed" type="number" min="0" max="4294967295" value={seed} onChange={e=>setSeed(e.target.value)}/></label>
   <label>Coverage probability<select aria-label="Coverage probability" value={coverage} onChange={e=>setCoverage(e.target.value)}><option value="0.9">90%</option><option value="0.95">95%</option><option value="0.99">99%</option></select></label><p>Gaussian error assumptions determine these intervals. Sampling stability is reported.</p>
  </>}
  </fieldset>
 </>}
 {page==='comparison'&&result&&<>
  <h3>{result.title}</h3>{result.comparison_warning&&<p role="status">{result.comparison_warning}</p>}<p>{result.runs.map(r=>r.label).join(' · ')}</p>{metricSelect}
  {result.uncertainty&&interval?<><p>{result.uncertainty.coverage*100}% model coverage interval · {result.uncertainty.samples} realizations · {result.uncertainty.model}</p>
   <table><thead><tr><th>Baseline</th><th>Mean</th><th>Std</th><th>Low</th><th>High</th></tr></thead><tbody><tr>{(['baseline','mean','std','low','high'] as const).map(k=><td key={k}>{fmt(interval[k])}</td>)}</tr></tbody></table>
   <p>Split-half endpoint difference: {fmt(interval.split_half_endpoint_difference)} · Mean standard error: {fmt(interval.mean_standard_error)}</p><small>{result.uncertainty.warning}</small></>:
   <table><thead><tr><th>Scenario</th><th>Value</th><th>Δ from baseline</th><th>Relative Δ</th></tr></thead><tbody>{result.runs.map((run,i)=><tr key={i}><th>{run.label}</th><td>{fmt(row?.values[i])}</td><td>{fmt(row?.deltas[i])}</td><td>{row?.relative_pct[i]==null?'Undefined':fmt(row.relative_pct[i])+'%'}</td></tr>)}</tbody></table>}
  <p>Units follow metric names and the manifest. Changes are undefined for unmatched populations; percentages are also undefined for a zero baseline. The package includes every metric.</p>
 </>}
 {page==='figures'&&result&&<>
  <label>Figure<select aria-label="Figure" value={figureMode} onChange={e=>{setFigureMode(e.target.value as typeof figureMode);setProductIndex(0);}}><option value="difference">Output and difference maps</option><option value="swipe" disabled={!result.products.some(p=>p.role==='scenario')}>Baseline / scenario swipe</option><option value="response" disabled={!result.sensitivity.length}>Sensitivity response</option><option value="metric">Scientific metric figures</option><option value="matrix" disabled={result.products.length<2}>Multi-map matrix</option></select></label>
  {figureMode==='metric'?<>{metricSelect}<label>Data source<select aria-label="Research figure data" value={sourceChoice} onChange={e=>setMetricFigureSource(e.target.value as ResearchFigureSource)}>{metricSources.map(s=><option key={s} value={s}>{({values:'Scenario values',delta:'Absolute change',relative:'Relative change',response:'Parameter response',derivative:'Baseline secant',interval:'Model coverage interval',realizations:'Monte Carlo realizations'})[s]}</option>)}</select></label><button type="button" disabled={!metricFigure} onClick={()=>setGalleryData(metricFigure||null)}>Open metric figure library</button>{!metricFigure&&<p>No valid recorded values for this selection.</p>}</>:figureMode==='matrix'?<div className="research-map-matrix" style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(230px,1fr))',gap:12}}>{result.products.map((item,i)=><figure key={i} style={{margin:0}}><figcaption>{item.name}</figcaption><img style={{width:'100%',objectFit:'contain'}} src={item.raster.png} alt={item.name+' matrix map'}/><div className="research-map-legend">{item.raster.legend.map((entry,j)=><span key={j}><i style={{background:entry.color}}/>{entry.label}</span>)}</div><button type="button" disabled={!item.plot_data} onClick={()=>setGalleryData(item.plot_data??null)}>Plot {item.name}</button></figure>)}</div>:figureMode==='response'?<>{metricSelect}<ResponsePlot parameter={result.sensitivity[0]?.parameter??''} metric={metricChoice} points={result.sensitivity.filter(r=>Number.isFinite(r.metrics[metricChoice])).map(r=>[r.value,r.metrics[metricChoice]])}/><p>Slopes from baseline: {result.sensitivity.map(r=>fmt(r.value)+' → '+fmt(r.derivatives[metricChoice])).join(' · ')}</p></>:<>
   <label>Map output<select aria-label="Map output" value={activeProductIndex} onChange={e=>setProductIndex(Number(e.target.value))}>{availableProducts.map((item,i)=><option key={i} value={i}>{item.name} · {item.role??item.kind}</option>)}</select></label>
   {product?<>
    <div className="research-map-figure"><img src={product.raster.png} alt={product.name+' map'}/>{figureMode==='swipe'&&result.products[0]&&<img className="research-swipe-baseline" src={result.products[0].raster.png} alt="Baseline map" style={{clipPath:`inset(0 ${100-wipe}% 0 0)`}}/>}</div>
    {figureMode==='swipe'&&<label>Baseline reveal<input aria-label="Baseline reveal" type="range" min="0" max="100" value={wipe} onChange={e=>setWipe(Number(e.target.value))}/></label>}
    <small>{product.raster.unit} · {product.raster.valid_cells.toLocaleString()} valid cells · signed differences use candidate minus baseline</small>
    <div className="research-map-legend">{product.raster.legend.map((entry,i)=><span key={i}><i style={{background:entry.color}}/>{entry.label}</span>)}</div>
    {product.plot_data&&<button type="button" onClick={()=>setGalleryData(product.plot_data??null)}>Open scientific figure library</button>}
   {product.statistics&&<p>Common cells: {String(product.statistics.common_cells)} · Coverage: {fmt(product.statistics.common_coverage_pct as number)}% · Changed: {fmt(product.statistics.changed_pct as number)}%</p>}
    <div className="research-actions"><button type="button" onClick={()=>{p.onLayer({id:'research-preview',title:product.name,raster:product.raster,opacity:.8,resampling:'nearest'});p.onClose();}}>Show on map</button><button type="button" onClick={()=>downloadResearch(product.raster.geotiff,'research-output.tif','image/tiff')}>Download GeoTIFF</button></div>
   </>:<p>This operation has metric outputs. Use the results table.</p>}
  </>}
 </>}
 {page==='report'&&result&&<><h3>Research report and reproducibility package</h3><p>{result.title}</p><ul><li>PDF report with maps, figures, methods, parameters and quality information</li><li>GeoTIFF products, differences and preview maps</li><li>Scenario metrics and sensitivity / uncertainty tables</li><li>Source checksum, exact study geometry, software versions and experiment input</li></ul><p>The report describes the completed experiment. Form edits do not change this result.</p><div className="research-actions"><button type="button" onClick={()=>downloadResearch(result.archive_base64,'terrain-research.zip','application/zip')}>Download research package</button><button type="button" onClick={exportJson}>Download experiment input</button></div><p>Source accuracy is not independently validated. Scenario spread is descriptive. Model intervals depend on the error model and finite sampling.</p></>}
 </main>
 <footer><span>{result?'Completed: '+result.title:'Inputs from the selected terrain result'}</span>{busy?<><span role="status">Computing experiment…</span><button type="button" onClick={cancel}>Cancel experiment</button></>:<button type="button" disabled={!supported||!p.connected||!title.trim()} onClick={()=>void run()}>Run experiment</button>}</footer>
 {galleryData&&result&&<FigureGallery projectId={p.projectId} research={{id:result.title+'-'+galleryData.quantity,title:galleryData.quantity,data:galleryData,manifest:result.manifest}} onClose={()=>setGalleryData(null)}/>}
 </div></div>,document.body);
}
