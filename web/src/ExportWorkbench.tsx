import {useState} from 'react';
import {downloadMapPDF,exportProject,exportVectorFile,
 type GeoWorkspace,type Measurement,type NetworkFace,type TerrainRasterLayer} from './api';
import type {ScratchFeature} from './scratch';
import {areaText,distanceText} from './displaySettings';

type ExportScope='selection'|'local'|'areas'|'project';
type ExportFormat='geojson'|'gpkg'|'kml'|'gpx'|'shapefile'|'csv'|'report'|'pdf'|'geotiff';
interface Props{
 projectId:string|null;workspace:GeoWorkspace|null;selected:GeoJSON.Geometry|null;
 measurement:Measurement|null;scratch:ScratchFeature[];faces:NetworkFace[];
 terrainRasters:TerrainRasterLayer[];viewport:[number,number,number,number]|null;
}
const fileSave=(filename:string,blob:Blob)=>{
 const url=URL.createObjectURL(blob);
 const link=document.createElement('a');link.href=url;link.download=filename;
 document.body.appendChild(link);link.click();link.remove();
 window.setTimeout(()=>URL.revokeObjectURL(url),1500);
};
const jsonSave=(name:string,value:unknown)=>
 fileSave(name,new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
const csvCell=(value:unknown)=>'"'+String(value??'').replace(/"/g,'""')+'"';
function collectionFromScope(scope:ExportScope,p:Props):GeoJSON.FeatureCollection{
 const items:GeoJSON.Feature[]=
  scope==='selection'?(p.selected?[{type:'Feature',geometry:p.selected,
   properties:{name:'Selected geometry',
    area_m2:p.measurement?.area_m2,perimeter_m:p.measurement?.perimeter_m,
    length_m:p.measurement?.length_m,method:p.measurement?.method}}]:[]):
  scope==='areas'?p.faces.map(f=>({type:'Feature',geometry:f.geometry,
   properties:{name:f.name,...f.properties}})):
  p.scratch.map(f=>({type:'Feature',geometry:f.geometry,properties:{
   name:f.name,source:f.source,area_m2:f.measurement.area_m2,
   perimeter_m:f.measurement.perimeter_m,length_m:f.measurement.length_m,
   measurement_method:f.measurement.method,...f.properties}}));
 return {type:'FeatureCollection',features:items};
}
export default function ExportWorkbench(p:Props){
 const [scope,setScope]=useState<ExportScope>('selection');
 const [format,setFormat]=useState<ExportFormat>('geojson');
 const [title,setTitle]=useState('GeoFathom survey');
 const [paper,setPaper]=useState<'a4'|'a3'|'letter'>('a4');
 const [orientation,setOrientation]=useState<'landscape'|'portrait'>('landscape');
 const [extent,setExtent]=useState<'all'|'viewport'>('all');
 const [grid,setGrid]=useState(true);
 const [legend,setLegend]=useState(true);
 const [rasterIndex,setRasterIndex]=useState(0);
 const [busy,setBusy]=useState(false);
 const [message,setMessage]=useState('');
 const [error,setError]=useState('');
 const count=scope==='selection'?Number(Boolean(p.selected)):
  scope==='local'?p.scratch.length:scope==='areas'?p.faces.length:
  (p.workspace?.features.length??0);
 const projectFormat=['geojson','gpkg','kml','gpx','shapefile'].includes(format);
 const canExport=format==='geotiff'?p.terrainRasters.length>0:
  format==='pdf'?Boolean(p.projectId&&title.trim()&&(extent!=='viewport'||p.viewport)):
  scope==='project'?Boolean(p.projectId&&count):
  Boolean(count&&(format==='geojson'||format==='csv'||format==='report'));
 async function run(){
  if(!canExport||busy)return;setBusy(true);setError('');setMessage('');
  try{
   if(format==='geotiff'){
    const raster=p.terrainRasters[rasterIndex];
    if(!raster?.raster.geotiff)throw Error('No georeferenced raster result selected.');
    const bytes=Uint8Array.from(atob(raster.raster.geotiff),c=>c.charCodeAt(0));
    fileSave('geofathom-'+raster.title.replace(/[^a-z0-9_-]/gi,'-')+'.tif',
      new Blob([Uint8Array.from(bytes)],{type:'image/tiff'}));
   }else if(format==='pdf'){
    if(!p.projectId)throw Error('Open a project for a printable map.');
    await downloadMapPDF(p.projectId,{
      title,paper,orientation,extent:extent==='viewport'?p.viewport:null,
      show_grid:grid,show_legend:legend,layer_ids:null,
    });
   }else if(scope==='project'&&projectFormat){
    await exportVectorFile(p.projectId!,format as 'geojson'|'gpkg'|'kml'|'gpx'|'shapefile');
   }else{
    const featureCollection=scope==='project'?await exportProject(p.projectId!):
      collectionFromScope(scope,p);
    if(!featureCollection.features.length)throw Error('No features in the selected export scope.');
    if(format==='geojson'){
     fileSave('geofathom-'+scope+'.geojson',new Blob([
      JSON.stringify(featureCollection,null,2)],{type:'application/geo+json'}));
    }else if(format==='csv'){
     const headers=['name','geometry_type','area_m2','perimeter_m','length_m',
       'source','measurement_method'];
     const lines=[headers.map(csvCell).join(',')];
     for(const f of featureCollection.features){
      const props=f.properties??{};
      const values=[props.name,f.geometry.type,props.area_m2,
        props.perimeter_m,props.length_m,props.source,
        props.measurement_method??props.method];
      lines.push(values.map(csvCell).join(','));
     }
     fileSave('geofathom-'+scope+'-measurements.csv',
       new Blob(['\ufeff'+lines.join('\r\n')+'\r\n'],{type:'text/csv;charset=utf-8'}));
    }else if(format==='report'){
     const measurements=featureCollection.features.map(f=>({
       name:f.properties?.name??'Unnamed',type:f.geometry.type,
       area_m2:f.properties?.area_m2??null,
       perimeter_m:f.properties?.perimeter_m??null,
       length_m:f.properties?.length_m??null,
       method:f.properties?.measurement_method??f.properties?.method??null,
     }));
     jsonSave('geofathom-'+scope+'-report.json',{
      schema:'geofathom.export-report.v1',created_utc:new Date().toISOString(),
      scope,project_id:p.projectId,feature_count:featureCollection.features.length,
      measurements,coordinate_system:'EPSG:4326',
      limitations:'Results retain original source accuracy. CSV/report are not independent survey certifications.',
     });
    }else throw Error('This format requires a saved project.');
   }
   setMessage('Export generated: '+format.toUpperCase()+'.');
  }catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 return <div className="export-workbench">
  <div className="data-metric-band">
   <div><small>Source</small><strong>{scope==='selection'?'Selection':
     scope==='local'?'Local drawings':scope==='areas'?'Enclosed areas':'Project'}</strong></div>
   <div><small>Features</small><strong>{count}</strong></div>
  </div>
  <label>Export scope
   <select aria-label="Export scope" value={scope} onChange={e=>setScope(e.target.value as ExportScope)}>
    <option value="selection">Current selection</option>
    <option value="areas">Detected closed areas</option>
    <option value="local">All local drawings</option>
    <option value="project" disabled={!p.projectId}>Active project</option>
   </select>
  </label>
  <label>Output
   <select aria-label="Export format" value={format} onChange={e=>setFormat(e.target.value as ExportFormat)}>
    <optgroup label="Vector datasets">
     <option value="geojson">GeoJSON · WGS84</option>
     <option value="gpkg">GeoPackage · project</option>
     <option value="shapefile">Shapefile ZIP · project</option>
     <option value="kml">KML · project</option>
     <option value="gpx">GPX · points & lines, project</option>
    </optgroup>
    <optgroup label="Research outputs">
     <option value="csv">Measurements CSV</option>
     <option value="report">Measurements report JSON</option>
     <option value="pdf">Printable map PDF · project</option>
     <option value="geotiff">Analysis GeoTIFF</option>
    </optgroup>
   </select>
  </label>
  {format==='geotiff'&&<label>Raster result
   <select aria-label="GeoTIFF result" value={rasterIndex}
    onChange={e=>setRasterIndex(Number(e.target.value))}>
    {p.terrainRasters.map((r,i)=><option value={i} key={r.id}>{r.title}</option>)}
   </select>
  </label>}
  {format==='pdf'&&<div className="export-layout-options">
   <label>Title<input aria-label="Export map title" value={title} maxLength={120} onChange={e=>setTitle(e.target.value)}/></label>
   <div className="data-input-pair">
    <label>Paper<select aria-label="Export paper" value={paper} onChange={e=>setPaper(e.target.value as typeof paper)}>
     <option value="a4">A4</option><option value="a3">A3</option><option value="letter">Letter</option>
    </select></label>
    <label>Orientation<select aria-label="Export orientation" value={orientation} onChange={e=>setOrientation(e.target.value as typeof orientation)}>
     <option value="landscape">Landscape</option><option value="portrait">Portrait</option>
    </select></label>
   </div>
   <label>Extent<select aria-label="Export extent" value={extent} onChange={e=>setExtent(e.target.value as typeof extent)}>
    <option value="all">All visible features</option><option value="viewport">Current map view</option>
   </select></label>
   <div className="data-choice-buttons">
    <label><input type="checkbox" checked={grid} onChange={e=>setGrid(e.target.checked)}/> Grid</label>
    <label><input type="checkbox" checked={legend} onChange={e=>setLegend(e.target.checked)}/> Legend</label>
   </div>
  </div>}
  <button type="button" className="data-primary" onClick={()=>void run()}
   disabled={!canExport||busy}>{busy?'Preparing…':'Export '+format.toUpperCase()}</button>
  {format!=='geotiff'&&count===0&&<small>No features in the current scope.</small>}
  {scope!=='project'&&['gpkg','kml','gpx','shapefile'].includes(format)&&
    <small>Save features to a project to use this vector format.</small>}
  {message&&<small className="project-info" role="status">{message}</small>}
  {error&&<small className="discovery-error" role="alert">{error}</small>}
 </div>;
}
