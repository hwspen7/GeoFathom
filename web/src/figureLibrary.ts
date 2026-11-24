/** Plot recipes keep numerical tables, geometry and export styles in one model. */
import type {PlotData} from './api';
import type {PersistedTerrainResult} from './terrainResultStore';
export type FigureKind='histogram'|'cdf'|'exceedance'|'density'|'box'|'quantile'|'qq'|'class_bar'|'class_dot'|'rose'|'profile'|'grade'|'metrics'|'scatter'|'joint_density'|'experiment_line'|'experiment_bar'|'experiment_dot'|'experiment_interval';
export interface FigureRecipe {id:FigureKind;title:string;description:string;category:string}
export const FIGURES:FigureRecipe[]=[
 {id:'histogram',title:'Histogram',description:'Exact counts or area within numerical bins',category:'Distribution'},
 {id:'cdf',title:'Cumulative distribution',description:'Area at or below a value',category:'Distribution'},
 {id:'exceedance',title:'Exceedance curve',description:'Area strictly above a value',category:'Distribution'},
 {id:'density',title:'Frequency density',description:'Normalized histogram density; no fitted smoothing',category:'Distribution'},
 {id:'box',title:'Box and whisker',description:'Quartiles, median and observed 1.5 IQR whiskers',category:'Distribution'},
 {id:'quantile',title:'Quantile curve',description:'Recorded quantiles of the numerical population',category:'Distribution'},
 {id:'qq',title:'Normal Q–Q',description:'Observed versus theoretical normal quantiles',category:'Diagnostics'},
 {id:'scatter',title:'Elevation–result scatter',description:'Aligned value pairs with explicit sampling and all-cell correlation',category:'Relationships'},
 {id:'joint_density',title:'Elevation–result density',description:'Two-dimensional frequency using every aligned valid cell',category:'Relationships'},
 {id:'class_bar',title:'Class area bars',description:'Classified area or frequency by class',category:'Composition'},
 {id:'class_dot',title:'Class dot plot',description:'Compact class comparison without filled bars',category:'Composition'},
 {id:'rose',title:'Aspect rose',description:'Directional frequencies; flat cells excluded',category:'Direction'},
 {id:'profile',title:'Elevation profile',description:'Distance and elevation with NoData gaps',category:'Profiles'},
 {id:'grade',title:'Profile grade',description:'Signed segment grade from adjacent valid samples',category:'Profiles'},
 {id:'experiment_line',title:'Parameter response',description:'Numeric response at actual parameter values; missing results remain gaps',category:'Experiments'},
 {id:'experiment_bar',title:'Scenario bars',description:'One physical metric across named scenarios',category:'Experiments'},
 {id:'experiment_dot',title:'Scenario dots',description:'Named values without misleading connecting lines',category:'Experiments'},
 {id:'experiment_interval',title:'Model coverage interval',description:'Conditional empirical bounds, mean and deterministic baseline',category:'Experiments'},
 {id:'metrics',title:'Metric comparison',description:'Select quantities with the same physical unit',category:'Summary'},
];
export interface FigureSettings {kind:FigureKind;title:string;x_label:string;y_label:string;bins:number;
 measure:'percent'|'cells'|'area';palette:'mono'|'blue'|'earth';font:'sans'|'serif';font_size:number;
 grid:boolean;x_log:boolean;y_log:boolean;width_mm:number;height_mm:number;dpi:number;series:number;sectors:number;metric_keys:string[];}
export function defaultFigure(data:PlotData):FigureSettings{
 const kind:FigureKind=data.experiment_series?(data.experiment_series.interval_label?'experiment_interval':data.experiment_series.numeric?'experiment_line':'experiment_bar'):data.histograms?'histogram':data.kind==='directional'?'rose':data.kind==='profile'?'profile':data.classes.length?'class_bar':'metrics';
 return {kind,title:data.quantity.replaceAll('_',' ')+': '+(availableFigures(data).find(f=>f.id===kind)?.title??'Summary'),x_label:'',y_label:'',bins:data.histograms?.['40']?40:Number(Object.keys(data.histograms??{})[0]??40),measure:'percent',palette:'mono',font:'sans',font_size:16,grid:true,x_log:false,y_log:false,width_mm:160,height_mm:110,dpi:300,series:0,sectors:16,metric_keys:[]};
}
export function availableFigures(data:PlotData):FigureRecipe[]{
 return FIGURES.filter(f=>{
  if(f.id==='experiment_line')return !!data.experiment_series?.numeric;
  if(f.id==='experiment_bar'||f.id==='experiment_dot')return !!data.experiment_series&&!data.experiment_series.numeric&&!data.experiment_series.interval_label;
  if(f.id==='experiment_interval')return !!data.experiment_series?.interval_label;
  if(['scatter','joint_density'].includes(f.id))return !!data.joint;
  if(f.id==='histogram')return !!data.histograms;
  if(f.id==='density')return !!data.histograms&&Object.values(data.histograms).some(bins=>bins.some(b=>b.density!==null&&Number.isFinite(b.density)));
  if(['cdf','exceedance'].includes(f.id))return !!data.cdf?.length;
  if(f.id==='box')return !!data.box;
  if(f.id==='quantile')return !!data.quantiles?.length;
  if(f.id==='qq')return !!data.normal_qq?.length;
  if(['class_bar','class_dot'].includes(f.id))return data.classes.length>0;
  if(f.id==='rose')return !!data.roses;
  if(['profile','grade'].includes(f.id))return !!data.profiles?.length;
  return !!data.metrics&&Object.values(data.metrics).some(Number.isFinite);
 }).map(f=>data.joint?.identity_line&&f.id==='scatter'?{...f,title:'Baseline–candidate agreement',description:'Paired physical values with a 1:1 reference line'}:data.joint?.identity_line&&f.id==='joint_density'?{...f,title:'Paired frequency map'}:f);
}
export function localPlotData(record:PersistedTerrainResult):PlotData|null{
 if(record.profile){
  const samples=record.profile.samples;
  return {schema:'geofathom-plot-data-1',kind:'profile',quantity:'Elevation',unit:'m',valid_cells:samples.filter(s=>s.elevation_m!==null).length,cell_area_m2:0,classes:[],
   notes:['Distance is geodesic along the recorded line. Gaps are preserved.'],
   profiles:[{name:'Elevation profile',points:samples.map(s=>({x:s.distance_m,y:s.elevation_m}))}]};
 }
 if(record.advanced?.sections?.length){
  return {schema:'geofathom-plot-data-1',kind:'profile',quantity:'Cross-section elevation',unit:'m',valid_cells:record.advanced.valid_cells,cell_area_m2:record.advanced.cell_area_m2,classes:[],notes:['Cross-section distances and sampled elevations are retained.'],
   profiles:record.advanced.sections.map(s=>({name:'Station '+s.station_m.toFixed(1)+' m',points:s.samples.map(p=>({x:p.offset_m,y:p.elevation_m}))}))};
 }
 if(record.advanced?.plot_data)return record.advanced.plot_data;
 if(record.advanced&&!record.advanced.raster){
  const a=record.advanced;
  const base:PlotData={schema:'geofathom-plot-data-1',kind:'summary',operation:a.operation,quantity:record.title,unit:'',valid_cells:a.valid_cells,cell_area_m2:a.cell_area_m2,classes:[],metrics:a.metrics,notes:[a.warning]};
  if(a.distribution){base.kind='binned';base.quantity='Elevation';base.unit='m';base.histograms={[String(a.distribution.length)]:a.distribution.map(b=>({lower:b.lower_m,upper:b.upper_m,midpoint:(b.lower_m+b.upper_m)/2,cells:b.cells,area_m2:b.area_m2,percent:100*b.cells/Math.max(1,a.valid_cells),density:b.upper_m>b.lower_m?b.cells/Math.max(1,a.valid_cells)/(b.upper_m-b.lower_m):null,cumulative_pct:b.cumulative_pct}))};}
  return base;
 }
 return null;
}
export function metricUnit(key:string):string{
 const units:Record<string,string>={cells:'cells',m3:'m3',m2:'m2',m:'m',deg:'deg',pct:'%'};
 for(const [suffix,unit] of Object.entries(units))if(key.endsWith('_'+suffix))return unit;
 if(key.startsWith('product_'))return 'product';
 return key; // Unknown quantities are never silently mixed on one axis.
}
export interface PlotTable {columns:string[];rows:Array<Array<string|number|null>>;x_label:string;y_label:string;unit:string;note?:string}
export function figureTable(data:PlotData,s:FigureSettings):PlotTable{
 const unit=data.unit==='degree'?'deg':data.unit||'',quantity=data.quantity.replaceAll('_',' ');
 const key=unit==='degree'?'deg':unit.replace(/[^a-zA-Z0-9]+/g,'_').replace(/^_|_$/g,'')||'value';
 if(s.kind==='scatter'&&data.joint)return {columns:[data.joint.identity_line?'baseline_'+key:'elevation_m',data.joint.identity_line?'candidate_'+key:'result_'+key],rows:data.joint.samples.map(p=>[p.x,p.y]),x_label:data.joint.x_quantity+' ('+data.joint.x_unit+')',y_label:data.joint.y_quantity+' ('+data.joint.y_unit+')',unit:data.joint.y_unit,note:'Systematic sample; see metadata for full population statistics.'};
 if(s.kind==='joint_density'&&data.joint)return {columns:data.joint.identity_line?['baseline_lower_'+key,'baseline_upper_'+key,'candidate_lower_'+key,'candidate_upper_'+key,'cells','area_m2']:['elevation_lower_m','elevation_upper_m','result_lower_'+key,'result_upper_'+key,'cells','area_m2'],rows:data.joint.density_cells.map(b=>[b.x_lower,b.x_upper,b.y_lower,b.y_upper,b.cells,b.area_m2]),x_label:data.joint.x_quantity+' ('+data.joint.x_unit+')',y_label:data.joint.y_quantity+' ('+data.joint.y_unit+')',unit:data.joint.y_unit};
 const sample=data.population==='monte_carlo_realizations';
 if(s.kind.startsWith('experiment_')&&data.experiment_series){const series=data.experiment_series;return {columns:['label','x','value_'+key,'lower_'+key,'upper_'+key,'baseline_'+key],rows:series.points.map(p=>[p.label,p.x,p.value,p.low??null,p.high??null,p.baseline??null]),x_label:series.x_label,y_label:quantity+(unit?' ('+unit+')':''),unit,note:series.interval_label};}
 const yTitle=sample?(s.measure==='cells'?'Realizations':'Realizations (%)'):s.measure==='area'?'Projected area (m2)':s.measure==='cells'?'Valid cells':'Area share (%)';
 if(s.kind==='histogram'||s.kind==='density'){
  const choices=data.histograms??{},bins=choices[String(s.bins)]??Object.values(choices)[0]??[];
  return {columns:['lower_'+key,'upper_'+key,'midpoint_'+key,sample?'realizations':'cells',sample?'not_applicable':'area_m2','percent','density_per_'+key,'cumulative_pct'],rows:bins.map(b=>[b.lower,b.upper,b.midpoint,b.cells,sample?null:b.area_m2,b.percent,b.density,b.cumulative_pct]),x_label:quantity+' ('+unit+')',y_label:s.kind==='density'?'Probability density (1/'+unit+')':yTitle,unit};
 }
 if(s.kind==='cdf'||s.kind==='exceedance')return {columns:['value_'+key,sample?'realizations_le':'cells_le','percent_le','percent_gt'],rows:(data.cdf??[]).map(p=>[p.value,p.cells_le,p.percent_le,100-p.percent_le]),x_label:quantity+' ('+unit+')',y_label:s.kind==='cdf'?(sample?'Cumulative realizations (%)':'Cumulative area (%)'):(sample?'Exceedance realizations (%)':'Exceedance area (%)'),unit};
 if(s.kind==='quantile')return {columns:['probability','value_'+key],rows:(data.quantiles??[]).map(p=>[p.probability,p.value]),x_label:'Cumulative probability',y_label:quantity+' ('+unit+')',unit};
 if(s.kind==='qq')return {columns:['normal_quantile','observed_quantile_'+key,'probability'],rows:(data.normal_qq??[]).map(p=>[p.normal_quantile,p.observed_quantile,p.probability]),x_label:'Theoretical normal quantile',y_label:'Observed '+quantity+' ('+unit+')',unit};
 if(s.kind==='box')return {columns:['quantity','whisker_low_'+key,'q1_'+key,'median_'+key,'q3_'+key,'whisker_high_'+key,'lower_outliers','upper_outliers'],rows:data.box?[[quantity,data.box.whisker_low,data.box.q1,data.box.median,data.box.q3,data.box.whisker_high,data.box.lower_outliers,data.box.upper_outliers]]:[],x_label:quantity,y_label:quantity+' ('+unit+')',unit};
 if(s.kind==='class_bar'||s.kind==='class_dot')return {columns:['class','cells','area_m2','percent'],rows:data.classes.map(c=>[c.label,c.cells,c.area_m2,c.percent]),x_label:'Class',y_label:yTitle,unit};
 if(s.kind==='rose')return {columns:['bearing_deg','cells','area_m2','percent'],rows:(data.roses?.[String(s.sectors)]??[]).map(r=>[r.bearing_deg,r.cells,r.area_m2,r.percent]),x_label:'Downslope bearing (deg)',y_label:yTitle,unit:'deg'};
 if(s.kind==='profile'||s.kind==='grade'){
  const points=data.profiles?.[s.series]?.points??[];
  const rows=points.map((p,i)=>{
   if(s.kind==='profile')return [p.x,p.y];
   if(!i)return [p.x,null];const prev=points[i-1],dx=p.x-prev.x;
   return [(prev.x+p.x)/2,p.y===null||prev.y===null||dx<=0?null:100*(p.y-prev.y)/dx];
  });
  return {columns:['distance_m',s.kind==='grade'?'grade_pct':'elevation_m'],rows,x_label:'Distance (m)',y_label:s.kind==='grade'?'Signed grade (%)':'Elevation (m)',unit:s.kind==='grade'?'%':'m'};
 }
 const all=Object.keys(data.metrics??{}).filter(k=>Number.isFinite(data.metrics![k]));
 const selected=s.metric_keys.length?s.metric_keys:all.filter(k=>metricUnit(k)===metricUnit(all.find(k=>k.endsWith('_m3'))??all[0]??''));
 const first=metricUnit(selected[0]??'');
 return {columns:['metric','value'],rows:selected.filter(k=>metricUnit(k)===first&&Number.isFinite(data.metrics?.[k])).map(k=>[k,data.metrics![k]]),x_label:'Metric',y_label:'Value ('+(first==='product'?unit:first)+')',unit:first};
}
function csvCell(value:string|number|null):string{
 if(value===null)return '';
 let text=String(value);if(typeof value==='string'&&/^[=+@-]/.test(text))text="'"+text;
 return /[",\n\r]/.test(text)?'"'+text.replaceAll('"','""')+'"':text;
}
export function tableCSV(table:PlotTable){return [table.columns,...table.rows].map(row=>row.map(csvCell).join(',')).join('\r\n')+'\r\n';}
export interface Primitive {kind:'line'|'rect'|'polyline'|'polygon'|'circle'|'text';x?:number;y?:number;x2?:number;y2?:number;width?:number;height?:number;radius?:number;points?:Array<[number,number]>;text?:string;stroke?:string;fill?:string;line_width?:number;font_size?:number;font?:'sans'|'serif';anchor?:'start'|'middle'|'end';angle?:number;dashed?:boolean}
export interface FigureScene {width:number;height:number;width_mm:number;height_mm:number;title:string;primitives:Primitive[];note:string;error?:string}
const finite=(x:unknown):x is number=>typeof x==='number'&&Number.isFinite(x);
export function makeFigure(data:PlotData,s:FigureSettings):FigureScene{
 const table=figureTable(data,s),width=900,height=600,p:Primitive[]=[];
 const ink=s.palette==='blue'?'#225b87':s.palette==='earth'?'#826344':'#222222',fill=s.palette==='mono'?'#cccccc':s.palette==='blue'?'#b4cddd':'#d5c5af';
 const left=115,right=855,top=75,bottom=470,fw=right-left,fh=bottom-top;
 const text=(x:number,y:number,t:string,anchor:'start'|'middle'|'end'='start',size=s.font_size,angle=0)=>p.push({kind:'text',x,y,text:t,anchor,font_size:size,font:s.font,fill:'#222222',angle});
 const line=(x:number,y:number,x2:number,y2:number,color='#222222',dashed=false)=>p.push({kind:'line',x,y,x2,y2,stroke:color,line_width:1.3,dashed});
 const poly=(points:Array<[number,number]>,color=ink)=>p.push({kind:'polyline',points,stroke:color,fill:'none',line_width:2});
 const title=s.title||FIGURES.find(f=>f.id===s.kind)?.title||data.quantity;
 p.push({kind:'rect',x:0,y:0,width,height,fill:'#ffffff',line_width:0});text(width/2,35,title,'middle',s.font_size+5);
 const fmt=(n:number)=>{if(n===0)return '0';return Math.abs(n)>=1e5||Math.abs(n)<.001?n.toExponential(1):Number(n.toPrecision(4)).toString();};
 let xValues:number[]=[],yValues:number[]=[],categories:string[]=[],points:Array<[number,number|null]>=[];
 const col=s.measure==='cells'?1:s.measure==='area'?2:3;
 const categorical=['class_bar','class_dot','metrics','experiment_bar','experiment_dot','experiment_interval'].includes(s.kind);
 if(s.kind.startsWith('experiment_')){
  categories=table.rows.map(r=>String(r[0]));
  points=table.rows.map((r,i)=>[categorical?i:Number(r[1]),finite(r[2])?r[2]:null]);
  if(s.kind==='experiment_interval')yValues=table.rows.flatMap(r=>r.slice(2,6)).filter(finite);
 }else if(s.kind==='histogram'||s.kind==='density'){
  xValues=table.rows.flatMap(r=>[r[0],r[1]]).filter(finite);
  const i=s.kind==='density'?6:s.measure==='cells'?3:s.measure==='area'?4:5;
  points=table.rows.map(r=>[r[2] as number,finite(r[i])?r[i] as number:null]);
 }else if(s.kind==='joint_density'){xValues=table.rows.flatMap(r=>[r[0],r[1]]).filter(finite);yValues=table.rows.flatMap(r=>[r[2],r[3]]).filter(finite);}
 else if(s.kind==='cdf'||s.kind==='exceedance')points=table.rows.map(r=>[r[0] as number,r[s.kind==='cdf'?2:3] as number]);
 else if(['quantile','qq','profile','grade','scatter'].includes(s.kind))points=table.rows.map(r=>[r[0] as number,finite(r[1])?r[1] as number:null]);
 else if(categorical){categories=table.rows.map(r=>String(r[0]).replaceAll('_',' '));points=table.rows.map((r,i)=>[i,s.kind==='metrics'?r[1] as number:r[col] as number]);}
 else if(s.kind==='box'&&data.box){xValues=[0,1];yValues=[data.box.whisker_low,data.box.whisker_high,...(data.box.fliers??[])];}
 else if(s.kind==='rose'){xValues=[0,360];yValues=table.rows.map(r=>Number(r[col]));}
 if(!xValues.length)xValues=points.map(p=>p[0]).filter(finite);
 if(!yValues.length)yValues=points.map(p=>p[1]).filter(finite);
 const logX=s.x_log&&!categorical&&s.kind!=='box'&&s.kind!=='rose',logY=s.y_log&&s.kind!=='rose'&&s.kind!=='experiment_interval';
 const validX=xValues.filter(v=>!logX||v>0),validY=yValues.filter(v=>!logY||v>0);
 let xmin=categorical?-.5:Math.min(...validX),xmax=categorical?Math.max(.5,categories.length-.5):Math.max(...validX);
 let ymin=Math.min(...validY),ymax=Math.max(...validY);
 const bars=s.kind==='histogram'||s.kind==='class_bar'||s.kind==='metrics'||s.kind==='experiment_bar';
 if(bars&&!logY){ymin=Math.min(0,ymin);ymax=Math.max(0,ymax);}
 if(['cdf','exceedance'].includes(s.kind)&&!logY){ymin=0;ymax=100;}
 const invalidLogBox=s.kind==='box'&&logY&&!!data.box&&data.box.whisker_low<=0;
 const invalidLogBins=['histogram','joint_density'].includes(s.kind)&&logX&&table.rows.some(r=>Number(r[0])<=0);
 const invalidDensityY=s.kind==='joint_density'&&logY&&table.rows.some(r=>Number(r[2])<=0);
 if(!Number.isFinite(xmin)||!Number.isFinite(ymin)||invalidLogBox||invalidLogBins||invalidDensityY){
  text(450,280,'No finite values available on the selected axis scales.','middle');
  return {width,height,width_mm:s.width_mm,height_mm:s.height_mm,title,primitives:p,note:'Non-positive values cannot be shown on logarithmic axes.',error:'Choose a linear scale or strictly positive plot bounds.'};
 }
 if(xmax===xmin){xmin-=Math.max(.5,Math.abs(xmin)*.02);xmax+=Math.max(.5,Math.abs(xmax)*.02);if(logX)xmin=Math.max(xmax/10,Number.MIN_VALUE);}
 if(ymax===ymin){const span=Math.max(.5,Math.abs(ymin)*.05);ymin-=span;ymax+=span;if(logY)ymin=Math.max(ymax/10,Number.MIN_VALUE);}
 const probabilityAxis=['cdf','exceedance'].includes(s.kind)&&!logY;
 if(!logY&&!probabilityAxis)ymax+=(ymax-ymin)*.08;else if(logY)ymax*=1.08;
 const niceStep=(span:number)=>{const raw=span/5,power=10**Math.floor(Math.log10(raw)),fraction=raw/power;return (fraction<=1?1:fraction<=2?2:fraction<=2.5?2.5:fraction<=5?5:10)*power;};
 if(!categorical&&s.kind!=='box'&&!logX){const step=niceStep(xmax-xmin);xmin=Math.floor(xmin/step)*step;xmax=Math.ceil(xmax/step)*step;}
 if(!logY&&!probabilityAxis){const step=niceStep(ymax-ymin);ymin=Math.floor(ymin/step)*step;ymax=Math.ceil(ymax/step)*step;}
 const f=(v:number,lo:number,hi:number,log:boolean)=>log?(Math.log10(v)-Math.log10(lo))/(Math.log10(hi)-Math.log10(lo)):(v-lo)/(hi-lo);
 const x=(v:number)=>left+fw*f(v,xmin,xmax,logX),y=(v:number)=>bottom-fh*f(v,ymin,ymax,logY);
 const ticks=(lo:number,hi:number,log:boolean)=>{if(log)return Array.from({length:6},(_,i)=>10**(Math.log10(lo)+(Math.log10(hi)-Math.log10(lo))*i/5));const step=niceStep(hi-lo);return Array.from({length:Math.min(12,Math.floor((hi-lo)/step+1e-9)+1)},(_,i)=>lo+i*step);};
 if(s.kind!=='rose'){
  for(const tick of ticks(ymin,ymax,logY)){const yy=y(tick);if(s.grid)line(left,yy,right,yy,'#e2e2e2');text(left-13,yy+5,fmt(tick),'end');}
  line(left,top,left,bottom);line(left,bottom,right,bottom);
  if(categorical){categories.forEach((name,i)=>text(x(i),bottom+22,name.length>18?name.slice(0,16)+'…':name,'end',Math.max(11,s.font_size-2),-35));}
  else if(s.kind!=='box')for(const tick of ticks(xmin,xmax,logX)){line(x(tick),bottom,x(tick),bottom+5);text(x(tick),bottom+25,fmt(tick),'middle');}
  text((left+right)/2,555,s.x_label||table.x_label,'middle',s.font_size+1);text(26,(top+bottom)/2,s.y_label||table.y_label,'middle',s.font_size+1,-90);
 }
 const okay=(pt:[number,number|null])=>pt[1]!==null&&(!logX||pt[0]>0)&&(!logY||pt[1]>0);
 const zero=logY?bottom:y(0);
 if(s.kind==='joint_density'){
  const maximum=Math.max(1,...table.rows.map(r=>Number(r[4])));
  const shade=(value:number)=>{const t=Math.log1p(value)/Math.log1p(maximum);const rgb=s.palette==='blue'?[225-190*t,237-150*t,245-110*t]:s.palette==='earth'?[240-125*t,235-155*t,225-160*t]:[255-225*t,255-225*t,255-225*t];return '#'+rgb.map(v=>Math.round(v).toString(16).padStart(2,'0')).join('');};
  table.rows.forEach(r=>{if(Number(r[4])<=0)return;p.push({kind:'rect',x:x(Number(r[0])),y:y(Number(r[3])),width:x(Number(r[1]))-x(Number(r[0])),height:y(Number(r[2]))-y(Number(r[3])),fill:shade(Number(r[4])),line_width:0});});
  text(right,60,'Cell count (log color): 1 to '+fmt(maximum),'end',12);
 }else if(s.kind==='histogram')table.rows.forEach((r,i)=>{
  if(!okay(points[i]))return;const [lo,hi]=r as number[];if(logX&&(lo<=0||hi<=0))return;
  const yy=y(points[i][1]!);p.push({kind:'rect',x:x(lo),y:Math.min(yy,zero),width:Math.max(.5,x(hi)-x(lo)),height:Math.abs(zero-yy),fill,stroke:ink,line_width:.8});
 });
 else if(['class_bar','metrics','experiment_bar'].includes(s.kind))points.forEach(pt=>{if(!okay(pt))return;const yy=y(pt[1]!);p.push({kind:'rect',x:x(pt[0])-.32*fw/Math.max(1,categories.length),y:Math.min(yy,zero),width:.64*fw/Math.max(1,categories.length),height:Math.abs(zero-yy),fill,stroke:ink,line_width:1});});
 else if(s.kind==='experiment_interval'){
  table.rows.forEach((r,i)=>{const xx=x(i);const [value,lo,hi,base]=r.slice(2,6);if(finite(lo)&&finite(hi)){line(xx,y(lo),xx,y(hi),ink);line(xx-24,y(lo),xx+24,y(lo),ink);line(xx-24,y(hi),xx+24,y(hi),ink);}if(finite(value))p.push({kind:'circle',x:xx,y:y(value),radius:6,fill:ink,stroke:ink});if(finite(base))p.push({kind:'circle',x:xx,y:y(base),radius:5,fill:'#ffffff',stroke:ink,line_width:1.5});});
  text(right,60,(data.experiment_series?.interval_label??'Model interval')+' · filled: mean; open: baseline','end',12);
 }
 else if(s.kind==='box'&&data.box){
  const b=data.box,xx=(left+right)/2;line(xx,y(b.whisker_low),xx,y(b.whisker_high));
  for(const value of [b.whisker_low,b.whisker_high])line(xx-55,y(value),xx+55,y(value));
  p.push({kind:'rect',x:xx-95,y:y(b.q3),width:190,height:y(b.q1)-y(b.q3),fill,stroke:ink,line_width:1.8});line(xx-95,y(b.median),xx+95,y(b.median));
  for(const value of b.fliers??[])if(!logY||value>0)p.push({kind:'circle',x:xx,y:y(value),radius:2.6,fill:'none',stroke:ink,line_width:1});
  text(xx,510,`Outside fences: ${b.lower_outliers} below, ${b.upper_outliers} above`,'middle',s.font_size-1);
 }else if(s.kind==='rose'){
  // Radius encodes sqrt(frequency), so sector area is proportional to frequency.
  const rows=table.rows,max=Math.max(1,...rows.map(r=>Number(r[col]))),cx=450,cy=295,radius=190;
  for(let ring=1;ring<=4;ring++){p.push({kind:'circle',x:cx,y:cy,radius:radius*Math.sqrt(ring/4),stroke:'#cccccc',fill:'none',line_width:1});text(cx+5,cy-radius*Math.sqrt(ring/4)+14,fmt(max*ring/4),'start',12);}
  const sectors=rows.length,width=2*Math.PI/Math.max(1,sectors);
  rows.forEach(row=>{const theta=Number(row[0])*Math.PI/180,rr=radius*Math.sqrt(Number(row[col])/max),vertices:Array<[number,number]>=[[cx,cy]];
   for(let i=0;i<=8;i++){const a=theta-width/2+width*i/8;vertices.push([cx+rr*Math.sin(a),cy-rr*Math.cos(a)]);}p.push({kind:'polygon',points:vertices,fill,stroke:ink,line_width:1});});
  for(const [name,a] of [['N',0],['E',90],['S',180],['W',270]] as Array<[string,number]>)text(cx+215*Math.sin(a*Math.PI/180),cy-215*Math.cos(a*Math.PI/180)+5,name,'middle');
  text(450,555,s.y_label||table.y_label,'middle');
 }else{
  let segment:Array<[number,number]>=[];
  const flush=()=>{if(segment.length>1)poly(segment);else if(segment.length===1)p.push({kind:'circle',x:segment[0][0],y:segment[0][1],radius:2.5,fill:ink,stroke:ink,line_width:0});segment=[];};
  const cumulative=['cdf','exceedance'].includes(s.kind);
  if(cumulative&&points.length&&!logY&&(!logX||points[0][0]>0)){const initial=s.kind==='cdf'?0:100;segment.push([left,y(initial)],[x(points[0][0]),y(initial)]);}
  points.forEach(pt=>{
   if(!okay(pt)){flush();return;}
   const xx=x(pt[0]),yy=y(pt[1]!);
   if(['qq','class_dot','scatter','experiment_dot'].includes(s.kind)){
    if(s.kind==='class_dot')line(left,yy,xx,yy,'#dddddd');
    p.push({kind:'circle',x:xx,y:yy,radius:3,fill:ink,stroke:ink,line_width:0});
   }else{
    if(['cdf','exceedance'].includes(s.kind)&&segment.length)segment.push([xx,segment[segment.length-1][1]]);
    segment.push([xx,yy]);
    if(s.kind==='experiment_line')p.push({kind:'circle',x:xx,y:yy,radius:4,fill:ink,stroke:ink,line_width:0});
   }
  });
  if(cumulative&&segment.length)segment.push([right,segment[segment.length-1][1]]);
  flush();
  if(s.kind==='scatter'&&data.joint?.identity_line){
   const lo=Math.max(xmin,ymin),hi=Math.min(xmax,ymax);
   if(hi>lo)line(x(lo),y(lo),x(hi),y(hi),'#888888',true);
   text(right,60,'Dashed: 1:1 agreement','end',12);
  }
  if(s.kind==='qq'&&data.summary){
   const slope=(data.summary.q3-data.summary.q1)/(2*.6744897501960817),intercept=(data.summary.q1+data.summary.q3)/2;
   const start=slope>0?Math.max(xmin,(ymin-intercept)/slope):xmin;
   const end=slope>0?Math.min(xmax,(ymax-intercept)/slope):xmax;
   if(end>=start&&intercept+slope*start>=ymin&&intercept+slope*end<=ymax)line(x(start),y(intercept+slope*start),x(end),y(intercept+slope*end),'#888888',true);
  }
 }
 const note=(s.kind==='scatter'&&data.joint?`Shown ${data.joint.sample_cells} / ${data.joint.population_cells} aligned pairs; r = ${data.joint.pearson_r?.toPrecision(4)??'undefined'}. `:'')+(logX||logY?'Log axes omit non-positive values. ':'')+`n = ${(s.kind==='rose'?(data.directional_cells??data.valid_cells):data.valid_cells).toLocaleString('en-US')} ${s.kind==='rose'?'directional cells':data.kind==='profile'?'valid profile samples':data.population==='monte_carlo_realizations'?'realizations':data.experiment_series?'experiment observations':'valid raster cells'}`;
 text(115,585,note,'start',11);
 return {width,height,width_mm:s.width_mm,height_mm:s.height_mm,title,primitives:p,note};
}
