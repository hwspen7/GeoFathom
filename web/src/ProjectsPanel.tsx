import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import {
  Copy, Download, Eye, EyeOff, FolderOpen, History, Layers3, Lock,
  LockOpen, MapPin, Plus, RotateCcw, Save,
} from 'lucide-react';

import {
  copyProjectFeature, createLayer, deleteProjectFeature, exportProject, getFeatureHistory, getProjects,
  getWorkspace, newProject, patchLayer, restoreFeature, saveProjectFeature,
  saveFeatureBatch, patchLayerStyle, updateProjectFeature, type GeoLayer, type GeoWorkspace, type Project,
  type WorkspaceFeature, type FeatureHistory,
} from './api';

interface Props {
  geometry: GeoJSON.Geometry | null;
  featureName: string;
  featureSource: string;
  featureProperties: Record<string, unknown>;
  selectedFeatureId: string | null;
  splitParts: GeoJSON.Geometry[];
  refreshToken: number;
  onOpen: (feature: WorkspaceFeature) => void;
  onWorkspace: (workspace: GeoWorkspace | null, projectId: string | null) => void;
  onPlaceAnnotation: (projectId:string,layerId:string,text:string)=>void;
  onFeatureDeleted:()=>void;
  extraFeatures:WorkspaceFeature[];
}

export default function ProjectsPanel({
  geometry, featureName, featureSource, featureProperties, selectedFeatureId,
  splitParts, refreshToken, onOpen, onWorkspace, onPlaceAnnotation, onFeatureDeleted,
  extraFeatures,
}: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState('');
  const [workspace, setWorkspace] = useState<GeoWorkspace | null>(null);
  const [layerId, setLayerId] = useState('');
  const [draftName, setDraftName] = useState('');
  const [layerName, setLayerName] = useState('');
  const [noteText,setNoteText] = useState('');
  const [noteEditText,setNoteEditText] = useState('');
  const [history, setHistory] = useState<FeatureHistory | null>(null);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [busy, setBusy] = useState(false);
  const notify = useRef(onWorkspace);
  notify.current = onWorkspace;

  useEffect(() => {
    getProjects().then(list => {
      setProjects(list);
      setSelected(current => list.find(p => p.id === current) ? current : (list[0]?.id ?? ''));
    }).catch(() => setError('Cannot load saved projects.'));
  }, []);

  const reload = useCallback(async (projectId: string): Promise<GeoWorkspace> => {
    const result = await getWorkspace(projectId);
    setWorkspace(result);
    setLayerId(id => result.layers.some(l => l.id === id) ? id : (result.layers[0]?.id ?? ''));
    return result;
  }, []);

  useEffect(() => {
    if (!selected) { setWorkspace(null); return; }
    reload(selected).catch(() => setError('Cannot load project layers.'));
  }, [selected, reload, refreshToken]);

  useEffect(() => { notify.current(workspace, selected || null); }, [workspace, selected]);

  useEffect(() => {
    if (!selected || !selectedFeatureId) {
      setHistory(null);
      return;
    }
    getFeatureHistory(selected, selectedFeatureId)
      .then(setHistory).catch(() => setHistory(null));
  }, [selected, selectedFeatureId, refreshToken]);

  useEffect(()=>{
    const feature=workspace?.features.find(item=>item.id===selectedFeatureId) ??
      extraFeatures.find(item=>item.id===selectedFeatureId);
    setNoteEditText(feature?.properties.annotation===true?
      String(feature.properties.annotation_text||''):'');
  },[workspace,extraFeatures,selectedFeatureId]);
  
  const activeLayer = workspace?.layers.find(l => l.id === layerId);
  const current = workspace?.features.find(f => f.id === selectedFeatureId) ??
    extraFeatures.find(f=>f.id===selectedFeatureId);
  const locked = Boolean(current &&
    workspace?.layers.find(l => l.id === current.layer_id)?.locked);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draftName.trim()) return;
    setBusy(true); setError('');
    try {
      const created = await newProject(draftName.trim());
      setProjects(await getProjects());
      setSelected(created.id);
      setWorkspace(null);
      setDraftName('');
      setInfo('Project created.');
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  }

  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setInfo('');
    try { await action(); if (selected) await reload(selected); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Operation failed.'); }
    finally { setBusy(false); }
  }

  async function save() {
    if (!selected || !geometry) return;
    await run(async () => {
      if (current) {
        const saved = await updateProjectFeature(selected, current.id, {
          geometry, properties: featureProperties,
          expected_revision: current.revision,
        });
        onOpen(saved);
        setInfo('Existing feature updated with a new revision.');
      } else {
        if (activeLayer?.locked) throw new Error('Unlock the target layer before saving.');
        const saved = await saveProjectFeature(
          selected, featureName, geometry, featureSource, featureProperties, layerId || undefined,
        );
        const latest = await getWorkspace(selected);
        const opened = latest.features.find(item => item.id === saved.id);
        if (opened) onOpen(opened);
        setInfo('New geometry saved to the chosen layer.');
      }
    });
  }

  async function saveSplit() {
    if (!selected || splitParts.length < 2) return;
    await run(async () => {
      await saveFeatureBatch(selected,splitParts.map((part,index) => ({
        name: featureName + ' – part ' + (index+1),
        geometry: part, source:featureSource,
        properties:{...featureProperties,operation:'split'},
      })),layerId || undefined);
      setInfo('Split polygons saved as independent features.');
    });
  }

  async function exportJson() {
    if (!selected) return;
    try {
      const collection = await exportProject(selected);
      const blob = new Blob([JSON.stringify(collection, null, 2)], {
        type: 'application/geo+json',
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = 'geofathom-project.geojson';
      document.body.append(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) { setError(String(cause)); }
  }

  async function addNewLayer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !layerName.trim()) return;
    await run(async () => {
      const created = await createLayer(selected, layerName.trim(), '#2563eb');
      setLayerId(created.id);
      setLayerName('');
      setInfo('New layer added.');
    });
  }

  async function changeLayer(layer: GeoLayer, update: Partial<{
    name: string; color: string; visible: boolean; locked: boolean; z_index: number;
  }>) {
    if (!selected) return;
    await run(async () => { await patchLayer(selected, layer.id, update); });
  }

  async function styleLayer(changes:{
    labels?:Partial<GeoLayer['style']['labels']>;
    symbol?:Partial<GeoLayer['style']['symbol']>;
  }){
    if(!selected||!activeLayer||busy)return;
    const projectId=selected,layer=activeLayer;
    // React controlled inputs must update immediately. Revert from the
    // authoritative server state if an optimistic style write is rejected.
    setWorkspace(current=>current?{
      ...current,
      layers:current.layers.map(item=>item.id===layer.id?{
        ...item,style:{
          labels:{...item.style.labels,...changes.labels},
          symbol:{...item.style.symbol,...changes.symbol},
        },
      }:item),
    }:current);
    setBusy(true);setError('');setInfo('');
    try{
      await patchLayerStyle(projectId,layer.id,{
        ...changes,expected_revision:layer.style_revision,
      });
      await reload(projectId);
      setInfo('Label and symbology settings saved.');
    }catch(failure){
      setError(failure instanceof Error?failure.message:'Could not save layer style.');
      try{await reload(projectId);}catch{ /* Surface the original error. */ }
    }finally{setBusy(false);}
  }

  function placeNote(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(!selected||!activeLayer||!noteText.trim()||activeLayer.locked)return;
    onPlaceAnnotation(selected,activeLayer.id,noteText.trim());
    setNoteText('');
    setInfo('Click the map to place your note.');
  }

  async function saveNoteText(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(!selected||!current||locked||!noteEditText.trim())return;
    await run(async()=>{
      const text=noteEditText.trim();
      const updated=await updateProjectFeature(selected,current.id,{
        name:text.slice(0,80),
        properties:{...current.properties,annotation:true,annotation_text:text},
        expected_revision:current.revision,
      });
      onOpen(updated);
      setInfo('Annotation text saved as a new revision.');
    });
  }

  async function deleteSelected(){
    if(!selected||!current||locked)return;
    if(!window.confirm('Delete this feature from the project?'))return;
    await run(async()=>{
      await deleteProjectFeature(selected,current.id);
      onFeatureDeleted();
      setInfo('Feature deleted.');
    });
  }

  async function duplicate() {
    if (!selected || !current || locked) return;
    await run(async () => {
      const created = await copyProjectFeature(selected, current.id);
      const result = await getWorkspace(selected);
      const feature = result.features.find(f => f.id === created.id);
      if (feature) onOpen(feature);
      setInfo('Feature duplicated.');
    });
  }

  async function restore(revision: number) {
    if (!selected || !current || locked) return;
    await run(async () => {
      const restored = await restoreFeature(selected, current.id, revision);
      onOpen(restored);
      setInfo('A new revision was created from the selected version.');
    });
  }

  return (
    <div className="project-panel">
      <form onSubmit={create} className="project-create">
        <input aria-label="New project name" placeholder="New project name" maxLength={150}
          value={draftName} onChange={event => setDraftName(event.target.value)} />
        <button aria-label="Create project" type="submit" disabled={busy || !draftName.trim()}>
          <Plus size={16} />
        </button>
      </form>
      {projects.length > 0 && (
        <>
          <select aria-label="Active project" value={selected}
            onChange={event => { setSelected(event.target.value); setWorkspace(null); }}>
            {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>

          <div className="layer-header"><Layers3 size={14} /> Layers</div>
          {workspace?.layers.map(layer => (
            <div key={layer.id} className="layer-row">
              <button aria-label={layer.visible ? 'Hide layer' : 'Show layer'}
                title={layer.visible ? 'Hide layer' : 'Show layer'}
                onClick={() => void changeLayer(layer, { visible: !layer.visible })}>
                {layer.visible ? <Eye size={14} /> : <EyeOff size={14} />}
              </button>
              <input aria-label={'Color of ' + layer.name} type="color" value={layer.color}
                onChange={event => void changeLayer(layer, { color: event.target.value })} />
              <button className={layerId === layer.id ? 'layer-name active' : 'layer-name'}
                onClick={() => setLayerId(layer.id)}>{layer.name}</button>
              <button aria-label={layer.locked ? 'Unlock layer' : 'Lock layer'}
                onClick={() => void changeLayer(layer, { locked: !layer.locked })}>
                {layer.locked ? <Lock size={14} /> : <LockOpen size={14} />}
              </button>
              <button aria-label="Move layer higher"
                onClick={() => void changeLayer(layer, { z_index: layer.z_index + 2 })}>↑</button>
              <button aria-label="Move layer lower"
                onClick={() => void changeLayer(layer, { z_index: layer.z_index - 2 })}>↓</button>
            </div>
          ))}
          {activeLayer && (
            <details className="layer-cartography" key={activeLayer.id}>
              <summary>Labeling & map symbology · {activeLayer.name}</summary>
              <div className="cartography-editor">
                <label className="cartography-switch">
                  <input aria-label="Enable layer labels" type="checkbox"
                    checked={activeLayer.style.labels.enabled} disabled={busy}
                    onChange={event=>void styleLayer({labels:{enabled:event.target.checked}})}/>
                  Automatically label visible features
                </label>
                <label>Label source field
                  <input aria-label="Label source field" list="geo-label-fields"
                    key={activeLayer.id+'-field-'+activeLayer.style_revision}
                    defaultValue={activeLayer.style.labels.field}
                    maxLength={64}
                    onBlur={event=>{
                      const value=event.currentTarget.value.trim();
                      if(value&&value!==activeLayer.style.labels.field)
                        void styleLayer({labels:{field:value}});
                    }}
                    onKeyDown={event=>{if(event.key==='Enter')event.currentTarget.blur();}}/>
                  <datalist id="geo-label-fields">
                    <option value="name"/><option value="source"/>
                    <option value="@area_m2"/><option value="@length_m"/>
                    {Array.from(new Set(workspace?.features.flatMap(feature=>
                      Object.keys(feature.properties))??[])).slice(0,70).map(field=>
                        <option key={field} value={field}/>)}
                  </datalist>
                </label>
                <div className="cartography-grid">
                  <label>Font size (px)
                    <select aria-label="Label font size" disabled={busy}
                      value={activeLayer.style.labels.font_size}
                      onChange={event=>void styleLayer({labels:{font_size:Number(event.target.value)}})}>
                      {[9,10,11,12,14,16,18,20,24,28].map(size=>
                        <option key={size} value={size}>{size}</option>)}
                    </select>
                  </label>
                  <label>Text color
                    <input type="color" aria-label="Label text color" disabled={busy}
                      defaultValue={activeLayer.style.labels.text_color}
                      key={activeLayer.id+'-text-'+activeLayer.style_revision}
                      onBlur={event=>{if(event.currentTarget.value!==activeLayer.style.labels.text_color)
                        void styleLayer({labels:{text_color:event.currentTarget.value}});}}/>
                  </label>
                  <label>Halo color
                    <input type="color" aria-label="Label halo color" disabled={busy}
                      defaultValue={activeLayer.style.labels.halo_color}
                      key={activeLayer.id+'-halo-'+activeLayer.style_revision}
                      onBlur={event=>{if(event.currentTarget.value!==activeLayer.style.labels.halo_color)
                        void styleLayer({labels:{halo_color:event.currentTarget.value}});}}/>
                  </label>
                  <label>Halo width
                    <select aria-label="Label halo width" disabled={busy}
                      value={activeLayer.style.labels.halo_width}
                      onChange={event=>void styleLayer({labels:{halo_width:Number(event.target.value)}})}>
                      {[0,0.5,1,1.5,2].map(value=><option key={value} value={value}>{value} px</option>)}
                    </select>
                  </label>
                  <label>Min zoom
                    <select aria-label="Label min zoom" disabled={busy}
                      value={activeLayer.style.labels.min_zoom}
                      onChange={event=>void styleLayer({labels:{min_zoom:Number(event.target.value)}})}>
                      {Array.from({length:25},(_,i)=>i).map(i=><option key={i} value={i}>{i}</option>)}
                    </select>
                  </label>
                  <label>Max zoom
                    <select aria-label="Label max zoom" disabled={busy}
                      value={activeLayer.style.labels.max_zoom}
                      onChange={event=>void styleLayer({labels:{max_zoom:Number(event.target.value)}})}>
                      {Array.from({length:25},(_,i)=>i).map(i=><option key={i} value={i}>{i}</option>)}
                    </select>
                  </label>
                  <label>Fill opacity
                    <select aria-label="Polygon fill opacity" disabled={busy}
                      value={activeLayer.style.symbol.fill_opacity}
                      onChange={event=>void styleLayer({symbol:{fill_opacity:Number(event.target.value)}})}>
                      {[0,0.1,0.17,0.25,0.4,0.6,0.8,1].map(value=>
                        <option key={value} value={value}>{value}</option>)}
                    </select>
                  </label>
                  <label>Line width
                    <select aria-label="Map line width" disabled={busy}
                      value={activeLayer.style.symbol.line_width}
                      onChange={event=>void styleLayer({symbol:{line_width:Number(event.target.value)}})}>
                      {[1,2,3,4,6,8].map(value=><option key={value} value={value}>{value}px</option>)}
                    </select>
                  </label>
                </div>
                <label>Category color attribute
                  <input aria-label="Category color field" maxLength={64}
                    placeholder="e.g. category, landuse, status"
                    key={activeLayer.id+'-category-field-'+activeLayer.style_revision}
                    defaultValue={activeLayer.style.symbol.category_field}
                    onBlur={event=>{
                      const value=event.currentTarget.value.trim();
                      if(value!==activeLayer.style.symbol.category_field)
                        void styleLayer({symbol:{
                          category_field:value,category_colors:{},
                        }});
                    }}
                    onKeyDown={event=>{if(event.key==='Enter')event.currentTarget.blur();}}/>
                </label>
                <button className="category-build" disabled={busy||
                  !activeLayer.style.symbol.category_field.trim()}
                  onClick={()=> {
                    const field=activeLayer.style.symbol.category_field;
                    const values=Array.from(new Set(
                      (workspace?.features??[])
                        .filter(feature=>feature.layer_id===activeLayer.id)
                        .map(feature=>field==='name'?feature.name:
                          field==='source'?feature.source:feature.properties[field])
                        .filter(value=>typeof value==='string'||typeof value==='number'||typeof value==='boolean')
                        .map(value=>String(value))
                        .filter(value=>value.length>0&&value.length<=80)
                    )).sort((a,b)=>a.localeCompare(b)).slice(0,20);
                    const palette=['#2979b9','#ef6d49','#4d9b80','#8856a7','#d9a441',
                      '#cb5a88','#599fc3','#9b7a45','#537ab6','#7ca34d',
                      '#a9674e','#997eb9','#41a3a4','#bf6c43','#738b4b',
                      '#ca819b','#47829b','#a4a44c','#c47768','#6283ae'];
                    void styleLayer({symbol:{
                      category_colors:Object.fromEntries(values.map((value,index)=>
                        [value,palette[index]])),
                    }});
                  }}>
                  Generate colors for attribute categories
                </button>
                {Object.entries(activeLayer.style.symbol.category_colors).map(([category,color])=>
                  <label className="category-color-row" key={category}>
                    <span>{category}</span>
                    <input type="color" aria-label={'Color for category '+category}
                      key={activeLayer.style_revision+'-'+category}
                      defaultValue={color} disabled={busy}
                      onBlur={event=>{
                        if(event.currentTarget.value!==color)
                          void styleLayer({symbol:{
                            category_colors:{...activeLayer.style.symbol.category_colors,
                              [category]:event.currentTarget.value},
                          }});
                      }}/>
                  </label>
                )}
                <p className="project-hint">Choose an existing attribute and assign a different
                  color to each unique value (up to 20 categories).
                  Unknown values retain the layer’s default color.</p>
                <label className="cartography-switch">
                  <input aria-label="Allow overlapping labels" type="checkbox" disabled={busy}
                    checked={activeLayer.style.labels.allow_overlap}
                    onChange={event=>void styleLayer({labels:{allow_overlap:event.target.checked}})}/>
                  Allow labels to overlap (normally off)
                </label>
                <p className="project-hint">
                  Fields include name, source, @area_m2, @length_m and custom properties.
                  Each layer has independent styling and collision handling.
                </p>
              </div>
            </details>
          )}
          <form className="project-create" onSubmit={placeNote}>
            <input aria-label="Map note text" placeholder="Map note / label text"
              maxLength={120} value={noteText}
              onChange={event=>setNoteText(event.target.value)}/>
            <button aria-label="Place map note" type="submit"
              disabled={busy||!noteText.trim()||!selected||Boolean(activeLayer?.locked)}>
              <MapPin size={14}/>
            </button>
          </form>
          <form className="project-create" onSubmit={addNewLayer}>
            <input aria-label="New layer name" placeholder="Add map layer" value={layerName}
              onChange={event => setLayerName(event.target.value)} maxLength={100}/>
            <button type="submit" disabled={busy || !layerName.trim()}><Plus size={14}/></button>
          </form>
          <div className="project-actions">
            <button onClick={() => void save()} disabled={busy || !geometry || locked || Boolean(!current && activeLayer?.locked)}>
              <Save size={14}/> {current ? 'Update feature' : 'Save selected'}
            </button>
            <button onClick={() => void exportJson()} disabled={busy}>
              <Download size={14}/> Export
            </button>
          </div>
          {splitParts.length > 1 && (
            <button className="project-split-save" disabled={busy || Boolean(activeLayer?.locked)}
              onClick={() => void saveSplit()}>Save all {splitParts.length} split pieces</button>
          )}

          <div className="project-features">
            {workspace?.features.map(item => {
              const layer = workspace.layers.find(l => l.id === item.layer_id);
              return (
                <button key={item.id} disabled={!layer?.visible} onClick={() => onOpen(item)}
                  className={selectedFeatureId === item.id ? 'active' : ''}>
                  <FolderOpen size={14}/><span>{item.name}</span><small>r{item.revision}</small>
                </button>
              );
            })}
            {extraFeatures.filter(f=>!(workspace?.features??[]).some(x=>x.id===f.id))
              .slice(0,60).map(item=><button key={item.id}
              className={selectedFeatureId===item.id?'active':''}
              onClick={()=>onOpen(item)}>
                <FolderOpen size={14}/><span>{item.name}</span><small>r{item.revision}</small>
              </button>)}
            {!workspace?.features.length&&!extraFeatures.length &&
              <p className="project-hint">No saved features yet.</p>}
          </div>

          {current&&<details className="feature-inspector">
            <summary>Identify feature · properties & measurement</summary>
            <div className="feature-inspector-body">
              <p><strong>Name:</strong> {current.name}</p>
              <p><strong>Type:</strong> {current.geometry.type}</p>
              <p><strong>Source:</strong> {current.source}</p>
              {current.measurement.area_m2!==null&&
                <p><strong>Area:</strong> {current.measurement.area_m2.toLocaleString('en-US',
                  {maximumFractionDigits:2})} m²</p>}
              {current.measurement.perimeter_m!==null&&
                <p><strong>Perimeter:</strong> {current.measurement.perimeter_m.toFixed(2)} m</p>}
              {current.measurement.length_m!==null&&
                <p><strong>Length:</strong> {current.measurement.length_m.toFixed(2)} m</p>}
              <p><strong>Revision:</strong> {current.revision}</p>
              {Object.entries(current.properties).slice(0,30).map(([key,value])=>
                <p key={key}><strong>{key}:</strong> {typeof value==='object'
                  ?JSON.stringify(value).slice(0,150):String(value).slice(0,150)}</p>)}
              <button type="button" onClick={()=>onOpen(current)}>Zoom to feature</button>
              <button type="button" onClick={async()=>{
                try{
                  await navigator.clipboard.writeText(JSON.stringify({
                    type:'Feature',geometry:current.geometry,properties:{
                      ...current.properties,name:current.name,source:current.source,
                    },
                  },null,2));
                  setInfo('Feature GeoJSON copied.');
                }catch{setError('Clipboard permissions are unavailable.');}
              }}>Copy feature GeoJSON</button>
            </div>
          </details>}
          {current && (
            <>
              {current.properties.annotation===true&&(
                <form className="project-create" onSubmit={event=>void saveNoteText(event)}>
                  <input aria-label="Edit selected map note"
                    maxLength={120} value={noteEditText}
                    onChange={event=>setNoteEditText(event.target.value)}/>
                  <button type="submit" aria-label="Save map note text"
                    disabled={busy||locked||!noteEditText.trim()}>
                    <Save size={14}/>
                  </button>
                </form>
              )}
              <div className="project-actions">
                <button onClick={() => void duplicate()} disabled={busy || locked}>
                  <Copy size={13}/> Duplicate
                </button>
                <button onClick={() => {
                  if (history) setHistory(null);
                  else if (selected) void getFeatureHistory(selected, current.id).then(setHistory);
                }}><History size={13}/> Versions</button>
                <button aria-label="Delete selected map feature"
                  onClick={()=>void deleteSelected()} disabled={busy||locked}>Delete</button>
              </div>
              {history && (
                <div className="version-list">
                  {history.versions.map(item => (
                    <button key={item.revision} onClick={() => void restore(item.revision)}
                      disabled={busy || locked || item.revision === history.current_revision}>
                      <RotateCcw size={12}/>
                      Revision {item.revision} · {new Date(item.created_at).toLocaleString()}
                      {item.measurement?.area_m2 != null ? ' · ' + item.measurement.area_m2.toFixed(2) + ' m²' : ''}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </>
      )}
      {!projects.length && <p className="project-hint">Create a project to keep geometry and layer history.</p>}
      {info && <p className="project-info">{info}</p>}
      {error && <p className="discovery-error">{error}</p>}
    </div>
  );
}
