import {useState,useEffect,useRef} from 'react';
import {Shapes} from 'lucide-react';
import {bufferGeometry,compareAreas,applyOverlay,type Measurement} from './api';
export interface AnalysisFeature {id:string;name:string;geometry:GeoJSON.Geometry}
export default function GeometryAnalysis({geometry,selectedId,features,connected,onResult}:{geometry:GeoJSON.Geometry|null;selectedId:string|null;
 features:AnalysisFeature[];connected:boolean;onResult:(g:GeoJSON.Geometry,m:Measurement,name:string)=>void}){
 const [distance,setDistance]=useState('25'),[target,setTarget]=useState(''),[notice,setNotice]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const generation=useRef(0);
 useEffect(()=>{generation.current++;setBusy(false);setNotice('');setError('');return()=>{generation.current++;};},[geometry,selectedId]);
 const other=features.find(f=>f.id===target&&f.id!==selectedId);
 const polygon=(g:GeoJSON.Geometry|null|undefined)=>g?.type==='Polygon'||g?.type==='MultiPolygon';
 async function run(operation:'buffer'|'union'|'difference'|'intersection'|'compare'){
   if(!geometry||!connected)return;
   const seq=++generation.current;
   setBusy(true);setNotice('');setError('');
   try{
     if(operation==='buffer'){
       const meters=Number(distance);
       if(!Number.isFinite(meters)||meters<=0||meters>100000)throw Error('Buffer distance must be 0–100,000 m.');
       const result=await bufferGeometry(geometry,meters);
       if(seq===generation.current){onResult(result.geometry,result.measurement,'Buffer '+meters+' m');setNotice(result.warning);}
     }else if(other&&polygon(geometry)&&polygon(other.geometry)){
       if(operation==='compare'){
         const result=await compareAreas(geometry,other.geometry);
         if(seq===generation.current)setNotice('A: '+result.left_area_m2.toFixed(2)+' m² · B: '+result.right_area_m2.toFixed(2)+' m² · Difference: '+result.difference_m2.toFixed(2)+' m²');
       }else{
         const result=await applyOverlay(operation,geometry,other.geometry);
         if(seq===generation.current){
           if(!result.geometry||!result.measurement)throw Error('No overlapping result.');
           onResult(result.geometry,result.measurement,operation+' result');
         }
       }
     }
   }catch(failure){if(seq===generation.current)setError(failure instanceof Error?failure.message:String(failure));}
   finally{if(seq===generation.current)setBusy(false);}
 }
 return <div className="professional-panel geometry-analysis">
   {!connected&&<small>Reconnect API to run spatial analysis.</small>}
   <section className="analysis-tool-group" aria-label="Geometry processing">
     <h3 className="analysis-tool-heading"><Shapes size={13} aria-hidden="true"/> Geometry</h3>
     <div className="professional-form">
     <div className="analysis-inline"><label className="analysis-inline-label">Buffer (m)<input aria-label="Buffer distance" type="number" min=".01" step="any" value={distance} onChange={e=>setDistance(e.target.value)}/></label>
     <button disabled={!connected||!geometry||busy} onClick={()=>void run('buffer')}>Create buffer</button></div>
     <select aria-label="Analysis second feature" value={target} onChange={e=>setTarget(e.target.value)}>
       <option value="">Compare / combine with…</option>{features.filter(f=>f.id!==selectedId&&polygon(f.geometry)).map(f=><option key={f.id} value={f.id}>{f.name}</option>)}
     </select>
     <div className="survey-action-bar analysis-four-actions">{(['union','intersection','difference','compare'] as const).map(op=>
       <button key={op} disabled={!connected||busy||!polygon(geometry)||!other} onClick={()=>void run(op)}>{op==='difference'?'Subtract':op[0].toUpperCase()+op.slice(1)}</button>)}</div>
     {notice&&<p className="project-info">{notice}</p>}{error&&<p className="discovery-error">{error}</p>}
   </div></section>
 </div>;
}
