import {useState} from 'react';
import {createPortal} from 'react-dom';
import {AlertTriangle,Download,MousePointer2,Square} from 'lucide-react';
import {downloadMapPDF,reviewTopology,selectSpatialFeatures,
  type QualityIssue,type SpatialRelation} from './api';

type BBox=[number,number,number,number];
interface Props{
  resultsTarget?:HTMLElement|null;active?:boolean;
  projectId:string|null;
  geometry:GeoJSON.Geometry|null;
  viewport:BBox|null;
  selectedIds:string[];
  onSelected:(ids:string[])=>void;
  boxMode:boolean;
  onBoxMode:(active:boolean)=>void;
  box:BBox|null;
  onBox:(bbox:BBox|null)=>void;
  onIssues:(issues:QualityIssue[])=>void;
  onOpen:(id:string)=>void;
}
function polygon(b:BBox):GeoJSON.Polygon{
  const [w,s,e,n]=b;
  return {type:'Polygon',coordinates:[[[w,s],[e,s],[e,n],[w,n],[w,s]]]};
}
export default function SpatialToolsPanel(p:Props){
  const [relation,setRelation]=useState<SpatialRelation>('intersects');
  const [visible,setVisible]=useState(true);
  const [selectionSource,setSelectionSource]=useState<'box'|'geometry'>('box');
  const [result,setResult]=useState<{results:Array<{id:string;name:string}>;total:number}|null>(null);
  const [issues,setIssues]=useState<QualityIssue[]>([]);
  const [issueCount,setIssueCount]=useState<number|null>(null);
  const [threshold,setThreshold]=useState(.01);
  const [paper,setPaper]=useState<'a4'|'a3'|'letter'>('a4');
  const [orientation,setOrientation]=useState<'portrait'|'landscape'>('landscape');
  const [coverage,setCoverage]=useState<'all'|'viewport'>('all');
  const [title,setTitle]=useState('GeoFathom survey map');
  const [legend,setLegend]=useState(true);
  const [grid,setGrid]=useState(true);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const selectedGeometry=selectionSource==='box'?(p.box?polygon(p.box):null):p.geometry;
  async function execute(task:()=>Promise<void>){
    setBusy(true);setError('');setNotice('');
    try{await task();}
    catch(cause){setError(cause instanceof Error?cause.message:'GIS action failed.');}
    finally{setBusy(false);}
  }
  async function select(){
    if(!p.projectId||!selectedGeometry)return;
    const response=await selectSpatialFeatures(p.projectId,selectedGeometry,relation,null,visible);
    setResult(response);p.onSelected(response.ids);
    setNotice('Selected '+response.ids.length+' of '+response.total+' matching features.');
  }
  async function quality(){
    if(!p.projectId)return;
    const study=p.geometry?.type==='Polygon'||p.geometry?.type==='MultiPolygon'
      ?p.geometry:null;
    const report=await reviewTopology(p.projectId,{
      study_area:study,minimum_area_m2:threshold,check_dangles:true,max_issues:500,
    });
    setIssues(report.issues);setIssueCount(report.issue_count);p.onIssues(report.issues);
    setNotice('Checked '+report.checked_features+' project features.');
  }
  async function print(){
    if(!p.projectId)return;
    if(coverage==='viewport'&&!p.viewport)throw Error('Map viewport is not ready.');
    await downloadMapPDF(p.projectId,{title,paper,orientation,
      extent:coverage==='viewport'?p.viewport:null,
      show_grid:grid,show_legend:legend,layer_ids:null});
    setNotice('Vector PDF map exported.');
  }
  const resultPanel=<div className="gis-spatial-results">
        {result&&<div className="gis-result-list" aria-label="Spatial selection results">
          <strong>{result.total} matches</strong>
          {result.results.slice(0,80).map(row=><button key={row.id} onClick={()=>p.onOpen(row.id)}>
            {row.name}
          </button>)}
        </div>}
        {issueCount!==null&&<div className="gis-result-list" aria-label="Topology QA results">
          <strong>{issueCount} topology issues</strong>
          {issues.map((issue,index)=><button key={index} title={issue.message}
            onClick={()=>issue.feature_ids.length&&p.onOpen(issue.feature_ids[0])}>
            {issue.type}: {issue.message} · {issue.area_m2.toFixed(1)} m²
          </button>)}
        </div>}
  </div>;
  return <div className="professional-panel">
    <details>
      <summary><MousePointer2 size={14}/> Select by location · {p.selectedIds.length} selected</summary>
      <div className="professional-form">
        <div className="area-fields">
          <select aria-label="Selection area mode" value={selectionSource}
            onChange={e=>setSelectionSource(e.target.value as typeof selectionSource)}>
            <option value="box">Rectangle from map drag</option>
            <option value="geometry">Current geometry / polygon lasso</option>
          </select>
          <select aria-label="Spatial relationship" value={relation}
            onChange={e=>setRelation(e.target.value as SpatialRelation)}>
            <option value="intersects">Intersects</option>
            <option value="within">Within</option>
            <option value="contains">Contains</option>
            <option value="touches">Touches</option>
            <option value="crosses">Crosses</option>
          </select>
        </div>
        {selectionSource==='box'?<button aria-label="Draw selection rectangle"
          disabled={busy||!p.projectId} onClick={()=>{
            p.onBoxMode(!p.boxMode);if(!p.boxMode)p.onBox(null);
          }} className={p.boxMode?'active':''}><Square size={14}/>
          {p.boxMode?'Drag on map to select area':'Draw map rectangle'}</button>:
          <p className="project-hint">Draw a polygon with the survey tools and use it as a lasso.</p>}
        <label className="linked-vertex-toggle">
          <input aria-label="Only visible layers" type="checkbox" checked={visible}
            onChange={e=>setVisible(e.target.checked)}/> Visible layers only
        </label>
        <div className="survey-action-bar">
          <button aria-label="Select spatial matches" disabled={!p.projectId||busy||!selectedGeometry}
            onClick={()=>void execute(select)}>Select matches</button>
          <button disabled={busy||!p.selectedIds.length} onClick={()=>{
            p.onSelected([]);setResult(null);setNotice('Selection cleared.');
          }}>Clear selection</button>
        </div>

      </div>
    </details>
    <details>
      <summary><AlertTriangle size={14}/> Topology quality inspection</summary>
      <div className="professional-form">
        <label>Minimum overlap / gap (m²)
          <input aria-label="Topology threshold" type="number" min="0" step=".01"
            value={threshold} onChange={e=>setThreshold(Number(e.target.value))}/>
        </label>
        <p className="project-hint">Check duplicate and overlapping polygons,
          uncovered gaps inside a chosen polygon study area and dangling line endpoints.
          Results are diagnostic and do not modify geometry.</p>
        <button aria-label="Run topology QA" disabled={busy||!p.projectId}
          onClick={()=>void execute(quality)}>Analyze topology</button>

      </div>
    </details>
    <details>
      <summary><Download size={14}/> PDF print layout</summary>
      <form className="professional-form" onSubmit={event=>{
        event.preventDefault();void execute(print);
      }}>
        <label>Map title
          <input aria-label="PDF map title" value={title} maxLength={120}
            onChange={e=>setTitle(e.target.value)}/>
        </label>
        <div className="area-fields">
          <label>Paper
            <select aria-label="PDF paper" value={paper}
              onChange={e=>setPaper(e.target.value as typeof paper)}>
              <option value="a4">A4</option><option value="a3">A3</option>
              <option value="letter">US Letter</option>
            </select>
          </label>
          <label>Orientation
            <select aria-label="PDF orientation" value={orientation}
              onChange={e=>setOrientation(e.target.value as typeof orientation)}>
              <option value="landscape">Landscape</option>
              <option value="portrait">Portrait</option>
            </select>
          </label>
          <label>Extent
            <select aria-label="PDF extent" value={coverage}
              onChange={e=>setCoverage(e.target.value as typeof coverage)}>
              <option value="all">All visible features</option>
              <option value="viewport">Map viewport</option>
            </select>
          </label>
        </div>
        <label className="linked-vertex-toggle">
          <input aria-label="PDF include grid" type="checkbox" checked={grid}
            onChange={e=>setGrid(e.target.checked)}/> Coordinate grid
        </label>
        <label className="linked-vertex-toggle">
          <input aria-label="PDF include legend" type="checkbox" checked={legend}
            onChange={e=>setLegend(e.target.checked)}/> Layer legend
        </label>
        <button aria-label="Export vector PDF" disabled={!p.projectId||busy||!title.trim()}
          type="submit"><Download size={14}/> Export vector PDF</button>
        <p className="project-hint">Vector geometries, geographic grid, north arrow,
          metric scale, timestamp and visible-layer legend; no unlicensed basemap.</p>
      </form>
    </details>
    {notice&&<p className="project-info">{notice}</p>}
    {error&&<p className="discovery-error">{error}</p>}
    {p.resultsTarget?(p.active?createPortal(resultPanel,p.resultsTarget):null):resultPanel}
  </div>;
}
