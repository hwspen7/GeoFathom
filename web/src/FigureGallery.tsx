import {useEffect,useMemo,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {exportFigurePDF,getTerrainPlotData,type PlotData} from './api';
import type {PersistedTerrainResult} from './terrainResultStore';
import {researchBase} from './terrainResearch';
import {availableFigures,defaultFigure,figureTable,localPlotData,makeFigure,metricUnit,tableCSV,type FigureSettings,type Primitive} from './figureLibrary';
import {exportScenePNG,pythonFigure,saveFigureBlob} from './figureExport';

function PrimitiveView({p}:{p:Primitive}){
 const common={stroke:p.stroke??'#000000',fill:p.fill??'none',strokeWidth:p.line_width??1,strokeDasharray:p.dashed?'5 4':undefined};
 if(p.kind==='line')return <line x1={p.x} y1={p.y} x2={p.x2} y2={p.y2} {...common}/>;
 if(p.kind==='rect')return <rect x={p.x} y={p.y} width={p.width} height={p.height} {...common}/>;
 if(p.kind==='circle')return <circle cx={p.x} cy={p.y} r={p.radius} {...common}/>;
 if(p.kind==='polyline'||p.kind==='polygon'){const points=p.points?.map(p=>p.join(',')).join(' ');return p.kind==='polygon'?<polygon points={points} {...common}/>:<polyline points={points} {...common}/>;}
 return <text x={p.x} y={p.y} textAnchor={p.anchor} fontFamily={p.font==='serif'?'Times New Roman, serif':'Arial, sans-serif'} fontSize={p.font_size} fill={p.fill??'#222222'} transform={p.angle?`rotate(${p.angle} ${p.x} ${p.y})`:undefined}>{p.text}</text>;
}
interface StylePreset {name:string;settings:FigureSettings}
function readStyles(project:string):StylePreset[]{try{const raw:unknown=JSON.parse(localStorage.getItem(project)??'[]');return Array.isArray(raw)?raw.filter((s):s is StylePreset=>!!s&&typeof s.name==='string'&&!!s.settings&&typeof s.settings.kind==='string'&&Number.isFinite(s.settings.width_mm)&&Number.isFinite(s.settings.height_mm)).slice(0,12):[];}catch{return [];}}
export default function FigureGallery(p:{record?:PersistedTerrainResult;research?:{id:string;title:string;data:PlotData;manifest:unknown};projectId:string|null;onClose:()=>void}){
 const record=p.record, research=p.research;
 const [data,setData]=useState<PlotData|null>(()=>research?.data??(record?localPlotData(record):null));
 const [loading,setLoading]=useState(!data),[error,setError]=useState(''),[exporting,setExporting]=useState(false);
 const [settings,setSettings]=useState<FigureSettings|null>(()=>data?defaultFigure(data):null);
 const [page,setPage]=useState<'charts'|'appearance'|'axes'|'data'>('charts');
 const [dataPage,setDataPage]=useState(0),[styleName,setStyleName]=useState(''),[threshold,setThreshold]=useState('');
 const styleKey='geofathom-figure-styles:'+(p.projectId??'local');
 const [styles,setStyles]=useState<StylePreset[]>(()=>readStyles(styleKey));
 const [selectedStyle,setSelectedStyle]=useState(''),[chartPage,setChartPage]=useState(0);
 const svg=useRef<SVGSVGElement>(null),dialog=useRef<HTMLDivElement>(null);
 useEffect(()=>{
  const previous=document.activeElement as HTMLElement|null;dialog.current?.focus();
  const existing=research?.data??(record?localPlotData(record):null);if(existing){setData(existing);setSettings(defaultFigure(existing));setLoading(false);return()=>previous?.focus();}
  if(!record){setLoading(false);setError('No recorded figure data.');return()=>previous?.focus();}
  const controller=new AbortController();setLoading(true);
  getTerrainPlotData(researchBase(record),record.source.sha256,controller.signal).then(value=>{if(!controller.signal.aborted){setData(value);setSettings(defaultFigure(value));}})
   .catch(e=>{if(!controller.signal.aborted)setError(e.message??String(e));}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>{controller.abort();previous?.focus();};
 },[record?.id,research?.id]);
 const recipes=data?availableFigures(data):[];
 const thumbnails=useMemo(()=>data&&settings?availableFigures(data).map(recipe=>({id:recipe.id,scene:makeFigure(data,{...settings,kind:recipe.id,x_log:false,y_log:false})})):[],[data,settings]);
 const scene=useMemo(()=>data&&settings?makeFigure(data,settings):null,[data,settings]);
 const table=useMemo(()=>data&&settings?figureTable(data,settings):null,[data,settings]);
 const metadata={schema:'geofathom-figure-1',run_id:record?.id??research?.id,operation:record?.operation??data?.operation,research_manifest:research?.manifest,
  source:record?.source,geometry:record?.geometry,parameters:record?.researchInput??record?.parameters,
  created_at:record?new Date(record.createdAt).toISOString():undefined,settings,actual_histogram_bins:settings&&['histogram','density'].includes(settings.kind)?table?.rows.length:null,plot_population:data?.population,
  valid_cells:data?.valid_cells,cell_area_m2:data?.cell_area_m2,notes:data?.notes,quality:record?.advanced?.quality??data?.quality,joint_population:data?.joint?{cells:data.joint.population_cells,samples:data.joint.sample_cells,sampling:data.joint.sampling,pearson_r:data.joint.pearson_r,notes:data.joint.notes}:null,
  axis_units:table?{x:table.x_label,y:table.y_label}:null};
 function change<K extends keyof FigureSettings>(key:K,value:FigureSettings[K]){setSettings(s=>s?{...s,[key]:value}:s);setDataPage(0);setError('');}
 async function download(format:string){
  if(!scene||!table||!settings||!data)return;setExporting(true);setError('');
  try{
   const stem='terrain-'+(record?.operation??'research')+'-'+settings.kind;
   if(format==='CSV')saveFigureBlob(new Blob([tableCSV(table)],{type:'text/csv;charset=utf-8'}),stem+'.csv');
   if(format==='JSON')saveFigureBlob(new Blob([JSON.stringify({metadata,data,selected_table:table},null,2)],{type:'application/json'}),stem+'.json');
   if(format==='Python')saveFigureBlob(new Blob([pythonFigure(table,settings,data,metadata)],{type:'text/x-python'}),stem+'.py');
   if(format==='SVG'&&svg.current){const copy=svg.current.cloneNode(true) as SVGSVGElement;copy.setAttribute('xmlns','http://www.w3.org/2000/svg');copy.setAttribute('width',scene.width_mm+'mm');copy.setAttribute('height',scene.height_mm+'mm');const info=document.createElementNS('http://www.w3.org/2000/svg','metadata');info.textContent=JSON.stringify(metadata);copy.prepend(info);saveFigureBlob(new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml'}),stem+'.svg');}
   if(format==='PNG'&&svg.current)saveFigureBlob(await exportScenePNG(svg.current,scene,settings.dpi),stem+'.png');
   if(format==='PDF'){const {note:_note,error:_error,...payload}=scene;saveFigureBlob(await exportFigurePDF(payload),stem+'.pdf');}
  }catch(e){setError((e as Error).message);}finally{setExporting(false);}
 }
 function chooseChart(kind:FigureSettings['kind']){
  if(!settings||!data)return;
  setChartPage(Math.floor(Math.max(0,recipes.findIndex(r=>r.id===kind))/4));
  const auto=data.quantity.replaceAll('_',' ')+': '+recipes.find(f=>f.id===settings.kind)?.title;
  setSettings({...settings,kind,x_log:false,y_log:false,x_label:'',y_label:'',title:settings.title===auto?data.quantity.replaceAll('_',' ')+': '+recipes.find(f=>f.id===kind)!.title:settings.title});setDataPage(0);setError('');
 }
 const active=recipes.find(f=>f.id===settings?.kind);
 const plotValues=Object.keys(data?.metrics??{}).filter(k=>Number.isFinite(data!.metrics![k]));
 const pages=Math.max(1,Math.ceil((table?.rows.length??0)/8)),currentPage=Math.min(dataPage,pages-1);
 return createPortal(<div className="figure-gallery-backdrop"><div className="figure-gallery" role="dialog" aria-modal="true" aria-label="Scientific figure library" ref={dialog} tabIndex={-1} onKeyDown={e=>{
  e.stopPropagation();
  if(e.key==='Escape'){e.preventDefault();p.onClose();}
  if(e.key==='Tab'){
   const nodes=Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button:enabled,input:enabled,select:enabled')).filter(n=>n.getClientRects().length>0);
   const first=nodes[0],last=nodes[nodes.length-1];
   if(e.shiftKey&&(document.activeElement===first||document.activeElement===dialog.current)){e.preventDefault();last?.focus();}
   else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
  }
 }}>
  <header><div><strong>Scientific figure library</strong><small>{research?.title??record?.title} {record&&' · '+record.source.name}</small></div><button type="button" onClick={p.onClose}>Close figure library</button></header>
  {loading&&<p role="status">Preparing numerical plot tables from the recorded terrain input…</p>}
  {error&&<p role="alert" className="discovery-error">{error}</p>}
  {scene?.error&&<p role="alert">{scene.error}</p>}
  {data&&settings&&scene&&table&&<div className="figure-gallery-body">
   <aside aria-label="Figure settings"><nav aria-label="Figure settings pages">{(['charts','appearance','axes','data'] as const).map(tab=><button type="button" key={tab} aria-pressed={page===tab} onClick={()=>setPage(tab)}>{{charts:'Charts',appearance:'Style',axes:'Axes',data:'Data'}[tab]}</button>)}</nav>
    {page==='charts'&&<>
     <label>Chart type<select aria-label="Chart type" value={settings.kind} onChange={e=>chooseChart(e.target.value as FigureSettings['kind'])}>{recipes.map(r=><option key={r.id} value={r.id}>{r.title}</option>)}</select></label>
     <div className="figure-recipe-grid">{recipes.slice(chartPage*4,chartPage*4+4).map(r=><button type="button" key={r.id} aria-pressed={settings.kind===r.id} title={r.description} onClick={()=>chooseChart(r.id)}><svg viewBox="80 55 790 455" aria-hidden="true">{thumbnails.find(t=>t.id===r.id)?.scene.primitives.filter(p=>p.kind!=='text').map((p,i)=><PrimitiveView key={i} p={p}/>)}</svg>{r.title}</button>)}</div>
     {recipes.length>4&&<div className="figure-chart-pages"><button type="button" disabled={chartPage===0} onClick={()=>setChartPage(i=>i-1)}>Previous charts</button><span>{chartPage+1} / {Math.ceil(recipes.length/4)}</span><button type="button" disabled={chartPage>=Math.ceil(recipes.length/4)-1} onClick={()=>setChartPage(i=>i+1)}>Next charts</button></div>}
     <small>{active?.description}</small>
     {['histogram','density'].includes(settings.kind)&&<label>Numerical bins<select aria-label="Numerical bins" value={data.histograms?.[String(settings.bins)]?settings.bins:Object.keys(data.histograms??{})[0]} onChange={e=>change('bins',Number(e.target.value))}>{Object.keys(data.histograms??{}).map(n=><option key={n} value={n}>{n} bins</option>)}</select></label>}
     {['histogram','class_bar','class_dot','rose'].includes(settings.kind)&&<label>Vertical quantity<select aria-label="Vertical quantity" value={settings.measure} onChange={e=>change('measure',e.target.value as FigureSettings['measure'])}><option value="percent">{data.population==='monte_carlo_realizations'?'Realizations (%)':'Area share (%)'}</option><option value="cells">{data.population==='monte_carlo_realizations'?'Realization count':'Valid cell count'}</option>{data.population!=='monte_carlo_realizations'&&<option value="area">Projected area (m²)</option>}</select></label>}
     {settings.kind==='rose'&&<label>Direction sectors<select aria-label="Direction sectors" value={settings.sectors} onChange={e=>change('sectors',Number(e.target.value))}>{[8,16,36].map(n=><option key={n}>{n}</option>)}</select></label>}
     {['profile','grade'].includes(settings.kind)&&<label>Profile series<select aria-label="Profile series" value={settings.series} onChange={e=>change('series',Number(e.target.value))}>{data.profiles?.map((r,i)=><option key={i} value={i}>{r.name}</option>)}</select></label>}
     {settings.kind==='metrics'&&<label>Metric unit group<select aria-label="Metric unit group" value={metricUnit(table.rows[0]?.[0] as string??'')} onChange={e=>change('metric_keys',plotValues.filter(k=>metricUnit(k)===e.target.value))}>{Array.from(new Set(plotValues.map(metricUnit))).map(group=><option key={group} value={group}>{group}</option>)}</select></label>}
    </>}
    {page==='axes'&&<>
     <label>X axis label<input aria-label="X axis label" value={settings.x_label} placeholder={table.x_label} maxLength={120} onChange={e=>change('x_label',e.target.value)}/></label>
     <label>Y axis label<input aria-label="Y axis label" value={settings.y_label} placeholder={table.y_label} maxLength={120} onChange={e=>change('y_label',e.target.value)}/></label>
     <div className="figure-control-pair"><label>X scale<select aria-label="X scale" disabled={(['class_bar','class_dot','metrics','box','rose','experiment_bar','experiment_dot','experiment_interval','comparison_boxes','regression','bland_altman'].includes(settings.kind)||(settings.kind==='scatter'&&!!data.joint?.identity_line))} value={settings.x_log?'log':'linear'} onChange={e=>change('x_log',e.target.value==='log')}><option value="linear">Linear</option><option value="log">Logarithmic</option></select></label><label>Y scale<select aria-label="Y scale" disabled={['rose','experiment_interval','comparison_cdf','regression','bland_altman'].includes(settings.kind)||(settings.kind==='scatter'&&!!data.joint?.identity_line)} value={settings.y_log?'log':'linear'} onChange={e=>change('y_log',e.target.value==='log')}><option value="linear">Linear</option><option value="log">Logarithmic</option></select></label></div>
    </>}
    {page==='appearance'&&<>
     <label>Figure title<input aria-label="Figure title" value={settings.title} maxLength={160} onChange={e=>change('title',e.target.value)}/></label>
     <div className="figure-control-pair"><label>Palette<select aria-label="Palette" value={settings.palette} onChange={e=>change('palette',e.target.value as FigureSettings['palette'])}><option value="mono">Black and white</option><option value="blue">Blue</option><option value="earth">Earth</option></select></label><label>Font<select aria-label="Font" value={settings.font} onChange={e=>change('font',e.target.value as FigureSettings['font'])}><option value="sans">Sans serif</option><option value="serif">Serif</option></select></label></div>
     <label>Label size<input aria-label="Label size" type="number" min="12" max="22" value={settings.font_size} onChange={e=>change('font_size',Math.min(22,Math.max(12,Number(e.target.value)||16)))}/></label>
     <label className="figure-toggle"><input type="checkbox" checked={settings.grid} onChange={e=>change('grid',e.target.checked)}/>Grid lines</label>
     <label>Style name<input aria-label="Style name" value={styleName} maxLength={80} onChange={e=>setStyleName(e.target.value)}/></label>
     <button type="button" disabled={!styleName.trim()} onClick={()=>{try{const next=[{name:styleName.trim(),settings},...styles.filter(s=>s.name!==styleName.trim())].slice(0,12);localStorage.setItem(styleKey,JSON.stringify(next));setStyles(next);setSelectedStyle(styleName.trim());}catch{setError('Style could not be saved in this browser.');}}}>Save style</button>
     {styles.length>0&&<label>Saved styles<select aria-label="Saved styles" value={selectedStyle} onChange={e=>{setSelectedStyle(e.target.value);const preset=styles.find(s=>s.name===e.target.value);if(preset){const compatible=recipes.some(r=>r.id===preset.settings.kind);const bins=data.histograms?.[String(preset.settings.bins)]?preset.settings.bins:Number(Object.keys(data.histograms??{})[0]??preset.settings.bins);setSettings({...preset.settings,bins,measure:data.population==='monte_carlo_realizations'&&preset.settings.measure==='area'?'percent':preset.settings.measure,kind:compatible?preset.settings.kind:settings.kind});}}}><option value="">Choose a style</option>{styles.map(s=><option key={s.name}>{s.name}</option>)}</select></label>}
    </>}
    {page==='data'&&<>
     <p><strong>{data.valid_cells.toLocaleString()} {data.experiment_series?'experiment observations':data.population==='monte_carlo_realizations'?'realizations':'valid cells / samples'}</strong></p><p>Units: {data.unit||'See metric names'}</p>
     {data.summary&&<dl className="figure-summary">{Object.entries(data.summary).map(([key,value])=><div key={key}><dt>{key.replaceAll('_',' ')}</dt><dd>{value.toLocaleString('en-US',{maximumSignificantDigits:7})}</dd></div>)}</dl>}
     {data.thresholds&&<label>Slope area threshold<select aria-label="Slope area threshold" value={threshold} onChange={e=>setThreshold(e.target.value)}><option value="">Inspect threshold</option>{data.thresholds.map(t=><option key={t.threshold_deg} value={t.threshold_deg}>{t.threshold_deg}°</option>)}</select></label>}
     {threshold&&data.thresholds&&<p role="status">{threshold}°: {data.thresholds.find(t=>t.threshold_deg===Number(threshold))?.percent_le.toFixed(3)}% of valid area at or below threshold</p>}
     <small>{data.notes.join(' ')}</small>
    </>}
   </aside>
   <section className="figure-gallery-stage" aria-label="Figure preview and data">
    <svg ref={svg} viewBox={`0 0 ${scene.width} ${scene.height}`} role="img" aria-label={'Scientific figure: '+active?.title} className="scientific-figure-svg">{scene.primitives.map((p,i)=><PrimitiveView key={i} p={p}/>)}</svg>
    <details className="figure-data-preview"><summary>Underlying plot table · {table.rows.length} rows</summary><div><table><thead><tr>{table.columns.map(c=><th key={c}>{c}</th>)}</tr></thead><tbody>{table.rows.slice(currentPage*8,currentPage*8+8).map((row,i)=><tr key={i}>{row.map((v,j)=><td key={j}>{typeof v==='number'?v.toPrecision(7):v??'Missing'}</td>)}</tr>)}</tbody></table></div><div className="figure-table-pages"><button type="button" disabled={!currentPage} onClick={()=>setDataPage(currentPage-1)}>Previous rows</button><span>{currentPage+1} / {pages}</span><button type="button" disabled={currentPage>=pages-1} onClick={()=>setDataPage(currentPage+1)}>Next rows</button></div></details>
   </section>
  </div>}
  {settings&&<footer><div className="figure-size-controls"><label>Width (mm)<input aria-label="Width (mm)" type="number" min="60" max="300" value={settings.width_mm} onChange={e=>change('width_mm',Math.max(60,Math.min(300,Number(e.target.value)||160)))}/></label><label>Height (mm)<input aria-label="Height (mm)" type="number" min="40" max="300" value={settings.height_mm} onChange={e=>change('height_mm',Math.max(40,Math.min(300,Number(e.target.value)||110)))}/></label><label>PNG resolution<select aria-label="PNG resolution" value={settings.dpi} onChange={e=>change('dpi',Number(e.target.value))}><option value="300">300 DPI</option><option value="600">600 DPI</option></select></label></div><div className="figure-downloads">{['SVG','PDF','PNG','CSV','JSON','Python'].map(format=><button type="button" key={format} disabled={exporting||(!!scene?.error&&!['CSV','JSON'].includes(format))} onClick={()=>void download(format)}>{format==='Python'?'Python script':format}</button>)}</div></footer>}
 </div></div>,document.body);
}
