import {useEffect,useState} from 'react';
import {getGISJobs,getGISJob,queueRemoteModelJob,type GISJob} from './api';
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
 useEffect(()=>{if(!projectId)return;let live=true;getGISJobs(projectId).then(out=>{if(live)setModels(out.jobs.filter(j=>j.kind==='remote_model_train'&&j.status==='completed'));}).catch(e=>{if(live)setError((e as Error).message);});return()=>{live=false;};},[projectId,job?.id,job?.status]);
 useEffect(()=>{if(job?.kind==='remote_model_train'&&job.status==='completed')setModelId(job.id);},[job?.id,job?.status]);
 useEffect(()=>{if(!projectId||!modelId)return;let live=true;getGISJob(projectId,modelId).then(j=>{if(live)setModel(j);}).catch(e=>{if(live)setError((e as Error).message);});return()=>{live=false;};},[projectId,modelId]);
 const validation=model?.result?(model.result as {validation:Validation}).validation:null;
 const running=!!job&&['queued','running'].includes(job.status);
 async function submit(training:boolean){if(!projectId||!features||!quality)return;setBusy(true);setError('');try{
  const common={features,quality};
  onJob(await queueRemoteModelJob(projectId,training?{...common,labels:{image_id:labels,band:1},parameters:{block_m:block,folds,buffer_blocks:buffer?1:0}}:{...common,model_job_id:modelId,minimum_probability:minimum},training));
 }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 const csv=validation?['class,precision,recall,f1,iou,support',...validation.classes.map((c,i)=>[c,validation.precision[i],validation.recall[i],validation.f1[i],validation.iou[i],validation.support[i]].join(','))].join('\n'):'';
 return <fieldset disabled={busy}><legend>Train and reuse a classifier</legend>
 <p>The selected managed reflectance bands are model features. Labels use positive class IDs and zero for unlabeled pixels.</p>
 <label>Training label raster<select value={labels} onChange={e=>setLabels(e.target.value)}><option value="">Choose labels</option>{assets.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
 <label>Validation block width (m)<input type="number" min="1" max="100000" value={block} onChange={e=>setBlock(Number(e.target.value))}/></label>
 <label>Spatial validation folds<input type="number" min="3" max="10" value={folds} onChange={e=>setFolds(Number(e.target.value))}/></label>
 <label><input type="checkbox" checked={buffer} onChange={e=>setBuffer(e.target.checked)}/>Exclude neighboring validation blocks</label>
 <button disabled={!projectId||!features||!quality||!labels||running} onClick={()=>void submit(true)}>Train and save random forest</button>
 <label>Saved project model<select value={modelId} onChange={e=>setModelId(e.target.value)}><option value="">Choose a trained model</option>{models.map(m=><option key={m.id} value={m.id}>{m.created_at} · {m.id.slice(0,8)}</option>)}</select></label>
 <label>Minimum vote probability<input type="number" min="0" max="1" step=".05" value={minimum} onChange={e=>setMinimum(Number(e.target.value))}/></label>
 <button disabled={!projectId||!features||!quality||!modelId||running} onClick={()=>void submit(false)}>Classify full-resolution imagery</button>
 {validation&&<><p>Spatial holdout: accuracy {validation.overall_accuracy.toFixed(4)} · macro F1 {validation.macro_f1.toFixed(4)} · mIoU {validation.mean_iou.toFixed(4)} · {validation.cells} samples</p><button onClick={()=>setStudio(true)}>Model validation figures</button></>}
 <small>Outputs include class probabilities, entropy and training spectral distance. Forest votes are uncalibrated; spatial holdout does not establish external-site accuracy.</small>
 {error&&<p role="alert">{error}</p>}
 {studio&&model&&<ScientificFigureStudio initialTier="all" source={{name:'Spatial classification validation',csv,rasters:[],provenance:model.result as Record<string,unknown>,initialRecipe:'basic_column',initialBindings:{x:'class',y:'iou'}}} onClose={()=>setStudio(false)}/>}
 </fieldset>;
}
