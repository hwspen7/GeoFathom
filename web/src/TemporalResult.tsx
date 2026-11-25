import {useEffect,useState} from 'react';
import {renderStudio,type SpatialScienceResult,type SpatialFigureSource,type StudioOutput,type StudioInput,type RasterDisplayScale} from './api';

export const temporalNumber=(v:number)=>v===0?'0':Math.abs(v)>=1e6||Math.abs(v)<.0001?v.toExponential(3):Number(v.toPrecision(5)).toString();
const isTrend=(operation:string)=>operation==='series_slope'||operation==='sen';
export function TemporalScale({scale,unit}:{scale:RasterDisplayScale;unit:string}){
 const midpoint=scale.signed?0:(scale.minimum+scale.maximum)/2;
 return <div className="temporal-scale" aria-label="Raster color scale">
  <div className="temporal-scale-title">{unit}{scale.signed?' · rate of change':''}</div>
  <div className="temporal-gradient" style={{background:'linear-gradient(to right,'+scale.colors.join(',')+')'}}/>
  <div className="temporal-scale-ticks"><span>{temporalNumber(scale.minimum)}</span><span>{temporalNumber(midpoint)}</span><span>{temporalNumber(scale.maximum)}</span></div>
  {scale.signed&&<div className="temporal-scale-ticks"><span>Decrease</span><span>No change</span><span>Increase</span></div>}
 </div>;
}
function figureInput(result:SpatialScienceResult,figure:SpatialFigureSource):StudioInput{
 return {recipe:figure.recipe,csv:figure.csv??'',rasters:figure.raster&&result.raster?[{name:result.raster.name,data:result.raster.data,unit:result.raster.unit,band:1}]:[],x:'',y:'',z:'',group:'',low:'',high:'',columns:[],title:figure.title,x_label:'',y_label:'',parameter:null,maximize_x:false,maximize_y:false,palette:'color',font:'sans',font_size:10,grid:true,width_mm:175,height_mm:100,dpi:120,format:'png',...figure.bindings,...(figure.raster&&isTrend(result.operation)?{map_style:'diverging' as const}:{})};
}
const completedFigures=new WeakMap<SpatialScienceResult,Map<SpatialFigureSource,StudioOutput>>();
function TemporalFigure({result,figure}:{result:SpatialScienceResult;figure:SpatialFigureSource}){
 const [output,setOutput]=useState<StudioOutput|null>(null),[error,setError]=useState('');
 useEffect(()=>{
  const ac=new AbortController();setError('');
  // Reuse completed figures when moving between the full workbench and the dock.
  const cache=completedFigures.get(result)??new Map<SpatialFigureSource,StudioOutput>();
  completedFigures.set(result,cache);
  const previous=cache.get(figure);setOutput(previous??null);
  if(previous)return ()=>ac.abort();
  renderStudio(figureInput(result,figure),ac.signal).then(v=>{if(!ac.signal.aborted){cache.set(figure,v);setOutput(v);}}).catch(e=>{if(!ac.signal.aborted)setError(String(e.message??e));});
  return ()=>ac.abort();
 },[result,figure]);
 return <section className="temporal-figure" aria-label="Inline scientific figure">
  {error?<p role="alert">{error}</p>:output?<img alt={figure.title} src={'data:'+output.media_type+';base64,'+output.figure}/>:<p role="status">Rendering scientific figure…</p>}
  {figure.recipe==='errorbar'&&figure.title.includes('interquartile')&&<small>Observed spatial spread, not a confidence interval.</small>}
 </section>;
}
export default function TemporalResult({result,title,onMap,onStudio,onExport}:{result:SpatialScienceResult;title:string;onMap:()=>void;onStudio:(f:SpatialFigureSource|null)=>void;onExport:(kind:'raster'|'csv'|'receipt')=>void}){
 const [tab,setTab]=useState<'overview'|'figures'|'data'>('overview'),[selected,setSelected]=useState(0);
 const p=result.preview,r=result.raster,summary=r?.summary,figures=result.figures??[];
 const trend=isTrend(result.operation),unit=r?.unit??String(result.receipt.unit??'');
 const minimum=summary?.minimum??p?.minimum,maximum=summary?.maximum??p?.maximum;
 const median=summary?.quantiles.find(q=>q[0]===.5)?.[1];
 const defaultFigure=figures.find(f=>f.title==='Observed spatial median and interquartile range')??figures.find(f=>!f.raster);
 const selectedFigure=figures[selected]??defaultFigure;
 const displayScale=p?.scale??(p?{minimum:p.minimum,maximum:p.maximum,colors:['#440154','#21918c','#fde725'],signed:false}:undefined);
 const metrics=Object.entries(result.receipt.metrics).filter(([,v])=>typeof v==='number'||typeof v==='boolean');
 const times=Array.isArray(result.receipt.times)?result.receipt.times:[];
 const date=(v:unknown)=>typeof v==='number'&&result.receipt.time_origin==='1970-01-01 UTC'?new Date(v*86400000).toISOString().slice(0,10):String(v);
 return <div className="temporal-result">
  <header className="temporal-result-header"><div><h2>{trend?'Change rate':title}</h2><small>{title} · {unit||'unitless'}</small></div><span className="temporal-complete">Complete</span></header>
  <div className="temporal-result-actions">{r&&<button onClick={()=>onExport('raster')}>GeoTIFF</button>}{p&&r&&<button onClick={onMap}>Show space-time raster on map</button>}<button onClick={()=>onExport('csv')}>CSV</button><button onClick={()=>onExport('receipt')}>Research receipt</button><button onClick={()=>onStudio(null)}>Scientific Figure Studio</button></div>
  <nav className="temporal-tabs" aria-label="Temporal result views">{(['overview','figures','data'] as const).map(t=><button key={t} aria-pressed={tab===t} onClick={()=>setTab(t)}>{t[0].toUpperCase()+t.slice(1)}</button>)}</nav>
  {tab==='overview'&&<>
   <div className="temporal-metrics">
    <div><small>Acquisitions</small><strong>{times.length}</strong>{times.length>0&&<small>{date(times[0])} – {date(times[times.length-1])}</small>}</div>
    {minimum!==undefined&&<div><small>Minimum</small><strong>{temporalNumber(minimum)}</strong><small>{unit}</small></div>}
    {median!==undefined&&<div><small>Median</small><strong>{temporalNumber(median)}</strong><small>{unit}</small></div>}
    {maximum!==undefined&&<div><small>Maximum</small><strong>{temporalNumber(maximum)}</strong><small>{unit}</small></div>}
   </div>
   {p&&<section className="temporal-raster"><h3>Spatial distribution</h3><div className="temporal-raster-body"><img alt="Computed spatiotemporal raster" src={p.png.startsWith('data:')?p.png:'data:image/png;base64,'+p.png}/>{displayScale&&<TemporalScale scale={displayScale} unit={unit}/>}</div><small>{trend?'Negative = decreasing values; positive = increasing values. Fitted change rate, not statistical significance. ':''}{summary?.valid_cells??p.valid_cells} valid {summary?'native':'display'} cells · {result.receipt.crs}</small></section>}
   {defaultFigure&&<section><h3>Observed time series</h3><TemporalFigure result={result} figure={defaultFigure}/></section>}
   {!p&&!defaultFigure&&<p>Results available in Figures and Data.</p>}
  </>}
  {tab==='figures'&&<section><label>Scientific figure<select aria-label="Scientific figure" value={selected} onChange={e=>setSelected(Number(e.target.value))}>{figures.map((f,i)=><option value={i} key={i}>{f.title}</option>)}</select></label>{selectedFigure&&<><TemporalFigure result={result} figure={selectedFigure}/><button onClick={()=>onStudio(selectedFigure)}>Edit / export figure</button></>}</section>}
  {tab==='data'&&<><h3>Model diagnostics</h3><table><tbody>{metrics.map(([k,v])=><tr key={k}><th>{k.replaceAll('_',' ')}</th><td>{typeof v==='number'?temporalNumber(v):String(v)}</td></tr>)}</tbody></table><h3>Result table</h3><div className="temporal-data-table"><table><thead><tr>{result.columns.map(c=><th key={c}>{c}</th>)}</tr></thead><tbody>{result.rows.slice(0,200).map((row,i)=><tr key={i}>{row.map((v,j)=><td key={j}>{v===null?'NoData':typeof v==='number'?temporalNumber(v):v}</td>)}</tr>)}</tbody></table></div><small>{Math.min(200,result.rows.length)} / {result.rows.length} records · complete CSV available</small></>}
 </div>;
}

function timeLabel(result:SpatialScienceResult,value:unknown){
 return typeof value==='number'&&result.receipt.time_origin==='1970-01-01 UTC'?new Date(value*86400000).toISOString().slice(0,10):String(value);
}
/** Fixed-height monitor: spatial result plus an interchangeable scientific chart.
 * All figure recipes remain reachable without opening the modal or scrolling. */
export function TemporalMonitor({result,title,onDetails,onMap,onExport}:{result:SpatialScienceResult;title:string;onDetails:()=>void;onMap:()=>void;onExport:(kind:'raster'|'csv')=>void}){
 const p=result.preview,summary=result.raster?.summary,figures=result.figures??[];
 const charts=figures.filter(f=>!f.raster||!p);
 const preferred=charts.findIndex(f=>f.title==='Observed spatial median and interquartile range');
 const [index,setIndex]=useState(preferred>=0?preferred:0);
 const selected=charts[index]??charts[0];
 const unit=result.raster?.unit??String(result.receipt.unit??'');
 const scale=p?.scale??(p?{minimum:p.minimum,maximum:p.maximum,colors:['#440154','#21918c','#fde725'],signed:false}:undefined);
 const times=Array.isArray(result.receipt.times)?result.receipt.times:[];
 const forecastTime=result.receipt.metrics.forecast_time;
 const values=[['Min',summary?.minimum??p?.minimum],['Median',summary?.quantiles.find(q=>q[0]===.5)?.[1]],['Max',summary?.maximum??p?.maximum]] as const;
 return <section className="temporal-monitor" aria-label="Temporal results">
  <div className="temporal-monitor-head"><h3 title={title}>{title}</h3><small>{times.length} acquisitions{times.length?' · '+timeLabel(result,times[0])+' – '+timeLabel(result,times[times.length-1]):''}</small>
  {typeof forecastTime==='number'&&result.operation.startsWith('forecast_')&&<strong className="temporal-target">Forecast: {timeLabel(result,forecastTime)}</strong>}</div>
  {values.some(([,v])=>v!==undefined)&&<div className="temporal-monitor-metrics">{values.map(([name,v])=><div key={name}><small>{name}</small><strong>{v===undefined?'—':temporalNumber(v)}</strong></div>)}</div>}
  <div className="temporal-monitor-plots">
   {p&&<section className="temporal-monitor-map"><h4>Spatial distribution</h4><div className="temporal-monitor-image"><img alt="Temporal result overview" src={p.png.startsWith('data:')?p.png:'data:image/png;base64,'+p.png}/></div>{scale&&<TemporalScale scale={scale} unit={unit}/>}</section>}
   {selected&&<section className="temporal-monitor-chart"><label><span>Scientific figure</span><select aria-label="Result scientific figure" value={charts.indexOf(selected)} onChange={e=>setIndex(Number(e.target.value))}>{charts.map((f,i)=><option key={i} value={i}>{f.title}</option>)}</select></label><TemporalFigure result={result} figure={selected}/></section>}
   {!p&&!selected&&<p>{result.rows.length} result records available in Details.</p>}
  </div>
  <footer className="temporal-monitor-footer"><button onClick={onDetails} title="Review time-series results">Details</button>{p&&result.raster&&<button onClick={onMap}>Map</button>}{result.raster&&<button onClick={()=>onExport('raster')}>GeoTIFF</button>}<button onClick={()=>onExport('csv')}>CSV</button></footer>
 </section>;
}
