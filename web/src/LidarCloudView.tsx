import {useMemo,useState} from 'react';

/** Equal-scale orthographic preview. Analysis and full export never use this sample. */
export default function LidarCloudView({csv,columns,zField}:{csv:string;columns:string[];zField:string}){
 const [azimuth,setAzimuth]=useState(35),[elevation,setElevation]=useState(25);
 const cloud=useMemo(()=>{
   const indices=['x_m','y_m',zField].map(k=>columns.indexOf(k));
   if(indices.some(i=>i<0))return [];
   const raw=csv.trim().split(/\r?\n/).slice(1).map(row=>{
     const fields=row.split(',');
     return indices.map(i=>fields[i]?.trim()?Number(fields[i]):NaN);
   }).filter(row=>row.every(Number.isFinite));
   const count=Math.min(raw.length,2000);
   return Array.from({length:count},(_,i)=>raw[Math.floor(i*raw.length/count)]);
 },[csv,columns,zField]);
 const model=useMemo(()=>{
   if(!cloud.length)return null;
   const lo=[0,1,2].map(i=>Math.min(...cloud.map(p=>p[i]))),hi=[0,1,2].map(i=>Math.max(...cloud.map(p=>p[i])));
   const center=lo.map((x,i)=>(x+hi[i])/2),span=Math.max(1e-9,Math.hypot(...hi.map((x,i)=>x-lo[i])));
   const a=azimuth*Math.PI/180,e=elevation*Math.PI/180;
   function project(p:number[]){
     const [x,y,z]=p.map((v,i)=>(v-center[i])/span);
     const u=Math.cos(a)*x-Math.sin(a)*y,v=Math.sin(a)*x+Math.cos(a)*y;
     return {x:210+350*u,y:132-350*(Math.cos(e)*z-Math.sin(e)*v),depth:Math.cos(e)*v+Math.sin(e)*z};
   }
   const points=cloud.map((p,i)=>({...project(p),id:i,ratio:hi[2]===lo[2]?.5:(p[2]-lo[2])/(hi[2]-lo[2])})).sort((a,b)=>a.depth-b.depth);
   const origin=project(lo);
   const axes=[0,1,2].map(i=>{const end=[...lo];end[i]+=span*.13;return project(end);});
   return {points,origin,axes,lo,hi};
 },[cloud,azimuth,elevation]);
 if(!model)return null;
 return <div className="analysis-card" aria-label="Point cloud preview">
   <svg role="img" aria-label="Equal-scale orthographic point cloud" viewBox="0 0 420 270" style={{width:'100%',background:'#f4f6f8'}}>
     {model.axes.map((end,i)=><g key={i}><line x1={model.origin.x} y1={model.origin.y} x2={end.x} y2={end.y} stroke="#344054" strokeWidth="1.5"/><text x={end.x+3} y={end.y-3} fill="#344054" fontSize="10">{['X','Y',zField==='z_m'?'Z':zField][i]}</text></g>)}
     {model.points.map(p=><circle key={p.id} cx={p.x} cy={p.y} r="1.65" fill={'hsl('+String(225-180*p.ratio)+' 70% 42%)'} opacity=".85"/>)}
   </svg>
   <label>Azimuth (degrees)<input type="range" min="0" max="360" value={azimuth} onChange={e=>setAzimuth(Number(e.target.value))}/></label>
   <label>Elevation (degrees)<input type="range" min="-90" max="90" value={elevation} onChange={e=>setElevation(Number(e.target.value))}/></label>
   <small>{cloud.length.toLocaleString()} sampled result points · {zField}: {model.lo[2].toPrecision(5)} to {model.hi[2].toPrecision(5)} m · Equal XYZ scale; local projected view</small>
 </div>;
}
