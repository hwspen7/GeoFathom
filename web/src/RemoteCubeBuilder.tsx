import {useRef,useState} from 'react';
import {queueRemoteCubeJob,registerRemoteJobImagery,type GISJob,type RasterAsset} from './api';

export interface CubeReceipt {roles:string[];times:number[];time_origin:string;band_layout:Array<{band:number;role:string}>}
interface Band {image_id:string;band:number;encoding:string;scale:number;offset:number;unit:string}
interface Quality {image_id:string;band:number;scheme:string;roles:string[]}
interface Acquisition {id:string;datetime:string;sensor:string;bands:Record<string,Band>;quality:Quality[]}

export default function RemoteCubeBuilder({projectId,bands,quality,job,onJob,onCube}:{
 projectId?:string|null;bands:Record<string,Band>|null;quality:Quality[]|null;job:GISJob|null;
 onJob:(job:GISJob)=>void;onCube:(asset:RasterAsset,receipt:CubeReceipt,role:string)=>void;
}){
 const [acquisitions,setAcquisitions]=useState<Acquisition[]>([]),[datetime,setDatetime]=useState(''),[sensor,setSensor]=useState('');
 const [target,setTarget]=useState(''),[harmonization,setHarmonization]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[role,setRole]=useState('');
 const sequence=useRef(0);
 const receipt=job?.kind==='remote_cube'&&job.status==='completed'?job.result as CubeReceipt:null;
 function add(){if(!bands||!quality)return;try{
  if(!/(Z|[+-]\d\d:\d\d)$/.test(datetime)||!Number.isFinite(Date.parse(datetime)))throw Error('Enter an acquisition datetime with a timezone.');
  if(acquisitions.length&&Date.parse(datetime)<=Date.parse(acquisitions.at(-1)!.datetime))throw Error('Add acquisitions in increasing time order.');
  if(!sensor.trim())throw Error('Declare the sensor or harmonized product.');
  const id='acquisition-'+(++sequence.current);
  setAcquisitions(old=>[...old,{id,datetime,sensor:sensor.trim(),bands,quality}]);
  if(!target)setTarget(Object.values(bands)[0].image_id);setDatetime('');setError('');
 }catch(e){setError((e as Error).message);}}
 async function submit(){if(!projectId)return;setBusy(true);setError('');try{
  onJob(await queueRemoteCubeJob(projectId,{target_image_id:target,acquisitions,harmonization}));
 }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function reuse(){if(!projectId||!job||!receipt)return;setBusy(true);setError('');try{
  onCube(await registerRemoteJobImagery(projectId,job.id),receipt,role||receipt.roles[0]);
 }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <fieldset disabled={busy}><legend>Multi-date optical cube</legend>
 <p>Bind managed disk reflectance bands and QA above, then add each acquisition. The first acquisition supplies the reference grid.</p>
 <label>Acquisition datetime<input value={datetime} placeholder="2024-06-01T10:30:00Z" onChange={e=>setDatetime(e.target.value)}/></label>
 <label>Sensor or harmonized product<input value={sensor} onChange={e=>setSensor(e.target.value)}/></label>
 <button disabled={!bands||!quality||!datetime||!sensor.trim()||acquisitions.length>=64} onClick={add}>Add bound acquisition</button>
 <ol>{acquisitions.map((a,i)=><li key={a.id}>{a.datetime} · {a.sensor}<button onClick={()=>{const next=acquisitions.filter((_,j)=>j!==i);setAcquisitions(next);setTarget(next.length?Object.values(next[0].bands)[0].image_id:'');}}>Remove acquisition {i+1}</button></li>)}</ol>
 <label>Cross-sensor harmonization record<textarea value={harmonization} onChange={e=>setHarmonization(e.target.value)}/></label>
 <button disabled={!projectId||acquisitions.length<2||!!job&&['queued','running'].includes(job.status)} onClick={()=>void submit()}>Build disk time cube</button>
 {receipt&&<><label>Cube analysis band<select value={role||receipt.roles[0]} onChange={e=>setRole(e.target.value)}>{receipt.roles.map(r=><option key={r}>{r}</option>)}</select></label><button onClick={()=>void reuse()}>Use completed cube for analysis</button></>}
 {error&&<p role="alert">{error}</p>}</fieldset>;
}
