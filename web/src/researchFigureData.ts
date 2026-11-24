/** Adapt completed experiments, not placeholder values, to the general figure library. */
import type {PlotData,ResearchResult} from './api';
import {metricUnit} from './figureLibrary';
export type ResearchFigureSource='values'|'delta'|'relative'|'response'|'derivative'|'interval'|'realizations'|'factorial';
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v);
const label=(s:string)=>s.replaceAll('_',' ');
function quantile(sorted:number[],p:number){const i=p*(sorted.length-1),lo=Math.floor(i),hi=Math.ceil(i);return sorted[lo]+(sorted[hi]-sorted[lo])*(i-lo);}
export function researchFigureData(result:ResearchResult,metric:string,source:ResearchFigureSource):PlotData|null{
 const row=result.metric_table.find(r=>r.metric===metric);
 const interval=result.uncertainty?.metrics[metric];
 const rawUnit=metricUnit(metric);
 const unit=rawUnit==='product'?(result.products[0]?.raster.unit??''):rawUnit===metric?'':rawUnit;
 const base:PlotData={schema:'geofathom-plot-data-1',kind:'summary',quantity:label(metric),unit,valid_cells:0,cell_area_m2:0,classes:[],notes:['Computed experiment values; no independent accuracy claim.']};
 if(source==='factorial'){
  const g=result.factorial;if(!g)return null;
  const cells=g.cells.map(c=>({x:c.x,y:c.y,value:c.matched_population&&finite(c.metrics[metric])?c.metrics[metric]:null}));
  const n=cells.filter(c=>c.value!==null).length;if(!n)return null;
  return {...base,valid_cells:n,population:'experiment_observations',parameter_grid:{x_label:label(g.x_parameter),y_label:label(g.y_parameter),x_values:g.x_values,y_values:g.y_values,cells},notes:['Every cell is a real production-engine evaluation; unmatched output masks remain missing. No interpolation or global sensitivity attribution.']};
 }
 if(source==='realizations'){
  const raw=result.uncertainty?.realizations?.[metric];if(!raw?.length||raw.some(v=>!finite(v)))return null;
  const sorted=[...raw].sort((a,b)=>a-b),n=sorted.length,lo=sorted[0],hi=sorted[n-1],q1=quantile(sorted,.25),median=quantile(sorted,.5),q3=quantile(sorted,.75),iqr=q3-q1;
  const inside=sorted.filter(v=>v>=q1-1.5*iqr&&v<=q3+1.5*iqr),below=sorted.filter(v=>v<inside[0]),above=sorted.filter(v=>v>inside[inside.length-1]);
  const mean=sorted.reduce((a,b)=>a+b,0)/n, start=hi===lo?lo-Math.max(.5,Math.abs(lo)*.005):lo, stop=hi===lo?hi+Math.max(.5,Math.abs(hi)*.005):hi;
  const histograms:NonNullable<PlotData['histograms']>={};
  for(const bins of [10,20,40,80]){const width=(stop-start)/bins,counts=Array<number>(bins).fill(0);for(const value of sorted)counts[Math.max(0,Math.min(bins-1,Math.floor((value-start)/width)))]++;let cumulative=0;histograms[String(bins)]=counts.map((cells,i)=>{cumulative+=cells;return {lower:start+i*width,upper:start+(i+1)*width,midpoint:start+(i+.5)*width,cells,area_m2:0,percent:100*cells/n,density:cells/n/width,cumulative_pct:100*cumulative/n};});}
  const counts=new Map<number,number>();sorted.forEach((v,i)=>counts.set(v,i+1));
  return {...base,kind:'continuous',population:'monte_carlo_realizations',valid_cells:n,histograms,
   cdf:Array.from(counts,([value,cells_le])=>({value,cells_le,percent_le:100*cells_le/n})),
   quantiles:[0,.01,.05,.1,.25,.5,.75,.9,.95,.99,1].map(probability=>({probability,value:quantile(sorted,probability)})),
   summary:{minimum:lo,maximum:hi,mean,population_std:Math.sqrt(sorted.reduce((s,v)=>s+(v-mean)**2,0)/n),q1,median,q3,iqr},
   box:{q1,median,q3,whisker_low:inside[0],whisker_high:inside[inside.length-1],lower_outliers:below.length,upper_outliers:above.length,fliers:[...below,...above]},
   notes:['Actual Monte Carlo realizations; area is not applicable. Equal-tail model intervals depend on the assumed errors and finite sample count.']};
 }
 const series:NonNullable<PlotData['experiment_series']>={numeric:false,x_label:'Scenario',points:[]};
 if(source==='interval'&&interval&&result.uncertainty){
  series.x_label='Model estimate';series.interval_label=(100*result.uncertainty.coverage).toFixed(0)+'% model coverage';
  series.points=[{label:'Monte Carlo',x:0,value:interval.mean,low:interval.low,high:interval.high,baseline:interval.baseline}];
  base.notes=[result.uncertainty.warning];
 }else if(source==='response'||source==='derivative'){
  if(!result.sensitivity.length)return null;
  series.numeric=true;series.x_label=label(result.sensitivity[0].parameter);
  series.points=[...result.sensitivity].sort((a,b)=>a.value-b.value).map(r=>({label:String(r.value),x:r.value,value:(source==='response'?r.metrics[metric]:r.derivatives[metric])??null}));
  if(source==='derivative'){base.quantity+=' — secant from baseline';base.unit=unit?unit+' / parameter unit':'per parameter unit';}
 }else if(row&&['values','delta','relative'].includes(source)){
  const values=source==='delta'?row.deltas:source==='relative'?row.relative_pct:row.values;
  series.points=result.runs.map((r,i)=>({label:r.label,x:i,value:values[i]??null}));
  if(source==='delta')base.quantity+=' — change from baseline';
  if(source==='relative'){base.quantity+=' — relative change';base.unit='%';}
  if(result.comparison_warning)base.notes.push(result.comparison_warning);
 }else return null;
 const points=series.points.filter(p=>finite(p.value));if(!points.length)return null;
 return {...base,valid_cells:points.length,population:'experiment_observations',experiment_series:series};
}

/** Compare compatible continuous products, preserving each exact population. */
export function researchDistributionData(result:ResearchResult):PlotData|null{
 const products=result.products.filter(p=>['baseline','scenario'].includes(p.role??'')&&p.plot_data?.box&&p.plot_data.cdf?.length);
 if(products.length<2)return null;
 const unit=products[0].plot_data!.unit;if(products.some(p=>p.plot_data!.unit!==unit))return null;
 const series=products.map(p=>({label:p.name,valid_cells:p.plot_data!.valid_cells,box:p.plot_data!.box!,cdf:p.plot_data!.cdf!}));
 return {schema:'geofathom-plot-data-1',kind:'summary',quantity:products[0].plot_data!.quantity,unit,valid_cells:series.reduce((n,p)=>n+p.valid_cells,0),cell_area_m2:products[0].plot_data!.cell_area_m2,classes:[],population:'separate_scenario_populations',distribution_comparison:{series},notes:['Each distribution uses all finite values in its own exported raster; separate populations are not matched-pair effects.',result.comparison_warning??'']};
}
