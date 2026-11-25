import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react';
import {createPortal} from 'react-dom';
import { Database, FileDown, FileUp, Mountain, Search, TableProperties } from 'lucide-react';
import {
  analyzeTerrain, exportVectorFile, importVectorFile, queryAttributes,
  saveAttributes, terrainProfile, type AttributeResult,
  type GeoWorkspace, type RasterAsset, type TerrainResult,
} from './api';

interface Props {
  resultsTarget?:HTMLElement|null;active?:boolean;
  projectId:string|null;
  workspace:GeoWorkspace|null;
  geometry:GeoJSON.Geometry|null;
  raster:RasterAsset|null;
  refreshToken:number;
  onRefresh:()=>void;
  onOpen:(id:string)=>void;
}

function formatValue(value:unknown):string {
  return value===null || value===undefined?'—':String(value);
}
function numericText(value:string,kind:'text'|'number'|'boolean') {
  if(kind==='number') {
    const n=Number(value);
    if(!value.trim() || !Number.isFinite(n))throw new Error('Provide a finite number.');
    return n;
  }
  if(kind==='boolean')return value.trim().toLowerCase()==='true';
  return value;
}

export default function ProfessionalPanel({
  projectId,workspace,geometry,raster,refreshToken,onRefresh,onOpen,resultsTarget,active,
}:Props) {
  const [query,setQuery]=useState('');
  const [field,setField]=useState('name');
  const [operator,setOperator]=useState<'contains'|'equals'|'gte'|'lte'|'exists'>('contains');
  const [result,setResult]=useState<AttributeResult|null>(null);
  const [selection,setSelection]=useState<string[]>([]);
  const [editField,setEditField]=useState('category');
  const [editValue,setEditValue]=useState('');
  const [editType,setEditType]=useState<'text'|'number'|'boolean'>('text');
  const [exportFormat,setExportFormat]=useState<'geojson'|'gpkg'|'kml'|'gpx'|'shapefile'>('gpkg');
  const [terrain,setTerrain]=useState<TerrainResult|null>(null);
  const [profile,setProfile]=useState<Array<{distance_m:number;elevation_m:number|null}>|null>(null);
  const [busy,setBusy]=useState(false);
  const [notice,setNotice]=useState('');
  const [error,setError]=useState('');

  useEffect(()=>{
    if(!projectId){setResult(null);setSelection([]);return;}
    queryAttributes(projectId,{limit:100}).then(setResult).catch(()=>setResult(null));
  },[projectId,refreshToken]);

  async function submitQuery(event?:FormEvent) {
    event?.preventDefault();
    if(!projectId)return;
    setBusy(true);setError('');
    try {
      setResult(await queryAttributes(projectId,{
        field:field||undefined,operator,value:query,limit:100,
      }));
      setSelection([]);
    } catch(e){setError(e instanceof Error?e.message:'Attribute search failed.');}
    finally{setBusy(false);}
  }
  async function bulkEdit(event:FormEvent) {
    event.preventDefault();
    if(!projectId || !workspace || !selection.length || !editField.trim())return;
    setBusy(true);setError('');
    try{
      const value=numericText(editValue,editType);
      const updates=selection.map(id=>{
        const feature=workspace.features.find(f=>f.id===id);
        if(!feature)throw new Error('Selected feature is not loaded. Reload the project.');
        const layer=workspace.layers.find(l=>l.id===feature.layer_id);
        if(layer?.locked)throw new Error('Unlock all selected feature layers before editing.');
        return {id,expected_revision:feature.revision,properties:{[editField]:value}};
      });
      const outcome=await saveAttributes(projectId,updates);
      setNotice('Updated '+outcome.count+' feature attributes atomically.');
      setSelection([]);onRefresh();
    } catch(e){setError(e instanceof Error?e.message:'Attribute update failed.');}
    finally{setBusy(false);}
  }
  async function upload(event:ChangeEvent<HTMLInputElement>){
    if(!projectId)return;
    const file=event.target.files?.[0];
    event.target.value='';
    if(!file)return;
    setBusy(true);setError('');
    try{
      const result=await importVectorFile(projectId,file);
      setNotice('Imported '+result.created+' georeferenced GIS features.');
      onRefresh();
    }catch(e){setError(e instanceof Error?e.message:'GIS import failed.');}
    finally{setBusy(false);}
  }
  async function exportFile(){
    if(!projectId)return;
    setBusy(true);setError('');
    try{
      await exportVectorFile(projectId,exportFormat);
      setNotice('GIS export prepared.');
    }catch(e){setError(e instanceof Error?e.message:'GIS export failed.');}
    finally{setBusy(false);}
  }
  async function analyze(){
    if(!raster || !geometry)return;
    setBusy(true);setError('');
    try{
      if(geometry.type==='LineString'){
        setTerrain(null);
        setProfile((await terrainProfile(raster.id,geometry)).samples);
      } else {
        setProfile(null);
        setTerrain(await analyzeTerrain(raster.id,geometry));
      }
    }catch(e){setError(e instanceof Error?e.message:'Terrain analysis failed.');}
    finally{setBusy(false);}
  }

  const profiles=profile?.filter(item=>item.elevation_m!==null)??[];
  const minimum=Math.min(...profiles.map(item=>item.elevation_m!));
  const maximum=Math.max(...profiles.map(item=>item.elevation_m!));
  const profileWidth=340,profileHeight=110;
  const plot=profiles.length>1?profiles.map((item,index)=>{
    const xx=profiles.length===1?0:index/(profiles.length-1)*profileWidth;
    const yy=profileHeight-(item.elevation_m!-minimum)/(maximum-minimum || 1)*profileHeight;
    return xx.toFixed(2)+','+yy.toFixed(2);
  }).join(' '):'';

  const resultPanel=<div className="gis-professional-results">
    <section className="gis-attribute-results" aria-label="Attribute results">
      <strong>Attributes · {result?.total??0}</strong>
        <div className="attribute-table-scroll">
          <table className="attribute-table">
            <thead><tr><th>Select</th><th>Name</th><th>Value</th><th>Source</th></tr></thead>
            <tbody>{(result?.results??[]).map(row=><tr key={row.id}>
              <td><input aria-label={'Select '+row.name} type="checkbox" checked={selection.includes(row.id)}
                onChange={e=>setSelection(old=>e.target.checked?[...old,row.id]:old.filter(x=>x!==row.id))}/></td>
              <td><button className="attribute-open" onClick={()=>onOpen(row.id)}>{row.name}</button></td>
              <td>{formatValue(field==='name'?row.name:field==='source'?row.source:row.properties[field])}</td>
              <td>{row.source}</td>
            </tr>)}</tbody>
          </table>
        </div>

    </section>
          {terrain&&<div className="terrain-metrics">
            <div><span>Elevation</span><strong>{terrain.elevation_min_m.toFixed(1)}–{terrain.elevation_max_m.toFixed(1)} m</strong></div>
            <div><span>Relief</span><strong>{terrain.elevation_relief_m.toFixed(1)} m</strong></div>
            <div><span>Mean slope</span><strong>{terrain.mean_slope_deg.toFixed(2)}°</strong></div>
            <div><span>Mean aspect</span><strong>{terrain.mean_aspect_deg===null?'Flat':terrain.mean_aspect_deg.toFixed(1)+'°'}</strong></div>
            <small>{terrain.engine} · {terrain.valid_pixels} pixels</small>
          </div>}
          {profile&&<div className="terrain-profile">
            {plot&&<svg viewBox="0 0 340 110" role="img" aria-label="Elevation profile">
              <polyline points={plot} fill="none" stroke="#2967b3" strokeWidth="2" />
            </svg>}
            <span>{profiles.length} valid samples · {Number.isFinite(minimum)?minimum.toFixed(1):'—'}–{Number.isFinite(maximum)?maximum.toFixed(1):'—'} m</span>
          </div>}
  </div>;
  return (
    <div className="professional-panel">
      <section className="gis-tool-group" aria-label="Attribute table">
        <h3 className="gis-tool-heading"><TableProperties size={14}/> Attribute table · {result?.total ?? 0} features</h3>
        <form onSubmit={event=>void submitQuery(event)} className="professional-form">
          <div className="area-fields">
            <select aria-label="Attribute search field" value={field} onChange={e=>setField(e.target.value)}>
              <option value="name">Name</option><option value="source">Source</option>
              {(result?.fields??[]).filter(v=>v!=='name'&&v!=='source').map(item=>
                <option key={item} value={item}>{item}</option>)}
            </select>
            <select aria-label="Attribute search operator" value={operator}
              onChange={e=>setOperator(e.target.value as typeof operator)}>
              <option value="contains">Contains</option><option value="equals">Equals</option>
              <option value="gte">≥</option><option value="lte">≤</option>
              <option value="exists">Exists</option>
            </select>
          </div>
          <div className="gis-filter-row">{operator!=='exists'&&<input aria-label="Attribute search value" placeholder="Search attributes"
            value={query} onChange={e=>setQuery(e.target.value)}/>}
          <button disabled={busy||!projectId} type="submit" aria-label="Filter rows" title="Filter attribute rows"><Search size={12}/> Filter</button></div>
        </form>
        <form className="professional-form" onSubmit={e=>void bulkEdit(e)}>
          <div className="gis-edit-header"><strong>Edit · {selection.length} selected</strong><button type="submit" disabled={busy||!selection.length} aria-label="Save properties & revisions" title="Save properties and revisions">Save</button></div>
          <div className="area-fields">
            <input aria-label="Attribute property name" placeholder="Property name" maxLength={64}
            value={editField} onChange={e=>setEditField(e.target.value)}/>
            <select aria-label="Attribute value type" value={editType}
              onChange={e=>setEditType(e.target.value as typeof editType)}>
              <option value="text">Text</option><option value="number">Number</option><option value="boolean">Boolean</option>
            </select>
          </div>
          <input aria-label="New attribute value" placeholder="New value" value={editValue}
              onChange={e=>setEditValue(e.target.value)}/>
          <p className="project-hint">Changes are atomic, versioned, and rejected on locked layers.</p>
        </form>
      </section>
      <section className="gis-tool-group" aria-label="GIS file import / export">
        <h3 className="gis-tool-heading"><Database size={14}/> GIS file import / export</h3>
        <div className="professional-form gis-file-row">
          <label className="raster-upload" title="Import GIS file"><FileUp size={12}/> Import
            <input aria-label="Import GIS vector file" disabled={busy||!projectId}
              type="file" accept=".geojson,.gpkg,.kml,.gpx,.zip"
              onChange={e=>void upload(e)}/>
          </label>
          <div className="area-fields">
            <select aria-label="GIS export format" value={exportFormat}
              onChange={e=>setExportFormat(e.target.value as typeof exportFormat)}>
              <option value="gpkg">GeoPackage</option><option value="geojson">GeoJSON</option>
              <option value="kml">KML</option><option value="gpx">GPX</option>
              <option value="shapefile">Shapefile ZIP</option>
            </select>
            <button disabled={!projectId||busy} onClick={()=>void exportFile()}>
              <FileDown size={12}/> Export
            </button>
          </div>
          <p className="project-hint">Import up to 100 features per file. Source coordinate systems are transformed to WGS84. GPX export is limited to points and lines.</p>
        </div>
      </section>
      <section className="gis-tool-group" aria-label="Terrain slope and elevation profile">
        <div className="gis-terrain-row"><h3 className="gis-tool-heading"><Mountain size={14}/> Terrain</h3>
        <div className="professional-form">
          <button disabled={!raster||!geometry||busy} aria-label={'Analyze selected '+(geometry?.type==='LineString'?'elevation profile':'terrain area')} onClick={()=>void analyze()}>
            Analyze selected {geometry?.type==='LineString'?'profile':'area'}
          </button>
          <p className="project-hint">Requires a meter-based projected DEM GeoTIFF, with meter elevations in its first band. Satellite RGB imagery is not a DEM.</p>

        </div></div>
      </section>
      {notice&&<p className="project-info">{notice}</p>}
      {error&&<p className="discovery-error">{error}</p>}
      {resultsTarget?(active?createPortal(resultPanel,resultsTarget):null):resultPanel}
    </div>
  );
}
