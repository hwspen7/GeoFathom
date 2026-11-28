import EnglishFileInput from './EnglishFileInput';
import {useEffect,useRef,useState} from 'react';
import ScientificFigureStudio from './ScientificFigureStudio';
import {cancelGISJob,downloadBuildingArtifact,getBuildingResearch,getGISJob,installBuildingModel,
  queueGISJob,uploadBuildingStudy,type BuildingResearchCatalog,type GISJob,type VisionModel} from './api';

type Metric={classes:Array<{name:string;f1:number;iou:number;precision:number;recall:number}>;objects_50?:{f1:number}};
type StudyResult={kind?:string;validation?:Record<string,Metric>;test?:Record<string,Metric>;test_evaluated?:boolean;
  history?:Array<{epoch:number;training_loss:number|null;validation_loss:number}>;
  best_epoch?:number;initial_validation_loss?:number;selected_validation_loss?:number;test_used_for_training?:boolean;
  validation_improved?:boolean;device?:string;artifacts?:Record<string,unknown>;suggested_model_id?:string};

export default function BuildingResearchPanel(p:{projectId:string|null;token:string;models:VisionModel[];onInstalled:()=>void}){
  const [catalog,setCatalog]=useState<BuildingResearchCatalog|null>(null);
  const [dataset,setDataset]=useState(''),[initial,setInitial]=useState('');
  const [selected,setSelected]=useState<string[]>([]),[epochs,setEpochs]=useState(12);
  const [learningRate,setLearningRate]=useState(.001),[mode,setMode]=useState<'head'|'decoder'>('head');
  const [device,setDevice]=useState<'cpu'|'cuda'>('cpu'),[holdout,setHoldout]=useState(false);
  const [enhancedTraining,setEnhancedTraining]=useState(false);
  const [augmentation,setAugmentation]=useState<'none'|'flips'>('none');
  const [job,setJob]=useState<GISJob|null>(null),[busy,setBusy]=useState(false);
  const [figures,setFigures]=useState(false);
  const [error,setError]=useState(''),[message,setMessage]=useState('');
  const project=useRef(p.projectId);project.current=p.projectId;
  useEffect(()=>{let active=true;
    if(p.token)void getBuildingResearch(p.token).then(value=>{if(active){setCatalog(value);setDataset(old=>old||value.datasets[0]?.id||'');}})
      .catch(e=>{if(active)setError(String(e.message??e));});
    return()=>{active=false;};
  },[p.token]);
  useEffect(()=>{
    setInitial(old=>p.models.some(m=>m.id===old&&m.trainable)?old:p.models.find(m=>m.trainable)?.id||'');
    setSelected(old=>old.length?old.filter(id=>p.models.some(m=>m.id===id)):p.models.slice(0,2).map(m=>m.id));
  },[p.models]);
  useEffect(()=>{setJob(null);setFigures(false);setMessage('');setError('');},[p.projectId]);
  useEffect(()=>{
    if(!p.projectId||!job||!['queued','running'].includes(job.status))return;
    const id=p.projectId;let active=true;
    const timer=window.setInterval(()=>void getGISJob(id,job.id,true).then(value=>{
      if(active&&project.current===id)setJob(value);
    }).catch(e=>{if(active)setError(String(e.message??e));}),1250);
    return()=>{active=false;window.clearInterval(timer);};
  },[p.projectId,job?.id,job?.status]);
  const processing=busy||!!job&&['queued','running'].includes(job.status);
  const result=job?.status==='completed'?job.result as StudyResult:null;
  const figureCSV=result?.kind==='building_train'?['epoch,training_loss,validation_loss',
    ...(result.history||[]).filter(row=>row.training_loss!==null).map(row=>[row.epoch,row.training_loss,row.validation_loss].join(','))].join('\n'):
    ['model,pixel_f1,iou,recall,object_f1',...Object.entries(result?.test_evaluated?result.test||{}:result?.validation||{}).map(([id,metric])=>{
      const b=metric.classes.find(c=>c.name==='building');return [JSON.stringify(id),b?.f1,b?.iou,b?.recall,metric.objects_50?.f1].join(',');})].join('\n');
  const chosen=catalog?.datasets.find(d=>d.id===dataset);
  async function run(work:()=>Promise<void>){setBusy(true);setError('');try{await work();}catch(e){setError(String((e as Error).message??e));}finally{setBusy(false);}}
  async function submit(kind:'building_train'|'building_compare'){
    const id=p.projectId;if(!id||!dataset)return;
    const payload=kind==='building_train'?{dataset_id:dataset,training:{initial_model_id:initial,mode,epochs,learning_rate:learningRate,device,...(enhancedTraining?{enhanced_training:true}:{})}}:
      {dataset_id:dataset,model_ids:selected,evaluate_test:holdout,...(augmentation==='flips'?{augmentation}:{})};
    const created=await queueGISJob(id,kind,payload,p.token);
    if(project.current===id)setJob(created);
  }
  return <section aria-label="Building model research" className="professional-form">
    <p className="project-hint">Use frozen data with separate training, validation and test regions.
      Parameters and model choice are fixed on validation data before any test evaluation.</p>
    <label>Frozen study package
      <EnglishFileInput aria-label="Building study ZIP" type="file" accept=".zip" disabled={!p.token||processing}
        onChange={e=>{const file=e.target.files?.[0];if(file)void run(async()=>{
          const value=await uploadBuildingStudy(file,p.token);const updated=await getBuildingResearch(p.token);
          setCatalog(updated);setDataset(value.id);setMessage('Imported a verified, region-disjoint building study.');
        });}}/>
    </label>
    <select aria-label="Frozen building dataset" value={dataset} disabled={processing}
      onChange={e=>setDataset(e.target.value)}><option value="">Choose a frozen study</option>
      {(catalog?.datasets||[]).map(d=><option key={d.id} value={d.id}>{d.id.slice(0,12)} · {d.counts.train} train / {d.counts.validation} validation / {d.counts.test} test</option>)}
    </select>
    {chosen&&<p className="project-hint" aria-label="Building dataset regions">
      Training: {chosen.regions.train.join(', ')}. Validation: {chosen.regions.validation.join(', ')}. Test: {chosen.regions.test.join(', ')}.
    </p>}
    <details><summary>Train or fine-tune a model</summary>
      <label>Initial model<select aria-label="Initial trainable building model" value={initial} disabled={processing}
        onChange={e=>setInitial(e.target.value)}><option value="">Choose a trainable checkpoint</option>
        {p.models.filter(m=>m.trainable).map(m=><option key={m.id}>{m.id}</option>)}
      </select></label>
      <label>Adaptation scope<select aria-label="Building adaptation scope" value={mode} onChange={e=>setMode(e.target.value as typeof mode)}>
        <option value="head">Mask, boundary and distance heads</option><option value="decoder">Decoder and prediction heads</option>
      </select></label>
      <label>Epochs<input aria-label="Building training epochs" type="number" min={1} max={100} value={epochs} onChange={e=>setEpochs(Number(e.target.value))}/></label>
      <label>Learning rate<input aria-label="Building learning rate" type="number" min={.000001} max={.05} step={.0001} value={learningRate} onChange={e=>setLearningRate(Number(e.target.value))}/></label>
      <label>Training device<select aria-label="Building training device" value={device} onChange={e=>setDevice(e.target.value as typeof device)}>
        <option value="cpu">CPU</option><option value="cuda">CUDA GPU</option>
      </select></label>
      <label><input aria-label="Enhanced building training" type="checkbox" checked={enhancedTraining} disabled={processing}
        onChange={e=>setEnhancedTraining(e.target.checked)}/> Augmentation, learning-rate decay and early stopping</label>
      {!catalog?.training_runtime_available&&<p className="compact-notice">Training dependencies are not installed in this environment.</p>}
      <button disabled={processing||!p.projectId||!p.token||!dataset||!initial||!catalog?.training_runtime_available}
        onClick={()=>void run(()=>submit('building_train'))}>Train building model</button>
    </details>
    <details><summary>Compare models and validate instances</summary>
      <fieldset disabled={processing}><legend>Comparison models</legend>{p.models.map(m=><label key={m.id}>
        <input type="checkbox" checked={selected.includes(m.id)} onChange={e=>setSelected(old=>e.target.checked?[...old,m.id]:old.filter(id=>id!==m.id))}/>{m.id}
      </label>)}</fieldset>
      <label>Inference mode<select aria-label="Building comparison inference mode" value={augmentation} disabled={processing}
        onChange={e=>setAugmentation(e.target.value as typeof augmentation)}>
        <option value="none">Standard</option><option value="flips">Four-view fusion (experimental)</option>
      </select></label>
      <label><input aria-label="Evaluate frozen building test regions" type="checkbox" checked={holdout} disabled={processing}
        onChange={e=>setHoldout(e.target.checked)}/> Evaluate test regions after validation selection</label>
      <button disabled={processing||!p.projectId||!p.token||!dataset||selected.length<2||selected.length>5}
        onClick={()=>void run(()=>submit('building_compare'))}>Compare building models</button>
    </details>
    {job&&<p role="status">{job.kind==='building_train'?'Training':'Comparison'} · {job.status} · {job.progress}%</p>}
    {job&&p.projectId&&['queued','running'].includes(job.status)&&<button onClick={()=>void run(async()=>{
      const value=await cancelGISJob(p.projectId!,job.id);if(project.current===p.projectId)setJob(value);
    })}>Cancel building research</button>}
    {job?.status==='failed'&&<p role="alert">{job.error}</p>}
    {result?.kind==='building_train'&&<div aria-label="Building training results">
      <p>Selected epoch: {result.best_epoch}. Validation loss: {result.initial_validation_loss?.toFixed(4)} → {result.selected_validation_loss?.toFixed(4)}.</p>
      <p>Test data used for training: {result.test_used_for_training?'yes':'no'} · device: {result.device}.</p>
      <button disabled={busy} onClick={()=>void run(async()=>{
        const installed=await installBuildingModel(p.projectId!,job!.id,p.token);p.onInstalled();setMessage('Installed '+installed.model_id+'. Review validation and holdout performance before use.');
      })}>Install trained building model</button>
    </div>}
    {result?.kind==='building_compare'&&<div aria-label="Building comparison results">
      <p>{result.test_evaluated?'Frozen test results':'Validation results; test regions remain unscored'}</p>
      <table><thead><tr><th>Model</th><th>Pixel F1</th><th>IoU</th><th>Recall</th><th>Object F1</th></tr></thead>
        <tbody>{Object.entries(result.test_evaluated?result.test||{}:result.validation||{}).map(([id,metric])=>{
          const building=metric.classes.find(c=>c.name==='building');return <tr key={id}><td>{id}</td>
            <td>{building?.f1.toFixed(3)}</td><td>{building?.iou.toFixed(3)}</td><td>{building?.recall.toFixed(3)}</td><td>{metric.objects_50?.f1.toFixed(3)}</td></tr>;
        })}</tbody></table>
      <p className="project-hint">Model ranking uses validation data. Test scores describe the frozen study and do not guarantee accuracy in other regions.</p>
    </div>}
    {result&&p.projectId&&job&&<button disabled={busy} onClick={()=>void run(()=>downloadBuildingArtifact(p.projectId!,job.id,'research.zip'))}>Download building research bundle</button>}
    {result&&<button onClick={()=>setFigures(true)}>Open building research figures</button>}
    {figures&&result&&<ScientificFigureStudio onClose={()=>setFigures(false)} source={{
      name:result.kind==='building_train'?'Building learning history':result.test_evaluated?'Frozen building test comparison':'Building validation comparison',
      csv:figureCSV,provenance:result,initialRecipe:result.kind==='building_train'?'multi_line':'grouped_bar',
      initialBindings:result.kind==='building_train'?{x:'epoch',columns:['training_loss','validation_loss']}:{x:'model',columns:['pixel_f1','object_f1']}}}/>}
    {message&&<p className="project-info">{message}</p>}
    {error&&<p role="alert">{error}</p>}
  </section>;
}
