import {useState} from 'react';
import type {Position} from './editing';

export interface ProfileSample{distance_m:number;elevation_m:number|null;coordinate?:Position}
const fmt=(n:number)=>n.toLocaleString('en-US',{maximumFractionDigits:1});
/** Preserve nodata gaps and real distance spacing: don't reconnect missing elevations. */
export function profileSegments(samples:ProfileSample[],length:number,lo:number,hi:number){
 const segments:string[][]=[];let current:string[]=[];
 for(const sample of samples){
   if(sample.elevation_m===null||!Number.isFinite(sample.elevation_m)){
     if(current.length)segments.push(current);current=[];continue;
   }
   current.push((42+sample.distance_m/(length||1)*286).toFixed(2)+','+(125-(sample.elevation_m-lo)/(hi-lo||1)*105).toFixed(2));
 }
 if(current.length)segments.push(current);
 return segments.map(s=>s.join(' '));
}
export function ProfilePlot({samples,length,onHover}:{samples:ProfileSample[];length:number;onHover:(pt:Position|null)=>void}){
 const [index,setIndex]=useState<number|null>(null);
 const valid=samples.filter(s=>s.elevation_m!==null&&Number.isFinite(s.elevation_m));
 if(!valid.length)return <p className="discovery-error">No valid elevation samples.</p>;
 const lo=Math.min(...valid.map(s=>s.elevation_m!)),hi=Math.max(...valid.map(s=>s.elevation_m!)),top=hi===lo?hi+1:hi;
 const selected=index===null?null:samples[index];
 function choose(distance:number){
   let best=0;
   for(let i=1;i<samples.length;i++)if(Math.abs(samples[i].distance_m-distance)<Math.abs(samples[best].distance_m-distance))best=i;
   setIndex(best);onHover(samples[best].coordinate??null);
 }
 function download(){
   const csv='distance_m,elevation_m,longitude,latitude\n'+samples.map(p=>[p.distance_m,p.elevation_m??'',p.coordinate?.[0]??'',p.coordinate?.[1]??''].join(',')).join('\n');
   const a=document.createElement('a'),url=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.href=url;a.download='elevation-profile.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 return <div className="terrain-profile-chart">
   <svg viewBox="0 0 345 153" role="img" aria-label="Interactive elevation profile"
     onPointerMove={e=>{const b=e.currentTarget.getBoundingClientRect();choose(Math.max(0,Math.min(1,((e.clientX-b.left)/b.width*345-42)/286))*length);}}
     onPointerLeave={()=>{setIndex(null);onHover(null);}}>
     <rect x="42" y="20" width="286" height="105" fill="#f4f7f9"/>
     {[0,.5,1].map(t=><g key={t}><line x1="42" x2="328" y1={125-t*105} y2={125-t*105} stroke="#d6dee4"/>
       <text x="38" y={128-t*105} textAnchor="end" fontSize="9" fill="#526270">{fmt(lo+t*(top-lo))}</text>
       <text x={42+t*286} y="138" textAnchor="middle" fontSize="9" fill="#526270">{fmt(t*length)}</text></g>)}
     <text x="42" y="12" fontSize="9" fill="#526270">Elevation (m)</text><text x="185" y="150" textAnchor="middle" fontSize="9" fill="#526270">Distance (m)</text>
     {profileSegments(samples,length,lo,top).map((segment,i)=><polyline key={i} points={segment} fill="none" stroke="#2771a6" strokeWidth="2"/>)}
     {selected&&<><line x1={42+selected.distance_m/length*286} x2={42+selected.distance_m/length*286} y1="20" y2="125" stroke="#b97835" strokeDasharray="3 2"/>
       {selected.elevation_m!==null&&<circle cx={42+selected.distance_m/length*286} cy={125-(selected.elevation_m-lo)/(top-lo)*105} r="3.5" fill="#b97835"/>}</>}
   </svg>
   <div className="profile-readout" aria-live="off">{selected?fmt(selected.distance_m)+' m · '+(selected.elevation_m===null?'No data':fmt(selected.elevation_m)+' m elevation'):fmt(lo)+'–'+fmt(hi)+' m · '+fmt(length)+' m length'}</div>
   <input aria-label="Profile sample position" type="range" min="0" max={Math.max(1,length)} value={selected?.distance_m??0} onChange={e=>choose(Number(e.target.value))}/>
   <div className="survey-action-bar"><span>{valid.length}/{samples.length} valid</span><button onClick={download}>CSV</button></div>
 </div>;
}
export function MetricBars({label,values,max}:{label:string;values:Array<{name:string;value:number;color:string}>;max?:number}){
 const scale=max??Math.max(1,...values.map(v=>v.value));
 return <div className="terrain-bars" role="img" aria-label={label}>
   <small>{label}</small>{values.map(v=><div key={v.name}><span>{v.name}</span><div className="terrain-bar-track"><span style={{width:Math.max(0,Math.min(100,v.value/scale*100))+'%',background:v.color}}/></div><strong>{fmt(v.value)}</strong></div>)}
 </div>;
}
