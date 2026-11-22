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
export function ResultPane({expanded,onClose,children}:{expanded:boolean;onClose:()=>void;children:ReactNode}){
 const ref=useRef<HTMLDialogElement>(null),content=useRef<HTMLElement>(null),[error,setError]=useState('');
 const [plots,setPlots]=useState<string[]>([]),[plot,setPlot]=useState(0);
 const selector='svg.terrain-chart, .terrain-profile-chart svg, .dem-mesh canvas, .terrain-profile-chart img';
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
 const panel=<section ref={content} className="terrain-output" aria-label="Terrain results">{children}
   {expanded&&<div className="survey-action-bar"><select aria-label="Plot to export" value={plot} onChange={e=>setPlot(Number(e.target.value))}>{plots.map((name,i)=><option key={i} value={i}>{name}</option>)}</select>{['SVG','PNG','PDF'].map(format=><button key={format} onClick={()=>void exportPlot(format)}>{format}</button>)}</div>}
   {error&&<small role="alert">{error}</small>}</section>;
 return expanded?<dialog ref={ref} className="terrain-result-dialog" aria-label="Expanded terrain result" onCancel={e=>{e.preventDefault();onClose();}}>{panel}</dialog>:panel;
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
