import {useEffect,useRef,useState,type ReactNode} from 'react';
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
export function ProfilePlot({samples,length,onHover,mapIndex=null}:{samples:ProfileSample[];length:number;onHover:(pt:Position|null)=>void;mapIndex?:number|null}){
 const [index,setIndex]=useState<number|null>(null);
 const valid=samples.filter(s=>s.elevation_m!==null&&Number.isFinite(s.elevation_m));
 if(!valid.length)return <p className="discovery-error">No valid elevation samples.</p>;
 const lo=Math.min(...valid.map(s=>s.elevation_m!)),hi=Math.max(...valid.map(s=>s.elevation_m!)),top=hi===lo?hi+1:hi;
 const activeIndex=index??mapIndex;
 const selected=activeIndex===null?null:samples[activeIndex]??null;
 function choose(distance:number){
   let best=0;
   for(let i=1;i<samples.length;i++)if(Math.abs(samples[i].distance_m-distance)<Math.abs(samples[best].distance_m-distance))best=i;
   setIndex(best);onHover(samples[best].coordinate??null);
 }
 function download(){
   const csv='distance_m,elevation_m,longitude,latitude\n'+samples.map(p=>[p.distance_m,p.elevation_m??'',p.coordinate?.[0]??'',p.coordinate?.[1]??''].join(',')).join('\n');
   const a=document.createElement('a'),url=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.href=url;a.download='elevation-profile.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 return <div className="terrain-profile-chart" data-profile-selected-index={activeIndex??'none'}>
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
 const height=24+values.length*22;
 return <svg className="terrain-chart metric-chart" role="img" aria-label={label} viewBox={'0 0 345 '+height}>
   <text x="4" y="13" fontSize="10" fill="#526270">{label}</text>
   {values.map((v,i)=><g key={v.name}><text x="4" y={30+i*22} fontSize="10" fill="#263340">{v.name}</text>
    <rect x="97" y={19+i*22} width="169" height="13" fill="#dce3e7"/>
    <rect x="97" y={19+i*22} width={Math.max(0,Math.min(169,169*v.value/scale))} height="13" fill={v.color}/>
    <text x="340" y={30+i*22} fontSize="10" fill="#263340" textAnchor="end">{fmt(v.value)}</text></g>)}
 </svg>;
}

/** Full-resolution cell histogram and cumulative valid-area curve. */
export function ElevationDistribution({bins}:{bins:import('./api').TerrainDistributionBin[]}){
 const [active,setActive]=useState<number|null>(null);
 if(!bins.length)return null;
 const maximum=Math.max(1,...bins.map(b=>b.cells));
 const selected=active===null?null:bins[active];
 const dx=276/bins.length;
 const curve=['42,120',...bins.map((b,i)=>(42+(i+1)*dx)+','+(120-b.cumulative_pct))].join(' ');
 function download(){
   const text='lower_m,upper_m,cells,area_m2,cumulative_pct\n'+bins.map(b=>[b.lower_m,b.upper_m,b.cells,b.area_m2,b.cumulative_pct].join(',')).join('\n');
   const a=document.createElement('a'),url=URL.createObjectURL(new Blob([text],{type:'text/csv'}));a.href=url;a.download='elevation-distribution.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 return <div className="terrain-profile-chart">
   <svg viewBox="0 0 360 155" role="img" aria-label="Elevation distribution and cumulative area"
       onPointerMove={e=>{const b=e.currentTarget.getBoundingClientRect();const x=(e.clientX-b.left)/b.width*360;setActive(Math.max(0,Math.min(bins.length-1,Math.floor((x-42)/dx))));}}
       onPointerLeave={()=>setActive(null)}>
     <rect x="42" y="20" width="276" height="100" fill="#f4f7f9"/>
     {[0,.5,1].map(t=><g key={t}><line x1="42" x2="318" y1={120-t*100} y2={120-t*100} stroke="#d6dee4"/>
       <text x="38" y={123-t*100} textAnchor="end" fontSize="9" fill="#526270">{fmt(t*maximum)}</text>
       <text x="322" y={123-t*100} fontSize="9" fill="#526270">{t*100}%</text></g>)}
     {bins.map((b,i)=><rect key={i} x={42+i*dx+.5} y={120-100*b.cells/maximum} width={Math.max(0,dx-1)} height={100*b.cells/maximum} fill={active===i?'#c18732':'#3977aa'}/>)}
     <polyline points={curve} fill="none" stroke="#ad6026" strokeWidth="2"/>
     <text x="42" y="11" fontSize="9" fill="#526270">Cells</text><text x="318" y="11" textAnchor="end" fontSize="9" fill="#ad6026">Cumulative area</text>
     <text x="42" y="133" fontSize="9" fill="#526270">{fmt(bins[0].lower_m)}</text>
     <text x="318" y="133" textAnchor="end" fontSize="9" fill="#526270">{fmt(bins[bins.length-1].upper_m)}</text>
     <text x="180" y="148" textAnchor="middle" fontSize="9" fill="#526270">Elevation (m)</text>
   </svg>
   <div className="profile-readout">{selected?fmt(selected.lower_m)+'–'+fmt(selected.upper_m)+' m · '+selected.cells.toLocaleString()+' cells · '+fmt(selected.cumulative_pct)+'% cumulative':'Blue: cell frequency · Brown: cumulative area'}</div>
   <input aria-label="Elevation distribution bin" type="range" min="0" max={Math.max(0,bins.length-1)} value={active??0} onChange={e=>setActive(Number(e.target.value))}/>
   <div className="survey-action-bar"><span>{bins.length} elevation bins</span><button onClick={download}>CSV</button></div>
 </div>;
}

/** A single result pane switches between inspector and modal, avoiding duplicate plots. */
function saveBlob(blob:Blob,name:string){const a=document.createElement('a'),url=URL.createObjectURL(blob);a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function chartCanvas(node:Element):Promise<HTMLCanvasElement>{
 if(node instanceof HTMLCanvasElement)return Promise.resolve(node);
 return new Promise((resolve,reject)=>{
   const img=new Image(),svg=node instanceof SVGElement;
   let data:Blob|null=null;
   if(svg){const copy=node.cloneNode(true) as SVGSVGElement;const vb=copy.viewBox.baseVal;copy.setAttribute('width',String(vb.width||600));copy.setAttribute('height',String(vb.height||300));copy.setAttribute('xmlns','http://www.w3.org/2000/svg');data=new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml;charset=utf-8'});}
   const url=data?URL.createObjectURL(data):(node as HTMLImageElement).src;
   img.onload=()=>{const c=document.createElement('canvas');c.width=svg?1200:img.naturalWidth;c.height=svg?Math.max(1,Math.round(1200*img.naturalHeight/img.naturalWidth)):img.naturalHeight;const ctx=c.getContext('2d');if(!ctx){if(data)URL.revokeObjectURL(url);reject(Error('Canvas unavailable'));return;}ctx.fillStyle='white';ctx.fillRect(0,0,c.width,c.height);ctx.drawImage(img,0,0,c.width,c.height);if(data)URL.revokeObjectURL(url);resolve(c);};
   img.onerror=()=>{if(data)URL.revokeObjectURL(url);reject(Error('Unable to render plot'));};img.src=url;
 });
}
/** Minimal standards-compliant single-page PDF embedding a chart JPEG. */
export function chartPDF(jpeg:Uint8Array,width:number,height:number){
 const encode=(s:string)=>new TextEncoder().encode(s);
 const chunks:BlobPart[]=[],offsets:number[]=[0];let position=0;
 function put(v:string|Uint8Array){const b=typeof v==='string'?encode(v):v;chunks.push(new Uint8Array(b));position+=b.byteLength;}
 function obj(n:number,body:string){offsets[n]=position;put(n+' 0 obj\n'+body+'\nendobj\n');}
 put('%PDF-1.4\n');
 const pageW=612,pageH=792,w=Math.min(540,700*width/height),h=w*height/width;
 obj(1,'<< /Type /Catalog /Pages 2 0 R >>');obj(2,'<< /Type /Pages /Kids [3 0 R] /Count 1 >>');
 obj(3,'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 '+pageW+' '+pageH+'] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>');
 offsets[4]=position;put('4 0 obj\n<< /Type /XObject /Subtype /Image /Width '+width+' /Height '+height+' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length '+jpeg.length+' >>\nstream\n');put(jpeg);put('\nendstream\nendobj\n');
 const command='q '+w+' 0 0 '+h+' '+((pageW-w)/2)+' '+((pageH-h)/2)+' cm /Im0 Do Q\n';
 obj(5,'<< /Length '+encode(command).length+' >>\nstream\n'+command+'endstream');
 const xref=position;put('xref\n0 6\n0000000000 65535 f \n'+offsets.slice(1).map(n=>String(n).padStart(10,'0')+' 00000 n \n').join('')+'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+xref+'\n%%EOF\n');
 return new Blob(chunks,{type:'application/pdf'});
}
export function ResultPane({expanded,onClose,children,title='Terrain results'}:{expanded:boolean;onClose:()=>void;children:ReactNode;title?:string}){
 const ref=useRef<HTMLDialogElement>(null),content=useRef<HTMLDivElement>(null),[error,setError]=useState('');
 const [plots,setPlots]=useState<string[]>([]),[plot,setPlot]=useState(0);
 const selector='svg.terrain-chart, .terrain-profile-chart svg, .dem-mesh canvas, .terrain-profile-chart img, .terrain-overview-preview';
 useEffect(()=>{if(!expanded)return;const names=Array.from(content.current?.querySelectorAll(selector)??[]).map(n=>n.getAttribute('aria-label')??n.getAttribute('alt')??'Plot');setPlots(old=>JSON.stringify(old)===JSON.stringify(names)?old:names);setPlot(i=>Math.min(i,Math.max(0,names.length-1)));},[expanded,children]);
 useEffect(()=>{if(expanded&&ref.current&&!ref.current.open)ref.current.showModal();},[expanded]);
 async function exportPlot(format:string){
   const node=content.current?.querySelectorAll(selector)[plot];
   if(!node){setError('No graphical plot in this result. Use data export.');return;}
   try{
     setError('');
     if(format==='SVG'){
       if(!(node instanceof SVGElement))throw Error('SVG is only available for vector charts.');
       const n=node.cloneNode(true) as SVGElement;n.setAttribute('xmlns','http://www.w3.org/2000/svg');saveBlob(new Blob([new XMLSerializer().serializeToString(n)],{type:'image/svg+xml'}),'terrain-chart.svg');return;
     }
     const canvas=await chartCanvas(node);
     if(format==='PNG'){const blob=await new Promise<Blob|null>(r=>canvas.toBlob(r,'image/png'));if(!blob)throw Error('PNG encoding failed');saveBlob(blob,'terrain-chart.png');}
     else{const jpeg=Uint8Array.from(atob(canvas.toDataURL('image/jpeg',.92).split(',')[1]),c=>c.charCodeAt(0));saveBlob(chartPDF(jpeg,canvas.width,canvas.height),'terrain-chart.pdf');}
   }catch(e){setError(e instanceof Error?e.message:String(e));}
 }
 // Keep the dialog shell independent of tab content, including export controls.
 const panel=<section className="terrain-output" aria-label="Terrain results">
   <div ref={content} className={expanded?'terrain-review-body':undefined}>{children}</div>
   {expanded&&plots.length>0&&<div className="terrain-review-export"><select aria-label="Plot to export" value={plot} onChange={e=>setPlot(Number(e.target.value))}>{plots.map((name,i)=><option key={i} value={i}>{name}</option>)}</select>{['SVG','PNG','PDF'].map(format=><button key={format} onClick={()=>void exportPlot(format)}>{format}</button>)}</div>}
   {error&&<small className="terrain-review-error" role="alert">{error}</small>}</section>;
 return expanded?<dialog ref={ref} className="terrain-result-dialog" aria-label="Terrain result review" onCancel={e=>{e.preventDefault();onClose();}}>
   <header className="terrain-review-header"><strong>{title}</strong><button type="button" onClick={onClose} aria-label="Close review">Close</button></header>{panel}
 </dialog>:panel;
}

/** Area-elevation relation derived from the actual valid-cell histogram, not a fitted DEM. */
export function hypsometricPoints(bins:import('./api').TerrainDistributionBin[]){
 if(!bins.length)return [];
 const minimum=Math.min(...bins.map(b=>b.lower_m)),maximum=Math.max(...bins.map(b=>b.upper_m));
 const relief=Math.max(maximum-minimum,1e-12);
 return [{area_above:1,relative_elevation:0},...bins.map(b=>({
   area_above:Math.max(0,Math.min(1,1-b.cumulative_pct/100)),
   relative_elevation:Math.max(0,Math.min(1,(b.upper_m-minimum)/relief)),
 }))].sort((a,b)=>a.area_above-b.area_above);
}
export function HypsometricPlot({bins}:{bins:import('./api').TerrainDistributionBin[]}){
 const points=hypsometricPoints(bins);
 if(!points.length)return null;
 const line=points.map(p=>(46+p.area_above*260).toFixed(2)+','+(124-p.relative_elevation*103).toFixed(2)).join(' ');
 const area=points.reduce((sum,p,i)=>i?sum+Math.abs(points[i-1].area_above-p.area_above)*
   (points[i-1].relative_elevation+p.relative_elevation)/2:0,0);
 return <div className="terrain-research-figure">
   <svg className="terrain-chart" viewBox="0 0 345 161" role="img" aria-label="Hypsometric curve">
     <rect x="46" y="21" width="260" height="103" fill="#f4f8fa"/>
     {[0,.25,.5,.75,1].map(t=><g key={t}>
       <line x1={46+t*260} x2={46+t*260} y1="21" y2="124" stroke="#dbe5ea"/>
       <line x1="46" x2="306" y1={124-t*103} y2={124-t*103} stroke="#dbe5ea"/>
       <text x={46+t*260} y="139" textAnchor="middle" fontSize="9" fill="#5b7181">{Math.round(t*100)}%</text>
       <text x="40" y={127-t*103} textAnchor="end" fontSize="9" fill="#5b7181">{t.toFixed(2)}</text>
     </g>)}
     <polyline points={line} fill="none" stroke="#246b91" strokeWidth="2.5" strokeLinejoin="round"/>
     <text x="176" y="155" textAnchor="middle" fontSize="10" fill="#4c6475">Relative area above elevation</text>
     <text x="46" y="13" fontSize="9" fill="#4c6475">Relative elevation</text>
   </svg>
   <div className="profile-readout">Hypsometric integral ≈ {area.toFixed(3)} · valid DEM cells</div>
 </div>;
}
/** Consecutive valid profile stations only; no slope is inferred across nodata gaps. */
export function profileGrades(samples:ProfileSample[]){
 const grades:Array<{distance_m:number;grade_pct:number}>=[];
 for(let i=1;i<samples.length;i++){
   const previous=samples[i-1],current=samples[i],distance=current.distance_m-previous.distance_m;
   if(previous.elevation_m===null||current.elevation_m===null||!Number.isFinite(previous.elevation_m)||
      !Number.isFinite(current.elevation_m)||!Number.isFinite(distance)||distance<=0)continue;
   grades.push({distance_m:(previous.distance_m+current.distance_m)/2,
      grade_pct:100*(current.elevation_m-previous.elevation_m)/distance});
 }
 return grades;
}
export function ProfileGradePlot({samples}:{samples:ProfileSample[]}){
 const grades=profileGrades(samples);
 if(!grades.length)return null;
 const lo=Math.min(0,...grades.map(p=>p.grade_pct)),hi=Math.max(0,...grades.map(p=>p.grade_pct));
 const range=Math.max(hi-lo,.001),distance=Math.max(1,samples.at(-1)?.distance_m??1);
 const bars=grades.map((p,i)=>{const x=46+(p.distance_m/distance)*260;
   const zero=122-((0-lo)/range)*97,top=122-((p.grade_pct-lo)/range)*97;
   return <line key={i} x1={x} x2={x} y1={zero} y2={top} stroke={p.grade_pct>=0?'#277f75':'#bd7943'} strokeWidth="2.5"/>;
 });
 return <div className="terrain-research-figure">
   <svg className="terrain-chart" viewBox="0 0 345 157" role="img" aria-label="Longitudinal profile grade">
     <rect x="46" y="25" width="260" height="97" fill="#f4f8fa"/>
     <line x1="46" x2="306" y1={122-((0-lo)/range)*97} y2={122-((0-lo)/range)*97} stroke="#8495a2" strokeDasharray="3 3"/>
     {bars}
     <text x="46" y="15" fontSize="10" fill="#4c6475">Grade (%)</text>
     <text x="42" y="29" fontSize="9" textAnchor="end" fill="#4c6475">{hi.toFixed(1)}</text>
     <text x="42" y="123" fontSize="9" textAnchor="end" fill="#4c6475">{lo.toFixed(1)}</text>
     <text x="46" y="138" fontSize="9" fill="#4c6475">0</text>
     <text x="306" y="138" textAnchor="end" fontSize="9" fill="#4c6475">{fmt(distance)} m</text>
     <text x="176" y="152" fontSize="10" textAnchor="middle" fill="#4c6475">Distance along line</text>
   </svg>
   <div className="profile-readout">Steepest climb {fmt(Math.max(0,hi))}% · descent {fmt(Math.min(0,lo))}%</div>
 </div>;
}
/** Exact per-class spatial shares: computed from valid classified source cells. */
export interface TerrainClassRow{
 label:string;color:string;cells:number;sharePct:number;cumulativePct:number;
 areaM2:number;cumulativeAreaM2:number;
}
export function terrainClassStatistics(
 bins:readonly {label:string;color:string;cells:number}[],cellAreaM2:number,
):TerrainClassRow[]{
 const total=bins.reduce((sum,b)=>sum+(Number.isFinite(b.cells)&&b.cells>0?b.cells:0),0);
 const area=Number.isFinite(cellAreaM2)&&cellAreaM2>0?cellAreaM2:0;
 let cumulative=0;
 return bins.map(bin=>{
  const cells=Number.isFinite(bin.cells)&&bin.cells>0?bin.cells:0;
  cumulative+=cells;
  return {label:bin.label,color:bin.color,cells,
   sharePct:total?cells*100/total:0,
   cumulativePct:total?cumulative*100/total:0,
   areaM2:cells*area,cumulativeAreaM2:cumulative*area};
 });
}
export function terrainClassesCsv(bins:readonly {label:string;color:string;cells:number}[],cellAreaM2:number){
 const rows=terrainClassStatistics(bins,cellAreaM2);
 return ['class,cells,percent_valid,area_m2,cumulative_percent,cumulative_area_m2',
  ...rows.map(row=>[
   '"'+row.label.replaceAll('"','""')+'"',row.cells,
   row.sharePct.toFixed(8),row.areaM2.toFixed(4),
   row.cumulativePct.toFixed(8),row.cumulativeAreaM2.toFixed(4),
  ].join(','))].join('\n')+'\n';
}
/** Dual-axis class-share bars and cumulative share line. Class order comes from
 * the analytical legend, never from ranked or sorted display categories. */
export function TerrainCumulativeArea({bins,cellAreaM2}:{
 bins:{label:string;color:string;cells:number}[];cellAreaM2:number;
}){
 const rows=terrainClassStatistics(bins,cellAreaM2);
 if(!rows.length)return null;
 const step=274/rows.length;
 const barWidth=Math.min(26,step*.64);
 const x=(i:number)=>46+step*(i+.5);
 const y=(pct:number)=>158-pct*1.10;
 const points=rows.map((r,i)=>x(i).toFixed(2)+','+y(r.cumulativePct).toFixed(2)).join(' ');
 return <svg className="terrain-chart terrain-cumulative-chart"
   viewBox="0 0 345 225" role="img" aria-label="Class share and cumulative area">
   {[0,25,50,75,100].map(pct=><g key={pct}>
     <line x1="37" y1={y(pct)} x2="330" y2={y(pct)}
       stroke="#e5edf1" strokeWidth="1"/>
     <text x="32" y={y(pct)+3} textAnchor="end" fill="#6b8190" fontSize="9">{pct}%</text>
   </g>)}
   {rows.map((r,i)=><g key={i}>
     <rect x={x(i)-barWidth/2} y={y(r.sharePct)}
       width={barWidth} height={Math.max(0,y(0)-y(r.sharePct))}
       fill={r.color} opacity=".85">
       <title>{r.label}: {r.sharePct.toFixed(2)}% · {r.areaM2.toFixed(1)} m²</title>
     </rect>
     <text x={x(i)} y="172" textAnchor="middle" fontSize="8" fill="#506b7d">{i+1}</text>
   </g>)}
   <polyline points={points} fill="none" stroke="#164f76" strokeWidth="2.4"/>
   {rows.map((r,i)=><circle key={i} cx={x(i)} cy={y(r.cumulativePct)} r="3"
     fill="#164f76"><title>{r.label}: {r.cumulativePct.toFixed(2)}% cumulative</title></circle>)}
   <text x="172" y="192" textAnchor="middle" fill="#405e72" fontSize="10">
     Classes ordered as listed in the source raster legend (1–{rows.length})
   </text>
   <text x="172" y="207" textAnchor="middle" fill="#70889a" fontSize="9">
     Bars: class % · Line: cumulative valid-area %
   </text>
  </svg>;
}
export function TerrainClassTable({bins,cellAreaM2}:{
 bins:{label:string;color:string;cells:number}[];cellAreaM2:number;
}){
 const rows=terrainClassStatistics(bins,cellAreaM2);
 if(!rows.length)return null;
 return <table className="terrain-class-data-table" aria-label="Terrain class area statistics">
   <thead><tr><th scope="col">Class</th><th scope="col">Cells</th>
     <th scope="col">Valid %</th><th scope="col">Area (km²)</th><th scope="col">Cum. %</th></tr></thead>
   <tbody>{rows.map((r,i)=><tr key={i}>
     <th scope="row"><span className="terrain-class-swatch" style={{background:r.color}}/>{r.label}</th>
     <td>{r.cells.toLocaleString()}</td><td>{r.sharePct.toFixed(2)}</td>
     <td>{(r.areaM2/1e6).toFixed(4)}</td><td>{r.cumulativePct.toFixed(2)}</td>
   </tr>)}</tbody>
  </table>;
}

export function TerrainClassShare({bins}:{bins:{label:string;color:string;cells:number}[]}){
 const positive=bins.filter(b=>Number.isFinite(b.cells)&&b.cells>0);
 const total=positive.reduce((sum,b)=>sum+b.cells,0);
 if(!total)return null;
 const sorted=[...positive].sort((a,b)=>b.cells-a.cells);
 const major=sorted.slice(0,5);
 const other=sorted.slice(5);
 const groups=other.length?[...major,{label:'Other',cells:other.reduce((n,b)=>n+b.cells,0),color:'#aab8c3'}]:major;
 let previous=0;
 return <div className="terrain-research-figure terrain-class-share">
   <svg className="terrain-chart" viewBox="0 0 345 205" role="img" aria-label="Terrain class composition">
     <circle cx="100" cy="101" r="62" stroke="#edf2f6" fill="none" strokeWidth="27"/>
     {groups.map(b=>{const fraction=b.cells/total,start=previous;previous+=fraction;
       return <circle key={b.label} cx="100" cy="101" r="62" fill="none" stroke={b.color}
         strokeWidth="27" strokeDasharray={Math.max(0,fraction*389.56-.6)+' 389.56'}
         strokeDashoffset={-start*389.56} transform="rotate(-90 100 101)">
         <title>{b.label}: {(100*fraction).toFixed(1)}% ({b.cells.toLocaleString()} cells)</title>
       </circle>;
     })}
     <text x="100" y="98" fontSize="17" fontWeight="700" textAnchor="middle" fill="#26465b">{total.toLocaleString()}</text>
     <text x="100" y="115" fontSize="10" textAnchor="middle" fill="#688092">cells</text>
     {groups.map((b,i)=><g key={b.label} transform={'translate(188 '+(45+i*26)+')'}>
       <rect width="8" height="8" rx="2" fill={b.color}/>
       <text x="14" y="8" fontSize="10" fill="#3e586b">{b.label.length>17?b.label.slice(0,16)+'…':b.label}</text>
       <text x="14" y="20" fontSize="9" fill="#728796">{(b.cells/total*100).toFixed(1)}%</text>
     </g>)}
   </svg>
 </div>;
}
export function AspectRose({bins}:{bins:{label:string;color:string;cells:number}[]}){
 const directions=bins.filter(b=>b.label!=='Flat'),flat=bins.find(b=>b.label==='Flat');
 const max=Math.max(1,...directions.map(x=>x.cells));
 return <svg className="terrain-aspect-rose terrain-chart" viewBox="0 0 240 240" role="img" aria-label="Slope aspect rose">
   {[25,50,75,90].map(r=><circle key={r} cx="120" cy="120" r={r} fill="none" stroke="#c7d2da"/>)}
   {directions.map((b,i)=>{const t=i*Math.PI/4,r=90*b.cells/max,a=t-.32,z=t+.32;
    return <g key={b.label}><path d={'M120 120 L'+(120+r*Math.sin(a))+' '+(120-r*Math.cos(a))+' A'+r+' '+r+' 0 0 1 '+(120+r*Math.sin(z))+' '+(120-r*Math.cos(z))+' Z'} fill={b.color}><title>{b.label}: {b.cells} cells</title></path>
    <text x={120+103*Math.sin(t)} y={124-103*Math.cos(t)} textAnchor="middle" fontSize="11">{b.label}</text></g>;})}
   {flat&&<text x="120" y="238" textAnchor="middle" fontSize="9">Flat: {flat.cells} cells</text>}
 </svg>;
}
export function SectionPlot({sections,onHover}:{sections:NonNullable<import('./api').AdvancedTerrainResult['sections']>;onHover:(p:Position|null)=>void}){
 const [index,setIndex]=useState(0);const section=sections[Math.min(index,sections.length-1)];
 if(!section)return null;
 function csv(){saveBlob(new Blob(['station_m,offset_m,elevation_m,longitude,latitude\n'+sections.flatMap(s=>s.samples.map(p=>[s.station_m,p.offset_m,p.elevation_m??'',...p.coordinate].join(','))).join('\n')],{type:'text/csv'}),'cross-sections.csv');}
 return <div><label>Station <select value={index} onChange={e=>{onHover(null);setIndex(Number(e.target.value));}}>{sections.map((s,i)=><option key={i} value={i}>{fmt(s.station_m)} m</option>)}</select></label>
 <ProfilePlot key={index} samples={section.samples} length={section.length_m} onHover={onHover}/><small>Distance is measured from right edge; centerline at {fmt(section.length_m/2)} m.</small><button onClick={csv}>All sections CSV</button></div>;
}
