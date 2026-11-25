import {useState} from 'react';
import {getScientificJobRecipe,repeatScientificJob,type GISJob} from './api';
import {saveFigureBlob} from './figureExport';

export default function RemoteExperimentControls({projectId,job,onJob}:{projectId:string;job:GISJob;onJob:(j:GISJob)=>void}){
 const [allowChange,setAllowChange]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 if(job.status!=='completed'||!job.result||!('reproducibility' in (job.result as object)))return null;
 async function recipe(){setBusy(true);setError('');try{
  const data=await getScientificJobRecipe(projectId,job.id);
  saveFigureBlob(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),'remote-experiment.json');
 }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function repeat(){setBusy(true);setError('');try{onJob(await repeatScientificJob(projectId,job.id,allowChange));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <fieldset disabled={busy}><legend>Reproduce this experiment</legend>
 <button onClick={()=>void recipe()}>Export verified experiment recipe</button>
 <label><input type="checkbox" checked={allowChange} onChange={e=>setAllowChange(e.target.checked)}/>Allow changes in algorithm software</label>
 <button onClick={()=>void repeat()}>Repeat with verified inputs</button>
 <small>Input and model checksums are checked before scheduling and against execution snapshots. Version changes are recorded.</small>
 {error&&<p role="alert">{error}</p>}</fieldset>;
}
