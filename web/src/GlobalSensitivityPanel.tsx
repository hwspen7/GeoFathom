import {useEffect,useRef,useState} from 'react';
import {analyzeGlobalSensitivity,type GlobalSensitivityInput,type GlobalSensitivityOutput} from './api';
import ScientificFigureStudio from './ScientificFigureStudio';
import {saveFigureBlob} from './figureExport';

type Factor={name:string;minimum:string;maximum:string};
export default function GlobalSensitivityPanel({base,parameters,connected,sourceHash}:{base:GlobalSensitivityInput['base'];parameters:string[];connected:boolean;sourceHash?:string}){
 const eligible=parameters.filter(p=>!['neighborhood_radius','curvature_radius','stream_cells'].includes(p)&&(p!=='refraction_coeff'||base.consider_curvature===true));
 const [method,setMethod]=useState<'sobol'|'morris'|'pareto'>('sobol'),[factors,setFactors]=useState<Factor[]>(()=>eligible.slice(0,2).map(name=>({name,minimum:'',maximum:''})));
 const [metric,setMetric]=useState(''),[secondMetric,setSecondMetric]=useState(''),[samples,setSamples]=useState(16),[seed,setSeed]=useState(42),[busy,setBusy]=useState(false),[error,setError]=useState(''),[result,setResult]=useState<GlobalSensitivityOutput|null>(null),[studio,setStudio]=useState(false);
 const controller=useRef<AbortController|null>(null);
 useEffect(()=>()=>controller.current?.abort(),[]);
 function edit(i:number,field:keyof Factor,value:string){setFactors(old=>old.map((f,j)=>j===i?{...f,[field]:value}:f));}
 function cancel(){controller.current?.abort();controller.current=null;setBusy(false);}
 async function run(){if(busy)return;setError('');setResult(null);
  if(!metric.trim()||(method==='pareto'&&(!secondMetric.trim()||metric.trim()===secondMetric.trim()))||factors.length<2||new Set(factors.map(f=>f.name)).size!==factors.length||factors.some(f=>!f.minimum.trim()||!f.maximum.trim()||!Number.isFinite(Number(f.minimum))||!Number.isFinite(Number(f.maximum))||Number(f.minimum)>=Number(f.maximum))){setError('Choose a scalar metric and distinct factors with increasing finite bounds.');return;}
  const ac=new AbortController();controller.current=ac;setBusy(true);
  try{const output=await analyzeGlobalSensitivity({base,method,metric:metric.trim(),second_metric:method==='pareto'?secondMetric.trim():undefined,factors:factors.map(f=>({name:f.name,minimum:Number(f.minimum),maximum:Number(f.maximum)})),samples,seed,expected_source_sha256:sourceHash},ac.signal);if(!ac.signal.aborted)setResult(output);}
  catch(e){if(!ac.signal.aborted)setError((e as Error).message);}finally{if(controller.current===ac){controller.current=null;setBusy(false);}}
 }
 function download(data:string,name:string,type:string){saveFigureBlob(new Blob([data],{type}),name);}
 return <section aria-label="Global sensitivity analysis">
 <h3>Global sensitivity design</h3><p>Run actual terrain evaluations with independent uniform parameter bounds. Small designs are screening estimates.</p>
 {eligible.length<2?<p>This operation has fewer than two active continuous parameters. Select another terrain operation.</p>:<fieldset disabled={busy}><legend>Experiment settings</legend>
 <label>Method<select aria-label="Global sensitivity method" value={method} onChange={e=>setMethod(e.target.value as typeof method)}><option value="sobol">Sobol variance indices</option><option value="morris">Morris elementary effects</option><option value="pareto">Adaptive Pareto search (minimize both)</option></select></label>
 <label>Result metric key<input aria-label="Global result metric" value={metric} onChange={e=>setMetric(e.target.value)} placeholder="e.g. cut_m3 or product_mean"/></label>{method==='pareto'&&<label>Second minimized metric<input aria-label="Second objective metric" value={secondMetric} onChange={e=>setSecondMetric(e.target.value)} placeholder="e.g. fill_m3"/></label>}
 {factors.map((f,i)=><div key={i} className="research-scenarios"><label>Factor {i+1}<select value={f.name} onChange={e=>edit(i,'name',e.target.value)}>{eligible.map(n=><option key={n}>{n}</option>)}</select></label><label>Minimum<input type="number" step="any" value={f.minimum} onChange={e=>edit(i,'minimum',e.target.value)}/></label><label>Maximum<input type="number" step="any" value={f.maximum} onChange={e=>edit(i,'maximum',e.target.value)}/></label><button type="button" disabled={factors.length<=2} onClick={()=>setFactors(old=>old.filter((_,j)=>i!==j))}>Remove factor</button></div>)}
 <button type="button" disabled={factors.length>=Math.min(eligible.length,6)} onClick={()=>{const name=eligible.find(n=>!factors.some(f=>f.name===n));if(name)setFactors(old=>[...old,{name,minimum:'',maximum:''}]);}}>Add factor</button>
 <label>{method==='pareto'?'Evaluation budget':'Sample pairs / trajectories'}<input type="number" min="8" max="128" value={samples} onChange={e=>setSamples(Number(e.target.value))}/></label><label>Seed<input type="number" min="0" max="4294967295" value={seed} onChange={e=>setSeed(Number(e.target.value))}/></label>
 <p>Planned model evaluations: {method==='pareto'?samples:samples*(factors.length+(method==='sobol'?2:1))} plus baseline. The study area and total cell budget are validated on the server.</p>
 <button type="button" disabled={!connected||busy} onClick={()=>void run()}>{method==='pareto'?'Run Pareto search':'Run global sensitivity'}</button></fieldset>}
 {busy&&<><p role="status">Evaluating terrain design…</p><button onClick={cancel}>Cancel global experiment</button></>}
 {error&&<p role="alert">{error}</p>}
 {result&&<><h3>{result.method.toUpperCase()} · {result.metric}</h3><p>{result.evaluations} actual evaluations. {result.method_note}</p>
 <table><thead><tr>{Object.keys(result.indices[0]).map(k=><th key={k}>{k}</th>)}</tr></thead><tbody>{result.indices.map(row=><tr key={row.factor}>{Object.keys(result.indices[0]).map(k=><td key={k}>{typeof row[k]==='number'?Number(row[k]).toPrecision(5):row[k]??'Undefined'}</td>)}</tr>)}</tbody></table>
 <div className="research-actions"><button onClick={()=>setStudio(true)}>Open result figure</button><button onClick={()=>download(result.design_csv,'global-design.csv','text/csv')}>Design CSV</button><button onClick={()=>download(result.plot_csv,'global-plot.csv','text/csv')}>Plot CSV</button><button onClick={()=>download(JSON.stringify(result,null,2),'global-sensitivity.json','application/json')}>Experiment receipt</button></div></>}
 {studio&&result&&<ScientificFigureStudio source={{name:result.method.toUpperCase()+' · '+result.metric,csv:result.plot_csv,provenance:result.manifest,initialRecipe:result.method,initialBindings:result.bindings}} onClose={()=>setStudio(false)}/>}
 </section>;
}
