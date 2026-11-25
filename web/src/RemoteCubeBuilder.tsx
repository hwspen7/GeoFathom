import {useRef,useState} from 'react';
import {queueRemoteCubeJob,registerRemoteJobImagery,type GISJob,type RasterAsset} from './api';

export interface CubeReceipt {roles:string[];times:number[];time_origin:string;utc_datetimes?:string[];band_layout:Array<{band:number;role:string}>}
interface Band {image_id:string;band:number;encoding:string;scale:number;offset:number;unit:string}
interface Quality {image_id:string;band:number;scheme:string;roles:string[]}
interface Acquisition {id:string;datetime:string;sensor:string;bands:Record<string,Band>;quality:Quality[]}
interface Correction {gain:number;offset:number;reference_sensor:string;coefficient_source:string;brdf?:Record<string,number>}

export default function RemoteCubeBuilder({projectId,bands,quality,job,onJob,onCube,assets=[]}:{
 assets?:Array<{id:string;name:string}>;projectId?:string|null;bands:Record<string,Band>|null;quality:Quality[]|null;job:GISJob|null;
 onJob:(job:GISJob)=>void;onCube:(asset:RasterAsset,receipt:CubeReceipt,role:string)=>void;
}){
 const [acquisitions,setAcquisitions]=useState<Acquisition[]>([]),[datetime,setDatetime]=useState(''),[sensor,setSensor]=useState('');
 const [target,setTarget]=useState(''),[harmonization,setHarmonization]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[role,setRole]=useState('');
 const sequence=useRef(0);
 const [resampling,setResampling]=useState('bilinear'),[minimumCoverage,setMinimumCoverage]=useState(.8),[corrections,setCorrections]=useState<Record<string,Correction>>({}),[correct,setCorrect]=useState(false);
 const [registrationMask,setRegistrationMask]=useState(''),[registrationRole,setRegistrationRole]=useState(''),[registrationWindow,setRegistrationWindow]=useState('0,0,256,256');
 const receipt=job?.kind==='remote_cube'&&job.status==='completed'?job.result as CubeReceipt:null;
 function add(){if(!bands||!quality)return;try{
  if(!/(Z|[+-]\d\d:\d\d)$/.test(datetime)||!Number.isFinite(Date.parse(datetime)))throw Error('Enter an acquisition datetime with a timezone.');
  if(acquisitions.length&&Date.parse(datetime)<=Date.parse(acquisitions.at(-1)!.datetime))throw Error('Add acquisitions in increasing time order.');
  if(!sensor.trim())throw Error('Declare the sensor or harmonized product.');
  const id='acquisition-'+(++sequence.current);
  if(correct&&Object.keys(bands).some(r=>!corrections[r]))throw Error('Supply coefficients for every bound role.');
  setAcquisitions(old=>[...old,{id,datetime,sensor:sensor.trim(),bands,quality,...(correct?{corrections:Object.fromEntries(Object.keys(bands).map(r=>[r,corrections[r]]))}:{})}]);
  if(!target)setTarget(Object.values(bands)[0].image_id);setDatetime('');setError('');
 }catch(e){setError((e as Error).message);}}
 async function submit(){if(!projectId)return;setBusy(true);setError('');try{
  onJob(await queueRemoteCubeJob(projectId,{target_image_id:target,acquisitions,harmonization,resampling,minimum_coverage:minimumCoverage,
   ...(registrationMask?{registration:{mask_image_id:registrationMask,role:registrationRole||Object.keys(acquisitions[0].bands)[0],window:registrationWindow.split(',').map(Number)}}:{})}));
 }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function reuse(){if(!projectId||!job||!receipt)return;setBusy(true);setError('');try{
  onCube(await registerRemoteJobImagery(projectId,job.id),receipt,role||receipt.roles[0]);
 }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <fieldset disabled={busy}><legend>Multi-date optical cube</legend>
 <p>Bind managed disk reflectance bands and QA above, then add each acquisition. The first acquisition supplies the reference grid.</p>
 <label>Acquisition datetime<input value={datetime} placeholder="2024-06-01T10:30:00Z" onChange={e=>setDatetime(e.target.value)}/></label>
 <label>Sensor or harmonized product<input value={sensor} onChange={e=>setSensor(e.target.value)}/></label>
 <details><summary>Sensor and illumination corrections</summary><label><input type="checkbox" checked={correct} onChange={e=>setCorrect(e.target.checked)}/>Apply explicit band corrections</label>{correct&&Object.keys(bands??{}).map(r=>{const c=corrections[r]??{gain:1,offset:0,reference_sensor:acquisitions[0]?.sensor??sensor,coefficient_source:''};const update=(patch:Partial<Correction>)=>setCorrections(old=>({...old,[r]:{...c,...patch}}));return <div key={r}><strong>{r}</strong><label>{r} harmonization gain<input type="number" step="any" value={c.gain} onChange={e=>update({gain:Number(e.target.value)})}/></label><label>{r} harmonization offset<input type="number" step="any" value={c.offset} onChange={e=>update({offset:Number(e.target.value)})}/></label><label>{r} reference sensor<input value={c.reference_sensor} onChange={e=>update({reference_sensor:e.target.value})}/></label><label>{r} coefficient source<input value={c.coefficient_source} onChange={e=>update({coefficient_source:e.target.value})}/></label>
 <label><input type="checkbox" checked={!!c.brdf} onChange={e=>update({brdf:e.target.checked?{f_iso:.1,f_vol:.01,f_geo:0,solar_zenith:30,view_zenith:0,relative_azimuth:0,target_solar_zenith:30,target_view_zenith:0,target_relative_azimuth:0}:undefined})}/>Apply Ross–Li illumination correction for {r}</label>{c.brdf&&Object.entries(c.brdf).map(([key,value])=><label key={key}>{r} {key.replaceAll('_',' ')}<input type="number" step="any" value={value} onChange={e=>update({brdf:{...c.brdf,[key]:Number(e.target.value)}})}/></label>)}</div>;})}</details>
 <button disabled={!bands||!quality||!datetime||!sensor.trim()||acquisitions.length>=64} onClick={add}>Add bound acquisition</button>
 <ol>{acquisitions.map((a,i)=><li key={a.id}>{a.datetime} · {a.sensor}<button onClick={()=>{const next=acquisitions.filter((_,j)=>j!==i);setAcquisitions(next);setTarget(next.length?Object.values(next[0].bands)[0].image_id:'');}}>Remove acquisition {i+1}</button></li>)}</ol>
 <label>Cross-sensor harmonization record<textarea value={harmonization} onChange={e=>setHarmonization(e.target.value)}/></label>
 <label>Cube spatial resampling<select value={resampling} onChange={e=>setResampling(e.target.value)}><option value="bilinear">Bilinear point interpolation</option><option value="nearest">Nearest native sample</option><option value="area">Exact area-weighted support</option></select></label>
 {resampling==='area'&&<label>Minimum valid target-cell coverage<input type="number" min="0" max="1" step=".05" value={minimumCoverage} onChange={e=>setMinimumCoverage(Number(e.target.value))}/></label>}
 <details><summary>Stable-region registration check</summary><label>Registration control mask<select value={registrationMask} onChange={e=>setRegistrationMask(e.target.value)}><option value="">No registration check</option>{assets.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label><label>Registration role<input value={registrationRole} onChange={e=>setRegistrationRole(e.target.value)}/></label><label>Registration window (column,row,width,height)<input value={registrationWindow} onChange={e=>setRegistrationWindow(e.target.value)}/></label><small>Mask 1 fits translation; mask 2 independently checks radiometric residuals. Misaligned acquisitions fail before analysis.</small></details>
 <button disabled={!projectId||acquisitions.length<2||!!job&&['queued','running'].includes(job.status)} onClick={()=>void submit()}>Build disk time cube</button>
 {receipt&&<><label>Cube analysis band<select value={role||receipt.roles[0]} onChange={e=>setRole(e.target.value)}>{receipt.roles.map(r=><option key={r}>{r}</option>)}</select></label><button onClick={()=>void reuse()}>Use completed cube for analysis</button></>}
 {error&&<p role="alert">{error}</p>}</fieldset>;
}
