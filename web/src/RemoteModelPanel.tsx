import {useCallback,useEffect,useState} from 'react';
import RemoteFeatureBuilder,{type ModelFeatureBand} from './RemoteFeatureBuilder';
import {getGISJobs,getGISJob,queueRemoteModelJob,queueRemoteEvaluationJob,type GISJob} from './api';
import ScientificFigureStudio from './ScientificFigureStudio';

interface Band {image_id:string;band:number;encoding:string;scale:number;offset:number;unit:string}
interface Quality {image_id:string;band:number;scheme:string;roles:string[]}
interface Validation {overall_accuracy:number;macro_f1:number;mean_iou:number;cells:number;classes:number[];precision:number[];recall:number[];f1:number[];iou:number[];support:number[]}

export default function RemoteModelPanel({projectId,features,quality,assets,job,onJob}:{
 projectId?:string|null;features:Record<string,Band>|null;quality:Quality[]|null;
 assets:Array<{id:string;name:string}>;job:GISJob|null;onJob:(job:GISJob)=>void;
}){
 const [labels,setLabels]=useState(''),[block,setBlock]=useState(1000),[folds,setFolds]=useState(5),[buffer,setBuffer]=useState(true);
 const [models,setModels]=useState<GISJob[]>([]),[modelId,setModelId]=useState(''),[model,setModel]=useState<GISJob|null>(null);
 const [minimum,setMinimum]=useState(0),[busy,setBusy]=useState(false),[error,setError]=useState(''),[studio,setStudio]=useState(false);
 const [plot,setPlot]=useState<'class'|'reliability'|'interval'|'coverage'>('class');
 const [calibrate,setCalibrate]=useState(true),[maximumDistance,setMaximumDistance]=useState('');
 const [customFeatures,setCustomFeatures]=useState<Record<string,ModelFeatureBand>|null>(features);
 const featureChange=useCallback((value:Record<string,ModelFeatureBand>|null)=>setCustomFeatures(value),[]);
 const [predictions,setPredictions]=useState<GISJob[]>([]),[predictionId,setPredictionId]=useState(''),[reference,setReference]=useState(''),[referenceDescription,setReferenceDescription]=useState(''),[separation,setSeparation]=useState(1000);
 useEffect(()=>{if(!projectId)return;let live=true;getGISJobs(projectId).then(out=>{if(live){setModels(out.jobs.filter(j=>j.kind==='remote_model_train'&&j.status==='completed'));setPredictions(out.jobs.filter(j=>j.kind==='remote_model_predict'&&j.status==='completed'));}}).catch(e=>{if(live)setError((e as Error).message);});return()=>{live=false;};},[projectId,job?.id,job?.status]);
 useEffect(()=>{if(job?.kind==='remote_model_train'&&job.status==='completed')setModelId(job.id);},[job?.id,job?.status]);
 useEffect(()=>{if(!projectId||!modelId)return;let live=true;getGISJob(projectId,modelId).then(j=>{if(live)setModel(j);}).catch(e=>{if(live)setError((e as Error).message);});return()=>{live=false;};},[projectId,modelId]);
 const validation=model?.result?(model.result as {validation:Validation}).validation:null;
 const evaluation=job?.kind==='remote_model_evaluate'&&job.status==='completed'?job.result as {metrics:Validation&{training_excluded_cells:number;coverage:number;interval95:Record<string,number[]>;reliability:number[][];selective_accuracy:Array<{coverage:number;accuracy:number|null;accepted_cells:number}>}}:null;
 const running=!!job&&['queued','running'].includes(job.status);
 async function submit(training:boolean){if(!projectId||!customFeatures||!quality)return;setBusy(true);setError('');try{
  const common={features:customFeatures,quality};
  onJob(await queueRemoteModelJob(projectId,training?{...common,labels:{image_id:labels,band:1},parameters:{block_m:block,folds,buffer_blocks:buffer?1:0,calibrate}}:{...common,model_job_id:modelId,minimum_probability:minimum,...(maximumDistance?{maximum_training_distance:Number(maximumDistance)}:{})},training));
 }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function evaluate(){if(!projectId)return;setBusy(true);setError('');try{onJob(await queueRemoteEvaluationJob(projectId,{prediction_job_id:predictionId,reference_image_id:reference,reference_description:referenceDescription,block_m:block,training_buffer_m:separation}));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 const shown=evaluation?.metrics??validation;
 const csv=shown?['class,precision,recall,f1,iou,support',...shown.classes.map((c,i)=>[c,shown.precision[i],shown.recall[i],shown.f1[i],shown.iou[i],shown.support[i]].join(','))].join('\n'):'';
 const chartCsv=plot==='coverage'&&evaluation?['coverage,accuracy,accepted',...evaluation.metrics.selective_accuracy.filter(r=>r.accuracy!==null).map(r=>[r.coverage,r.accuracy,r.accepted_cells].join(','))].join('\n'):plot==='reliability'&&evaluation?['predicted,observed,cells',...evaluation.metrics.reliability.map(r=>r.join(','))].join('\n'):plot==='interval'&&evaluation?['metric,value,low,high',...(['overall_accuracy','macro_f1','mean_iou'] as const).map(k=>[k,evaluation.metrics[k],...evaluation.metrics.interval95[k]].join(','))].join('\n'):csv;
 return <fieldset disabled={busy}><legend>Train and reuse a classifier</legend>
 <RemoteFeatureBuilder assets={assets} bound={features} onChange={featureChange}/>
 <p>The selected managed reflectance bands are model features. Labels use positive class IDs and zero for unlabeled pixels.</p>
 <label>Training label raster<select value={labels} onChange={e=>setLabels(e.target.value)}><option value="">Choose labels</option>{assets.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
 <label>Validation block width (m)<input type="number" min="1" max="100000" value={block} onChange={e=>setBlock(Number(e.target.value))}/></label>
 <label>Spatial validation folds<input type="number" min="3" max="10" value={folds} onChange={e=>setFolds(Number(e.target.value))}/></label>
 <label><input type="checkbox" checked={buffer} onChange={e=>setBuffer(e.target.checked)}/>Exclude neighboring validation blocks</label>
 <label><input type="checkbox" checked={calibrate} onChange={e=>setCalibrate(e.target.checked)}/>Calibrate probabilities with nested spatial separation</label>
 <button disabled={!projectId||!customFeatures||!quality||!labels||running} onClick={()=>void submit(true)}>Train and save random forest</button>
 <label>Saved project model<select value={modelId} onChange={e=>setModelId(e.target.value)}><option value="">Choose a trained model</option>{models.map(m=><option key={m.id} value={m.id}>{m.created_at} · {m.id.slice(0,8)}</option>)}</select></label>
 <label>Minimum class probability<input type="number" min="0" max="1" step=".05" value={minimum} onChange={e=>setMinimum(Number(e.target.value))}/></label>
 <label>Maximum standardized training distance (optional)<input type="number" min="0" step=".5" value={maximumDistance} onChange={e=>setMaximumDistance(e.target.value)}/></label>
 <button disabled={!projectId||!customFeatures||!quality||!modelId||running} onClick={()=>void submit(false)}>Classify full-resolution imagery</button>
 {validation&&<><p>Spatial holdout: accuracy {validation.overall_accuracy.toFixed(4)} · macro F1 {validation.macro_f1.toFixed(4)} · mIoU {validation.mean_iou.toFixed(4)} · {validation.cells} samples</p><button onClick={()=>{setPlot('class');setStudio(true);}}>Model validation figures</button></>}
 <details><summary>Independent reference evaluation</summary>
 <label>Completed classification<select value={predictionId} onChange={e=>setPredictionId(e.target.value)}><option value="">Choose predictions</option>{predictions.map(p=><option key={p.id} value={p.id}>{p.created_at} · {p.id.slice(0,8)}</option>)}</select></label>
 <label>Independent reference labels<select value={reference} onChange={e=>setReference(e.target.value)}><option value="">Choose reference</option>{assets.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
 <label>Reference source and annotation procedure<textarea value={referenceDescription} onChange={e=>setReferenceDescription(e.target.value)}/></label>
 <label>Training-location exclusion distance (m)<input type="number" min="0" max="100000" value={separation} onChange={e=>setSeparation(Number(e.target.value))}/></label>
 <button disabled={!projectId||!predictionId||!reference||referenceDescription.trim().length<10||running} onClick={()=>void evaluate()}>Evaluate independent reference</button>
 {evaluation&&<><p>Independent reference: accuracy {evaluation.metrics.overall_accuracy.toFixed(4)} · 95% block interval {evaluation.metrics.interval95.overall_accuracy.map(v=>v.toFixed(4)).join(' – ')} · {evaluation.metrics.training_excluded_cells} training-neighbor observations excluded · coverage {(100*evaluation.metrics.coverage).toFixed(1)}%</p><button onClick={()=>{setPlot('class');setStudio(true);}}>Independent reference figures</button><button onClick={()=>{setPlot('reliability');setStudio(true);}}>Reference reliability figure</button><button onClick={()=>{setPlot('interval');setStudio(true);}}>Spatial confidence intervals</button><button onClick={()=>{setPlot('coverage');setStudio(true);}}>Coverage and accuracy</button></>}
 </details>
 <small>Outputs include class probabilities, entropy and training spectral distance. Calibration is optional and conditional on sampled support; spatial holdout does not establish external-site accuracy.</small>
 {error&&<p role="alert">{error}</p>}
 {studio&&(model||evaluation)&&<ScientificFigureStudio initialTier="all" source={{name:evaluation?'Independent classification validation':'Spatial classification validation',csv:chartCsv,rasters:[],provenance:(evaluation??model!.result) as Record<string,unknown>,initialRecipe:plot==='coverage'?'remote_selective_accuracy':plot==='reliability'?'remote_reliability':plot==='interval'?'research_forest':'basic_column',initialBindings:plot==='coverage'?{x:'coverage',y:'accuracy',z:'accepted'}:plot==='reliability'?{x:'predicted',y:'observed',z:'cells'}:plot==='interval'?{x:'metric',y:'value',low:'low',high:'high'}:{x:'class',y:'iou'}}} onClose={()=>setStudio(false)}/>}
 </fieldset>;
}
