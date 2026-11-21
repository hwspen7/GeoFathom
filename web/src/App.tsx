import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  ArrowRight, Compass, Download, Globe2, Layers3, MapPin,
  MousePointer2, Pencil, RotateCcw, Search, Send, Sparkles,
  Wifi, WifiOff,
} from 'lucide-react';

import {
  getCapabilities, interpret, measureGeometry, searchPlaces,
  type Capabilities, type Measurement, type Place,
} from './api';
import MapCanvas, { type FocusPoint } from './MapCanvas';
import SurveyTools from './SurveyTools';
import ProfessionalPanel from './ProfessionalPanel';
import { featureColor, legendEntries, DEFAULT_LAYER_STYLE } from './labels';
import ImageCorrectionPanel, { type PromptMode } from './ImageCorrectionPanel';
import {
  GeometryTimeline, approximateMeasurement, previewEdgeLengths, pathsOf,
  singleMovedVertex, type Position, type ShapeMode,
} from './editing';
import DiscoveryPanel from './DiscoveryPanel';
import type { DiscoveryResponse, GeoWorkspace, WorkspaceFeature } from './api';
import ProjectsPanel from './ProjectsPanel';
import ModelControls from './ModelControls';
import RasterPanel, { type TraceSettings } from './RasterPanel';
import {
  addMapAnnotation, applyOverlay, applyTopology, constructGeometry, editPair, getWorkspace, moveMeasured,
  previewTopology, refineRaster, traceExisting, traceImagery,
  type SharedTopologyPreview, type RasterAsset,
} from './api';

const number = (value: number, digits = 2) =>
  new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(value);

export default function App() {
  const [locationInput, setLocationInput] = useState('');
  const [prompt, setPrompt] = useState('');
  const [candidates, setCandidates] = useState<Place[]>([]);
  const [selectedPlace, setSelectedPlace] = useState<Place | null>(null);
  const [geometry, setGeometry] = useState<GeoJSON.Geometry | null>(null);
  const [measurement, setMeasurement] = useState<Measurement | null>(null);
  const [drawingMode, setDrawingMode] = useState<ShapeMode>(null);
  const [vertices, setVertices] = useState<Position[]>([]);
  const [viewport, setViewport] = useState<[number, number, number, number] | null>(null);
  const [discovered, setDiscovered] = useState<Place[]>([]);
  const [focus, setFocus] = useState<FocusPoint | null>(null);
  const [message, setMessage] = useState('Search a place or draw a shape directly on the map.');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [assistantQuery, setAssistantQuery] = useState('');
  const [modelId, setModelId] = useState('local-saluki');
  const [modelUsed, setModelUsed] = useState<boolean | null>(null);
  const [toolSteps, setToolSteps] = useState<string[]>([]);
  const [satellite, setSatellite] = useState(false);
  const [imageLayer, setImageLayer] = useState<RasterAsset | null>(null);
  const [traceMode, setTraceMode] = useState(false);
  const [promptMode,setPromptMode] = useState<PromptMode>(null);
  const [positivePoints,setPositivePoints] = useState<Position[]>([]);
  const [negativePoints,setNegativePoints] = useState<Position[]>([]);
  const [boxPoints,setBoxPoints] = useState<Position[]>([]);
  const [traceSettings, setTraceSettings] = useState<TraceSettings>({
    method: 'color', tolerance: 20, window_size: 512,
  });
  const [geometrySource, setGeometrySource] = useState('');
  const [featureProperties, setFeatureProperties] = useState<Record<string, unknown>>({});
  const [editing, setEditing] = useState(false);
  const [moving, setMoving] = useState(false);
  const [snapping, setSnapping] = useState(true);
  const [projectWorkspace, setProjectWorkspace] = useState<GeoWorkspace | null>(null);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(null);
  const [splitParts, setSplitParts] = useState<GeoJSON.Geometry[]>([]);
  const [refreshToken,setRefreshToken] = useState(0);
  const [pendingAnnotation,setPendingAnnotation] = useState<{
    projectId:string;layerId:string;text:string;
  }|null>(null);
  const [showLegend,setShowLegend] = useState(true);
  const [linked,setLinked] = useState(false);
  const [pendingShared,setPendingShared] = useState<{
    preview:SharedTopologyPreview;old:[number,number];next:[number,number];
  }|null>(null);
  const [preview, setPreview] = useState<ReturnType<typeof approximateMeasurement> | null>(null);
  const [areaUnit, setAreaUnit] = useState<'m2' | 'ha' | 'km2' | 'mu'>('m2');
  const timeline = useRef(new GeometryTimeline());
  const lastValid = useRef<GeoJSON.Geometry | null>(null);
  const [historyPulse, setHistoryPulse] = useState(0);

  const selectedSaved = projectWorkspace?.features.find(item => item.id === selectedFeatureId);
  const selectedLocked = Boolean(selectedSaved &&
    projectWorkspace?.layers.find(layer => layer.id === selectedSaved.layer_id)?.locked);

  async function commitGeometry(next: GeoJSON.Geometry, details = 'Geometry updated and validated.', detached = false) {
    if (selectedLocked && !detached) {
      setError('Unlock the selected layer before editing geometry.');
      return;
    }
    try {
      if (linked && selectedFeatureId && activeProjectId && !detached && lastValid.current) {
        const moved=singleMovedVertex(lastValid.current,next);
        if (!moved) throw new Error('Linked mode requires moving exactly one existing vertex.');
        const impact=await previewTopology(activeProjectId,moved.old,moved.next);
        if (!impact.affected.some(item=>item.id===selectedFeatureId)) {
          throw new Error('Selected feature does not contain this shared vertex.');
        }
        setPendingShared({preview:impact,old:moved.old,next:moved.next});
        setGeometry(next);
        setPreview(approximateMeasurement(next));
        setMessage('Linked vertex preview ready. Confirm all affected feature changes.');
        return;
      }
      const checked = await measureGeometry(next);
      setGeometry(next);
      setMeasurement(checked);
      setPreview(null);
      lastValid.current = structuredClone(next);
      timeline.current.push(next);
      setHistoryPulse(value => value + 1);
      setError('');
      setMessage(details);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Invalid geometry.');
      setGeometry(lastValid.current);
      setPreview(null);
    }
  }

  function applyHistory(next: GeoJSON.Geometry | null) {
    setGeometry(next);
    lastValid.current = next ? structuredClone(next) : null;
    setPreview(null);
    setHistoryPulse(value => value + 1);
    if (next) void measureGeometry(next).then(setMeasurement).catch(() => setMeasurement(null));
    else setMeasurement(null);
  }

  function openStoredFeature(feature: WorkspaceFeature) {
    setPendingShared(null);
    setGeometry(feature.geometry);
    lastValid.current = structuredClone(feature.geometry);
    timeline.current.push(feature.geometry);
    setHistoryPulse(value => value + 1);
    setMeasurement(feature.measurement);
    setFeatureProperties(feature.properties);
    setGeometrySource(feature.source);
    setSelectedFeatureId(feature.id);
    setSelectedPlace(null);
    setCandidates([]);
    setDiscovered([]);
    setSplitParts([]);
    setDrawingMode(null);
    setEditing(false);
    setMoving(false);
    const [west, south, east, north] = feature.measurement.bounds;
    setFocus({
      longitude: (west + east) / 2, latitude: (south + north) / 2,
      bbox: [west, south, east, north], key: Date.now(),
    });
    setMessage('Loaded feature: ' + feature.name + ' · revision ' + feature.revision);
  }

  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      if (event.target instanceof HTMLInputElement ||
          event.target instanceof HTMLTextAreaElement ||
          event.target instanceof HTMLSelectElement) return;
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() === 'z') {
        event.preventDefault();
        applyHistory(event.shiftKey ? timeline.current.redo() : timeline.current.undo());
      } else if (event.key.toLowerCase() === 'y') {
        event.preventDefault();
        applyHistory(timeline.current.redo());
      }
    }
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, []);


  const satelliteAvailable = Boolean(import.meta.env.VITE_SATELLITE_TILES_URL);

  useEffect(() => {
    getCapabilities().then(setCapabilities).catch(() => setCapabilities(null));
  }, []);

  async function selectPlace(place: Place) {
    setSelectedPlace(place);
    setSelectedFeatureId(null);
    setLinked(false);
    setEditing(false);
    setMoving(false);
    setSplitParts([]);
    setDrawingMode(null);
    setTraceMode(false);
    setVertices([]);
    setGeometry(
      place.geometry || {
        type: 'Point',
        coordinates: [place.longitude, place.latitude],
      },
    );
    setMeasurement(null);
    if (place.geometry) {
      lastValid.current = structuredClone(place.geometry);
      timeline.current.push(place.geometry);
      setHistoryPulse(value => value + 1);
    }
    setGeometrySource(place.source);
    setFeatureProperties({ source_type: 'mapped_openstreetmap', osm_id: place.osm_id, osm_type: place.osm_type });
    setFocus({
      latitude: place.latitude,
      longitude: place.longitude,
      bbox: place.bbox,
      key: Date.now(),
    });
    if (place.geometry) {
      try {
        const result = await measureGeometry(place.geometry);
        setMeasurement(result);
        setMessage('Mapped boundary loaded. Check that it represents your intended area.');
      } catch (problem) {
        setError(problem instanceof Error ? problem.message : 'Could not measure boundary.');
        setMessage('Place found, but the mapped geometry could not be measured.');
      }
    } else {
      setMessage('Location found without a mapped boundary. Draw a polygon to measure it.');
    }
  }

  async function runSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = locationInput.trim();
    if (query.length < 2) return;
    setBusy(true);
    setError('');
    try {
      const found = await searchPlaces(query);
      setCandidates(found);
      if (found.length) {
        await selectPlace(found[0]);
        if (found.length > 1) setMessage('Multiple candidates found. Confirm the correct place below.');
      } else {
        setMessage('No place found. Try a different spelling or draw directly on the map.');
      }
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Search failed.');
    } finally {
      setBusy(false);
    }
  }

  async function runAssistant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = prompt.trim();
    if (query.length < 2) return;
    setBusy(true);
    setError('');
    setAssistantQuery(query);
    try {
      const answer = await interpret(query, viewport, modelId);
      setModelUsed(answer.model_used);
      setToolSteps((answer.steps || []).map(step => step.tool + ' · ' + step.status));
      setCandidates(answer.results);
      setMessage(answer.message);
      if (answer.intent.action === 'discover') {
        setDiscovered(answer.results);
        setSelectedPlace(null);
        setGeometry(null);
        setMeasurement(null);
      } else {
        setDiscovered([]);
        if (answer.results.length) await selectPlace(answer.results[0]);
        if (answer.results.length > 1) setMessage(answer.message + ' Select the correct candidate.');
      }
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Assistant request failed.');
    } finally {
      setBusy(false);
    }
  }

  function startDrawing(next: Exclude<ShapeMode, null>) {
    if(next==='trace-along'&&!projectWorkspace?.features.some(f=>
      f.geometry.type==='LineString'||f.geometry.type==='MultiLineString')) {
      setError('Save at least one vector line feature in the active project to trace along.');
      return;
    }
    const operation = next === 'hole' || next === 'split';
    if (selectedLocked && operation) { setError('Unlock this layer before changing its geometry.'); return; }
    if (operation && geometry?.type !== 'Polygon' && geometry?.type !== 'MultiPolygon') {
      setError('Select a polygon before cutting a hole or splitting it.');
      return;
    }
    setDrawingMode(next);
    setTraceMode(false);
    if (!operation) {
      setGeometrySource('User drawn');
      setFeatureProperties({ source_type: 'user_drawn' });
    } else {
      setFeatureProperties(current => ({ ...current, last_operation: next }));
    }
    setVertices([]);
    if (!operation) {
      setGeometry(null);
      setSelectedFeatureId(null);
      setMeasurement(null);
      setSplitParts([]);
    }
    setEditing(false);
    setMoving(false);
    setSelectedPlace(null);
    setCandidates([]);
    setDiscovered([]);
    setError('');
    setMessage(['polygon', 'hole'].includes(next)
      ? 'Click at least three corners, then Finish.'
      : 'Click two or more points to define the geometry, then Finish.');
  }

  async function finishDrawing() {
    if (!drawingMode) return;
    const mode = drawingMode;
    const required = ['polygon','hole'].includes(mode) ? 3 : 2;
    if (vertices.length < required) {
      setError('Add more points before finishing.');
      return;
    }
    setBusy(true); setError('');
    try {
      let result: GeoJSON.Geometry;
      let measured: Measurement;
      if (mode === 'trace-along') {
        const paths=(projectWorkspace?.features ?? [])
          .filter(feature=>feature.geometry.type==='LineString'||feature.geometry.type==='MultiLineString')
          .flatMap(feature=>pathsOf(feature.geometry));
        const traced=await traceExisting(vertices[0],vertices[1],paths);
        result=traced.geometry;
        measured=traced.measurement;
        setSelectedFeatureId(null);
        setGeometrySource('Vector network tracing');
        setFeatureProperties({source_type:'vector_trace',method:'shortest connected path'});
      } else if (mode === 'polygon' || mode === 'rectangle' || mode === 'circle') {
        let constructed;
        if (mode === 'circle') {
          const path = { type: 'LineString', coordinates: vertices.slice(0,2) } as GeoJSON.LineString;
          const line = await measureGeometry(path);
          constructed = await constructGeometry({
            mode, vertices: vertices.slice(0,1), radius_m: line.length_m ?? 0,
          });
        } else {
          constructed = await constructGeometry({
            mode, vertices: mode === 'rectangle' ? vertices.slice(0,2) : vertices,
          });
        }
        result = constructed.geometry; measured = constructed.measurement;
      } else if (mode === 'line' || mode === 'split') {
        result = { type: 'LineString', coordinates: vertices };
        measured = await measureGeometry(result);
      } else {
        const constructed = await constructGeometry({ mode: 'polygon', vertices });
        result = constructed.geometry; measured = constructed.measurement;
      }
      if (mode === 'hole' && geometry) {
        const cut = await editPair('hole',geometry,result);
        result = cut.geometry; measured = cut.measurement;
      } else if (mode === 'split' && geometry) {
        const divided = await editPair('split',geometry,result);
        setSplitParts(divided.features.map(item => item.geometry));
        setDiscovered([]);
        result = divided.features[0].geometry;
        measured = divided.features[0].measurement;
        setSelectedFeatureId(null);
      }
      setGeometry(result);
      lastValid.current = structuredClone(result);
      timeline.current.push(result);
      setHistoryPulse(value => value + 1);
      setMeasurement(measured);
      setDrawingMode(null); setVertices([]); setPreview(null);
      setMessage(mode === 'split'
        ? 'Polygon divided. Save all pieces from Projects & saved geometry.'
        : 'Drawing completed and measured on the WGS84 ellipsoid.');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Drawing failed.');
    } finally { setBusy(false); }
  }

  async function numericShape(mode: string, body: {
    vertices: Position[]; radius_m?: number; bearing_deg?: number; length_m?: number;
  }) {
    setBusy(true); setError('');
    try {
      const created = await constructGeometry({
        mode: mode as 'rectangle' | 'circle' | 'bearing',
        ...body,
      });
      setSelectedFeatureId(null);
      setGeometrySource('Numeric geodesic construction');
      setFeatureProperties({ source_type:'numeric', mode });
      await commitGeometry(created.geometry,'Precise construction created with PyProj.',true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Numeric construction failed.');
    } finally { setBusy(false); }
  }

  async function combineWith(mode: 'union' | 'difference' | 'intersection', featureId: string) {
    const other = projectWorkspace?.features.find(item => item.id === featureId);
    if (!geometry || !other) return;
    setBusy(true); setError('');
    try {
      const result = await applyOverlay(mode, geometry, other.geometry);
      if (!result.geometry) throw new Error('Operation produced no geographic area.');
      setSelectedFeatureId(null);
      setGeometrySource('Spatial overlay · ' + mode);
      setFeatureProperties({ source_type:'spatial_operation', operation:mode });
      await commitGeometry(result.geometry, 'Spatial ' + mode + ' completed.',true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Spatial overlay failed.');
    } finally { setBusy(false); }
  }


  function clearWorkspace() {
    setGeometry(null);
    setPendingAnnotation(null);
    setPromptMode(null);setPositivePoints([]);setNegativePoints([]);setBoxPoints([]);
    setPendingShared(null);
    lastValid.current = null;
    timeline.current.push(null);
    setHistoryPulse(value => value + 1);
    setSelectedFeatureId(null);
    setSplitParts([]);
    setPreview(null);
    setEditing(false);
    setMoving(false);
    setMeasurement(null);
    setDrawingMode(null);
    setTraceMode(false);
    setVertices([]);
    setSelectedPlace(null);
    setCandidates([]);
    setDiscovered([]);
    setError('');
    setGeometrySource('');
    setFeatureProperties({});
    setMessage('Workspace cleared. Search or draw to get started.');
  }

  function exportGeoJSON() {
    if (!geometry) return;
    const feature: GeoJSON.Feature = {
      type: 'Feature',
      geometry,
      properties: {
        name: selectedPlace?.name ?? 'Custom measurement',
        source: selectedPlace?.source ?? 'User-drawn geometry',
        boundary_status: selectedPlace?.boundary_status ?? (featureProperties.source_type === 'image_derived' ? 'estimated_from_imagery' : 'user_drawn'),
        ...featureProperties,
        measured_using: 'WGS84 ellipsoidal geodesic',
      },
    };
    const blob = new Blob([JSON.stringify(feature, null, 2)], { type: 'application/geo+json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'geofathom-feature.geojson';
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div className="workspace">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Globe2 size={23} strokeWidth={1.9} /></div>
          <div><strong>GeoFathom</strong><span>GEOSPATIAL INTELLIGENCE</span></div>
        </div>
        <div className="sidebar-scroll">
          <div className="intro">
            <div className="eyebrow"><Sparkles size={13} /> LOCAL-FIRST WORKSPACE</div>
            <h1>Explore the world, <em>spatially.</em></h1>
            <p>Find geographic features, inspect mapped boundaries, and measure real-world shapes.</p>
          </div>

          <section className="panel-section">
            <div className="section-heading"><Search size={16} /><span>Find a place</span></div>
            <form onSubmit={runSearch} className="search-form">
              <input aria-label="Search for a place" placeholder="Airport, landmark, city, address…" value={locationInput}
                onChange={event => setLocationInput(event.target.value)} maxLength={200} />
              <button aria-label="Search" type="submit" disabled={busy || locationInput.trim().length < 2}>
                <ArrowRight size={17} />
              </button>
            </form>
          </section>

          <section className="panel-section">
            <div className="section-heading"><Sparkles size={16} /><span>Ask GeoFathom</span><span className="section-pill">Assistant</span></div>
            <ModelControls modelId={modelId} onChange={setModelId} />
            <form onSubmit={runAssistant} className="prompt-form">
              <textarea aria-label="Ask the geospatial assistant" placeholder="Measure Shanghai Hongqiao Airport's mapped boundary…" value={prompt}
                onChange={event => setPrompt(event.target.value)} maxLength={500} rows={3} />
              <div className="prompt-footer">
                <span>{modelUsed === null ? 'Selected model / GIS fallback' : modelUsed ? 'AI parsed the request' : 'GIS fallback interpretation'}</span>
                <button type="submit" disabled={busy || prompt.trim().length < 2}>
                  <Send size={15} /> Run
                </button>
              </div>
            </form>
            {assistantQuery && <div className="last-prompt">“{assistantQuery}” <span>{modelUsed ? 'AI parsed' : 'Rules parsed'}</span></div>}
            {toolSteps.length > 0 && <div className="tool-trace"><strong>Execution trace</strong><span>{toolSteps.join(' → ')}</span></div>}
          </section>

          <section className="panel-section">
            <div className="section-heading"><Pencil size={16} /><span>Survey & geometry editor</span><span className="section-pill">Precision</span></div>
            <SurveyTools
              mode={drawingMode}
              geometry={geometry}
              points={vertices}
              editing={editing}
              moving={moving}
              snapping={snapping}
              linked={linked}
              onLinked={enabled=>{
                if(enabled&&!selectedFeatureId){
                  setError('Open a saved feature to use linked vertex editing.');
                  return;
                }
                setLinked(enabled);setPendingShared(null);
              }}
              canUndo={timeline.current.canUndo && historyPulse >= 0}
              canRedo={timeline.current.canRedo && historyPulse >= 0}
              saved={activeProjectId ? projectWorkspace?.features ?? [] : []}
              onStart={startDrawing}
              onFinish={() => { void finishDrawing(); }}
              onCancel={() => { setDrawingMode(null); setVertices([]); }}
              onUndoPoint={() => setVertices(value => value.slice(0,-1))}
              onUndo={() => applyHistory(timeline.current.undo())}
              onRedo={() => applyHistory(timeline.current.redo())}
              onEdit={(active, shouldMove) => {
                if (selectedLocked) {
                  setError('Unlock the feature layer before editing.');
                } else {
                  setEditing(active); setMoving(shouldMove);
                  setDrawingMode(null); setVertices([]);
                }
              }}
              onSnapping={setSnapping}
              onAddPoint={point => {
                if (drawingMode) setVertices(value => [...value, point]);
                else setError('Select a drawing mode before adding precise coordinates.');
              }}
              onNumeric={(mode, body) => { void numericShape(mode, body); }}
              onOverlay={(mode, featureId) => { void combineWith(mode,featureId); }}
              onDuplicate={() => {
                if (geometry) {
                  setSelectedFeatureId(null);
                  setGeometrySource('Copied from current geometry');
                  void commitGeometry(structuredClone(geometry), 'Copied geometry. Save as a separate feature.',true);
                }
              }}
            />
 
            {pendingShared && <div className="linked-preview">
              <strong>Shared boundary preview · {pendingShared.preview.count} features</strong>
              {pendingShared.preview.affected.map(item=><div key={item.id}>
                {item.name} · r{item.revision}
                {item.locked?' · LOCKED':''}{!item.valid?' · INVALID':''}
              </div>)}
              <div className="survey-action-bar">
                <button onClick={()=>{
                  setGeometry(lastValid.current);setPendingShared(null);setPreview(null);
                }}>Cancel</button>
                <button disabled={busy||pendingShared.preview.affected.some(x=>x.locked||!x.valid)}
                  onClick={async()=>{
                    if(!activeProjectId)return;
                    setBusy(true);setError('');
                    try{
                      const expected=Object.fromEntries(pendingShared.preview.affected.map(item=>
                        [item.id,item.revision]));
                      await applyTopology(activeProjectId,pendingShared.old,pendingShared.next,expected);
                      const updated=await getWorkspace(activeProjectId);
                      setProjectWorkspace(updated);
                      const reopened=updated.features.find(item=>item.id===selectedFeatureId);
                      if(reopened)openStoredFeature(reopened);
                      setPendingShared(null);setRefreshToken(v=>v+1);
                    }catch(failure){
                      setError(failure instanceof Error?failure.message:'Linked edit failed.');
                      setGeometry(lastValid.current);setPendingShared(null);
                    }finally{setBusy(false);}
                  }}>Apply to all linked features</button>
              </div>
            </div>}
         </section>

          <section className="panel-section">
            <div className="section-heading"><Layers3 size={16} /><span>Georeferenced imagery</span></div>
            <RasterPanel
              asset={imageLayer}
              onSelect={(asset) => {
                setImageLayer(asset);
                setTraceMode(false);
                const [west, south, east, north] = asset.bbox;
                setFocus({
                  longitude: (west + east) / 2, latitude: (south + north) / 2,
                  bbox: asset.bbox, key: Date.now(),
                });
                setMessage('Loaded georeferenced image ' + asset.name + '. Click automatic outline to select an object.');
              }}
              tracing={traceMode}
              onTracing={(enabled) => {
                setTraceMode(enabled);
                if (enabled) { setDrawingMode(null); setVertices([]); }
              }}
              settings={traceSettings}
              onSettings={setTraceSettings}
              viewport={viewport}
            />
 
            <ImageCorrectionPanel
              enabled={Boolean(imageLayer)}
              mode={promptMode}
              onMode={mode=>{
                setPromptMode(mode);setTraceMode(false);setDrawingMode(null);
              }}
              positive={positivePoints}
              negative={negativePoints}
              box={boxPoints}
              busy={busy}
              onClear={()=>{
                setPositivePoints([]);setNegativePoints([]);
                setBoxPoints([]);setPromptMode(null);
              }}
              onRefine={async()=>{
                if(!imageLayer||positivePoints.length===0)return;
                setBusy(true);setError('');
                try{
                  const refined=await refineRaster({
                    image_id:imageLayer.id,positive_points:positivePoints,
                    negative_points:negativePoints,
                    box:boxPoints.length===2?boxPoints:null,
                    window_size:traceSettings.window_size,
                  });
                  setGeometry(refined.geometry);
                  lastValid.current=structuredClone(refined.geometry);
                  timeline.current.push(refined.geometry);
                  setHistoryPulse(x=>x+1);
                  setMeasurement(refined.measurement);
                  setSelectedFeatureId(null);setEditing(false);
                  setGeometrySource('Local SAM 2 refinement · '+imageLayer.name);
                  setFeatureProperties({
                    source_type:'image_derived',image_id:imageLayer.id,
                    model_id:refined.model_id,method:'sam2-prompt-refinement',
                    positive_count:refined.positive_count,
                    negative_count:refined.negative_count,
                    box_used:refined.box_used,
                    quality:'requires_user_review',
                  });
                  setPromptMode(null);
                  setMessage(refined.warning);
                }catch(failure){
                  setError(failure instanceof Error?failure.message:'SAM 2 refinement unavailable.');
                }finally{setBusy(false);}
              }}
            />
         </section>

          <section className="panel-section">
            <div className="section-heading"><Layers3 size={16} /><span>Projects & saved geometry</span></div>
            <ProjectsPanel
              geometry={geometry}
              featureName={selectedPlace?.name || 'Custom boundary'}
              featureSource={geometrySource || selectedPlace?.source || 'User drawn'}
              featureProperties={featureProperties}
              selectedFeatureId={selectedFeatureId}
              splitParts={splitParts}
              refreshToken={refreshToken}
              onWorkspace={(data, id) => {
                setProjectWorkspace(data);
                setActiveProjectId(id);
              }}
              onOpen={openStoredFeature}
              onFeatureDeleted={clearWorkspace}
              onPlaceAnnotation={(projectId,layerId,text)=>{
                setPendingAnnotation({projectId,layerId,text});
                setDrawingMode(null);setTraceMode(false);setPromptMode(null);
                setEditing(false);setMoving(false);
                setMessage('Click the map where the annotation should be placed.');
              }}
            />
          </section>

          <section className="panel-section">
            <div className="section-heading"><Layers3 size={16}/><span>Professional GIS tools</span></div>
            <ProfessionalPanel
              projectId={activeProjectId}
              workspace={projectWorkspace}
              geometry={geometry}
              raster={imageLayer}
              refreshToken={refreshToken}
              onRefresh={()=>setRefreshToken(v=>v+1)}
              onOpen={id=>{
                const feature=projectWorkspace?.features.find(item=>item.id===id);
                if(feature)openStoredFeature(feature);
              }}
            />
          </section>

          <section className="panel-section">
            <div className="section-heading"><Search size={16} /><span>Find areas by size</span><span className="section-pill">Spatial query</span></div>
            <DiscoveryPanel viewport={viewport} busy={busy} onFound={(result: DiscoveryResponse) => {
              setDiscovered(result.results);
              setCandidates(result.results);
              setSelectedPlace(null);
              setGeometry(null);
              setMeasurement(null);
              setSelectedFeatureId(null);
              setMessage(result.results.length
                ? 'Found ' + result.results.length + ' mapped features. ' + result.warning
                : 'No mapped features matched the filter. ' + result.warning);
              setError('');
            }} />
          </section>

          {candidates.length > 0 && (
            <section className="panel-section">
              <div className="section-heading"><MapPin size={16} /><span>Search results</span><span className="result-count">{candidates.length}</span></div>
              <div className="results">
                {candidates.map(place => (
                  <button key={place.id} className={selectedPlace?.id === place.id ? 'result active' : 'result'} onClick={() => { setError(''); void selectPlace(place); }}>
                    <MapPin size={15} />
                    <span className="result-text"><strong>{place.name}</strong><small>{place.display_name}</small></span>
                    <span className={place.boundary_status === 'mapped' ? 'result-tag mapped' : 'result-tag'}>
                      {place.boundary_status === 'mapped' ? 'Boundary' : 'Point'}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}

          <section className="panel-section results-summary">
            <div className="section-heading"><Compass size={16} /><span>Analysis</span></div>
            <div className="analysis-card">
              <div className="analysis-status">{error ? <span className="error">{error}</span> : message}</div>
              {measurement && (
                <>
                  <div className="metric">
                    <span>{measurement.area_m2 !== null ? 'Geographic area' : 'Distance'}</span>
                    <strong>{measurement.area_km2 !== null
                      ? number(measurement.area_km2, 4) + ' km²'
                      : measurement.length_m !== null ? number(measurement.length_m / 1000, 3) + ' km' : 'Location only'}</strong>
                  </div>
                  {measurement.perimeter_m !== null && <div className="metric secondary"><span>Perimeter</span><strong>{number(measurement.perimeter_m / 1000, 3)} km</strong></div>}
                  {measurement.area_m2 !== null && <div className="metric secondary"><span>Square meters</span><strong>{number(measurement.area_m2)} m²</strong></div>}
                  <p className="analysis-footnote">{measurement.method}. {measurement.note}</p>
                </>
              )}
              {(() => {
                const temporary = preview ?? (
                  drawingMode && vertices.length >= 2
                    ? approximateMeasurement(vertices.length >= 3 && drawingMode !== 'line' && drawingMode !== 'split'
                      ? { type: 'Polygon', coordinates: [[...vertices, vertices[0]]] }
                      : { type: 'LineString', coordinates: vertices })
                    : null
                );
                return temporary ? (
                  <div className="metric preview">
                    <span>Live estimate · final accuracy after Finish</span>
                    <strong>{temporary.area_m2 !== null
                      ? number(temporary.area_m2, 2) + ' m²'
                      : number(temporary.length_m ?? 0, 2) + ' m'}</strong>
                  </div>
                ) : null;
              })()}
              {measurement?.area_m2 !== null && measurement?.area_m2 !== undefined && (
                <div className="area-unit-picker">
                  <label htmlFor="area-unit">Area unit</label>
                  <select id="area-unit" value={areaUnit}
                    onChange={event => setAreaUnit(event.target.value as typeof areaUnit)}>
                    <option value="m2">Square meters</option>
                    <option value="ha">Hectares</option>
                    <option value="km2">Square kilometers</option>
                    <option value="mu">Mu (亩)</option>
                  </select>
                  <strong>{number((measurement.area_m2 ?? 0) /
                    (areaUnit === 'ha' ? 10000 : areaUnit === 'km2' ? 1000000 : areaUnit === 'mu' ? 2000 / 3 : 1),4)}</strong>
                </div>
              )}
              {geometry && ['Polygon','MultiPolygon','LineString','MultiLineString'].includes(geometry.type) && (
                <details className="edge-measurements">
                  <summary>Edge lengths · {previewEdgeLengths(geometry).total} segments</summary>
                  <div>
                    {previewEdgeLengths(geometry).edges.map((edge, index) =>
                      <div key={index}><span>{edge.label}</span><strong>~ {number(edge.length_m,2)} m</strong></div>)}
                  </div>
                  <p className="project-hint">Live spherical preview. Final area/perimeter is calculated on the WGS84 ellipsoid.</p>
                </details>
              )}
              {selectedPlace && <p className="data-source">Data: {selectedPlace.source} · {selectedPlace.boundary_status === 'mapped' ? 'Mapped outline' : 'Coordinates only'}</p>}
              <div className="analysis-actions">
                <button onClick={exportGeoJSON} disabled={!geometry}><Download size={15} /> Export GeoJSON</button>
                <button onClick={clearWorkspace}><RotateCcw size={15} /> Clear</button>
              </div>
            </div>
          </section>
        </div>
        <div className="sidebar-footer">
          {capabilities ? <span><Wifi size={14} /> API connected</span> : <span><WifiOff size={14} /> API not connected</span>}
          <span>No fabricated measurements</span>
        </div>
      </aside>

      <main className="main">
        <div className="map-topbar">
          <div className="map-title"><span className="map-title-icon"><Layers3 size={18} /></span><div><strong>Explore</strong><span>Interactive map workspace</span></div></div>
          <div className="map-controls">
            <button className={!satellite ? 'map-control selected' : 'map-control'} onClick={() => setSatellite(false)}><Globe2 size={16} /> Streets</button>
            {satelliteAvailable && <button className={satellite ? 'map-control selected' : 'map-control'} onClick={() => setSatellite(true)}><Layers3 size={16} /> Imagery</button>}
          </div>
        </div>
        <div className="map-wrap">
          <MapCanvas
            selected={geometry} drawingMode={drawingMode} vertices={vertices}
            editing={editing} moving={moving} snapping={snapping}
            selectedLocked={selectedLocked}
            layerFeatures={[...(projectWorkspace?.features ?? [])].sort((a,b) => {
              const aIndex=projectWorkspace?.layers.find(layer=>layer.id===a.layer_id)?.z_index ?? 0;
              const bIndex=projectWorkspace?.layers.find(layer=>layer.id===b.layer_id)?.z_index ?? 0;
              return aIndex-bIndex;
            }).map(feature => {
              const layer = projectWorkspace?.layers.find(item => item.id === feature.layer_id);
              return {
                id: feature.id, layer_id: feature.layer_id, geometry: feature.geometry,
                name:feature.name,source:feature.source,properties:feature.properties,
                measurement:feature.measurement,style:layer?.style ?? DEFAULT_LAYER_STYLE,
                color:featureColor(feature,layer?.style??DEFAULT_LAYER_STYLE,
                  layer?.color??'#2563eb'),visible:Boolean(layer?.visible),
                locked: Boolean(layer?.locked),
              };
            })}
            onGeometryPreview={next => {
              setGeometry(next);
              setPreview(approximateMeasurement(next));
            }}
            onGeometryCommit={(next,movement) => {
              if(!movement){void commitGeometry(next);return;}
              if(selectedLocked){setError('Unlock the feature layer.');return;}
              void moveMeasured(movement.original,movement.bearing_deg,movement.distance_m)
                .then(result=>commitGeometry(result.geometry,
                  'Shape translated by geodesic distance and azimuth.'))
                .catch(error=>{
                  setError(error instanceof Error?error.message:'Geodesic translation failed.');
                  setGeometry(lastValid.current);setPreview(null);
                });
            }}
            onSelectSavedFeature={id => {
              const feature = projectWorkspace?.features.find(item => item.id === id);
              if (feature) openStoredFeature(feature);
            }}
            focus={focus} satellite={satellite}
            imageLayer={imageLayer} traceMode={traceMode||promptMode!==null}
            promptPositive={positivePoints} promptNegative={negativePoints}
            promptBox={boxPoints}
            onTraceClick={async ([longitude, latitude]) => {
              if (promptMode!==null) {
                const location:Position=[longitude,latitude];
                if(promptMode==='positive')setPositivePoints(points=>points.length>=20?points:[...points,location]);
                else if(promptMode==='negative')setNegativePoints(points=>points.length>=20?points:[...points,location]);
                else setBoxPoints(points=>points.length>=2?[location]:[...points,location]);
                return;
              }
              if (!imageLayer || busy) return;
              setBusy(true);
              setError('');
              try {
                const result = await traceImagery({
                  image_id: imageLayer.id, longitude, latitude,
                  ...traceSettings,
                });
                setGeometry(result.geometry);
                lastValid.current = structuredClone(result.geometry);
                timeline.current.push(result.geometry);
                setHistoryPulse(value => value + 1);
                setSelectedFeatureId(null);
                setEditing(false);
                setMeasurement(result.measurement);
                setSelectedPlace(null);
                setCandidates([]);
                setDiscovered([]);
                setGeometrySource(imageLayer.provenance + ' · ' + result.engine);
                setFeatureProperties({
                  source_type: 'image_derived',
                  image_id: imageLayer.id,
                  image_name: imageLayer.name,
                  image_acquired_at: imageLayer.acquired_at,
                  image_crs: imageLayer.crs,
                  trace_method: result.provider,
                  trace_engine: result.engine,
                  trace_model_id: result.model_id,
                  trace_pixel_count: result.pixel_count,
                  trace_confidence: result.confidence,
                  trace_window_truncated: result.window_truncated,
                  trace_warning: result.warning,
                  quality: 'requires_user_review',
                });
                setTraceMode(false);
                setMessage(result.warning + ' (' + result.pixel_count + ' source pixels selected)');
              } catch (failure) {
                setError(failure instanceof Error ? failure.message : 'Automatic outline failed.');
              } finally {
                setBusy(false);
              }
            }}
            discovered={[...discovered.map(place => place.geometry).filter((item): item is GeoJSON.Geometry => item !== null), ...splitParts.slice(1)]}
            annotationMode={Boolean(pendingAnnotation)}
            onAnnotationClick={async position=>{
              if(!pendingAnnotation||busy)return;
              setBusy(true);setError('');
              try{
                const {projectId,layerId,text}=pendingAnnotation;
                const created=await addMapAnnotation(projectId,text,position,layerId);
                const latest=await getWorkspace(projectId);
                setProjectWorkspace(latest);
                setRefreshToken(value=>value+1);
                const opened=latest.features.find(feature=>feature.id===created.id);
                if(opened)openStoredFeature(opened);
                setPendingAnnotation(null);
                setMessage('Map annotation saved.');
              }catch(failure){
                setError(failure instanceof Error?failure.message:'Could not place annotation.');
              }finally{setBusy(false);}
            }}
            onViewportChange={setViewport}
            onMapClick={position => {
              const max = ['rectangle','circle','trace-along'].includes(drawingMode ?? '') ? 2 : 4000;
              setVertices(value => value.length >= max ? value : [...value, position]);
            }}
          />
          <div className="map-legend">
            <button className="map-legend-toggle" aria-label="Toggle map legend"
              onClick={()=>setShowLegend(value=>!value)}>
              <Layers3 size={15}/> Legend
            </button>
            {showLegend&&<div className="map-legend-items" aria-label="Map legend">
              {legendEntries(projectWorkspace?.layers??[],projectWorkspace?.features??[]).map(item=>(
                <div key={item.id} className="map-legend-item">
                  <span className="legend-swatch" style={{
                    borderColor:item.color,
                    backgroundColor:item.color,
                    opacity:Math.max(.3,item.opacity),
                  }}/>
                  <span>{item.name}</span>
                  {item.labels&&<small>Labels</small>}
                </div>
              ))}
              {!(projectWorkspace?.layers??[]).some(layer=>Boolean(layer.visible))&&
                <small>No visible project layers</small>}
            </div>}
          </div>
          {pendingAnnotation&&<div className="annotation-banner">
            Click map to place: <strong>{pendingAnnotation.text}</strong>
            <button onClick={()=>setPendingAnnotation(null)} aria-label="Cancel map note">
              Cancel
            </button>
          </div>}
          <div className="map-hint"><MousePointer2 size={15} /> {pendingAnnotation ? 'Click map to place a permanent label' :
            traceMode ? 'Click imported imagery to trace a region' : drawingMode ? 'Click corners, then Finish' : editing ? 'Drag handles or use Move. Right-click corner to delete.' : 'Pan, zoom, or choose a result'}</div>
          <div className="map-badge"><span className="live-dot" /> WGS84 GEODESIC ENGINE</div>
        </div>
        <div className="bottom-bar">
          <span><Compass size={14} /> Coordinate-based analysis</span>
          <span><Globe2 size={14} /> OpenStreetMap contributors</span>
        </div>
      </main>
    </div>
  );
}
