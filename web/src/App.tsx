import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  ArrowRight, Compass, Download, Globe2, Layers3, MapPin,
  Pencil, RotateCcw, Search, Send, Sparkles,
  Wifi, WifiOff,
} from 'lucide-react';

import {
  getCapabilities, interpret, measureGeometry, searchPlaces,
  type Capabilities, type Measurement, type Place,
} from './api';
import MapCanvas, { type FocusPoint } from './MapCanvas';
import {BASEMAPS,type BasemapId} from './basemaps';
import SurveyTools from './SurveyTools';
import ProfessionalPanel from './ProfessionalPanel';
import TerrainWorkbench from './TerrainWorkbench';
import SpatialToolsPanel from './SpatialToolsPanel';
import CartographyProPanel from './CartographyProPanel';
import DataServicesPanel, {type ExternalTile} from './DataServicesPanel';
import { featureColor, legendEntries, DEFAULT_LAYER_STYLE } from './labels';
import ImageCorrectionPanel, { type PromptMode } from './ImageCorrectionPanel';
import {
  GeometryTimeline, approximateMeasurement, previewEdgeLengths, pathsOf, drawingPreview,
  singleMovedVertex, type Position, type ShapeMode,
} from './editing';
import DiscoveryPanel from './DiscoveryPanel';
import type { DiscoveryResponse, GeoWorkspace, WorkspaceFeature, QualityIssue } from './api';
import ProjectsPanel from './ProjectsPanel';
import ModelControls from './ModelControls';
import RasterPanel, { type TraceSettings } from './RasterPanel';
import GeoAIAnalysisPanel from './GeoAIAnalysisPanel';
import ApiAccessPanel from './ApiAccessPanel';
import {
  addMapAnnotation, applyOverlay, applyTopology, constructGeometry, editPair, getWorkspace, moveMeasured,
  previewTopology, refineRaster, traceExisting, traceImagery,
  updateProjectFeature,
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
  const [basemap,setBasemap]=useState<BasemapId>('street');
  const [toolbarTarget,setToolbarTarget]=useState<HTMLDivElement|null>(null);
  const [showTools,setShowTools]=useState(true);
  const [showMeasurements,setShowMeasurements]=useState(true);
  const [rasterVisible,setRasterVisible]=useState(true);
  const [rasterOpacity,setRasterOpacity]=useState(.88);
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
  const [edgeMoving,setEdgeMoving]=useState(false);
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
  const [selectionBoxMode,setSelectionBoxMode]=useState(false);
  const [selectionBox,setSelectionBox]=useState<[number,number,number,number]|null>(null);
  const [spatialSelected,setSpatialSelected]=useState<string[]>([]);
  const [qualityIssues,setQualityIssues]=useState<QualityIssue[]>([]);
  const [projectGrid,setProjectGrid]=useState<GeoJSON.FeatureCollection|null>(null);
  const [labelMoveMode,setLabelMoveMode]=useState(false);
  const [externalTiles,setExternalTiles]=useState<ExternalTile[]>([]);
  const [externalFeatures,setExternalFeatures]=useState<GeoJSON.Geometry[]>([]);
  const [pagedFeatures,setPagedFeatures]=useState<WorkspaceFeature[]>([]);
  const [linked,setLinked] = useState(false);
  const [pendingShared,setPendingShared] = useState<{
    preview:SharedTopologyPreview;old:[number,number];next:[number,number];
  }|null>(null);
  const [preview, setPreview] = useState<ReturnType<typeof approximateMeasurement> | null>(null);
  const [areaUnit, setAreaUnit] = useState<'m2' | 'ha' | 'km2' | 'mu'>('m2');
  const timeline = useRef(new GeometryTimeline());
  const lastValid = useRef<GeoJSON.Geometry | null>(null);
  // Geometry responses must belong to the latest editing intent, not
  // merely the request that happens to finish last.
  const geometrySequence = useRef(0);
  const projectIdentity = useRef<string | null>(null);
  const projectEpoch = useRef(0);
  const renderEpoch = projectEpoch.current;
  // Even switching A -> B -> A must invalidate old A callbacks.
  const projectCurrent = () => projectEpoch.current === renderEpoch &&
    projectIdentity.current === activeProjectId;
  const featureIdentity = useRef<string | null>(null);
  const [historyPulse, setHistoryPulse] = useState(0);

  featureIdentity.current = selectedFeatureId;
  const selectedSaved = projectWorkspace?.features.find(item => item.id === selectedFeatureId) ??
    pagedFeatures.find(item => item.id === selectedFeatureId);
  const selectedLocked = Boolean(selectedSaved &&
    projectWorkspace?.layers.find(layer => layer.id === selectedSaved.layer_id)?.locked);

  async function commitGeometry(next: GeoJSON.Geometry, details = 'Geometry updated and validated.', detached = false) {
    if (selectedLocked && !detached) {
      setError('Unlock the selected layer before editing geometry.');
      return;
    }
    const sequence = ++geometrySequence.current;
    try {
      if (linked && selectedFeatureId && activeProjectId && !detached && lastValid.current) {
        const moved=singleMovedVertex(lastValid.current,next);
        if (!moved) throw new Error('Linked mode requires moving exactly one existing vertex.');
        const impact=await previewTopology(activeProjectId,moved.old,moved.next);
        if (sequence !== geometrySequence.current) return;
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
      if (sequence !== geometrySequence.current) return;
      setGeometry(next);
      setMeasurement(checked);
      setPreview(null);
      lastValid.current = structuredClone(next);
      timeline.current.push(next);
      setHistoryPulse(value => value + 1);
      setError('');
      setMessage(details);
    } catch (failure) {
      if (sequence !== geometrySequence.current) return;
      setError(failure instanceof Error ? failure.message : 'Invalid geometry.');
      setGeometry(lastValid.current);
      setPreview(null);
    }
  }

  function applyHistory(next: GeoJSON.Geometry | null) {
    const sequence = ++geometrySequence.current;
    setPendingShared(null);
    setGeometry(next);
    lastValid.current = next ? structuredClone(next) : null;
    setPreview(null);
    setHistoryPulse(value => value + 1);
    setMeasurement(null);
    if (next) void measureGeometry(next).then(value => {
      if (sequence === geometrySequence.current) setMeasurement(value);
    }).catch(() => {
      if (sequence === geometrySequence.current) setMeasurement(null);
    });
  }

  function openStoredFeature(feature: WorkspaceFeature) {
    // A callback from a previous project may finish after navigation.
    if (feature.project_id !== projectIdentity.current) return;
    geometrySequence.current++;
    if (featureIdentity.current !== feature.id) {
      timeline.current = new GeometryTimeline();
      setLinked(false);
    }
    featureIdentity.current = feature.id;
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
    setEditing(false);setEdgeMoving(false);
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


  function revealPanel(id:string){
    setShowTools(true);
    requestAnimationFrame(()=>document.getElementById(id)?.scrollIntoView({block:'start'}));
  }

  useEffect(() => {
    getCapabilities().then(setCapabilities).catch(() => setCapabilities(null));
  }, []);

  async function selectPlace(place: Place) {
    const sequence = ++geometrySequence.current;
    setSelectedPlace(place);
    setSelectedFeatureId(null);
    setLinked(false);
    setEditing(false);setEdgeMoving(false);
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
        if (sequence !== geometrySequence.current) return;
        setMeasurement(result);
        setMessage('Mapped boundary loaded. Check that it represents your intended area.');
      } catch (problem) {
        if (sequence !== geometrySequence.current) return;
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
    const sequence=++geometrySequence.current;
    try {
      const found = await searchPlaces(query);
      if(sequence!==geometrySequence.current)return;
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
    const sequence=++geometrySequence.current;
    try {
      const answer = await interpret(query, viewport, modelId);
      if(sequence!==geometrySequence.current)return;
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
    geometrySequence.current++;
    setDrawingMode(next);setEdgeMoving(false);
    setTraceMode(false);
    setPromptMode(null);setPendingAnnotation(null);setSelectionBoxMode(false);setLabelMoveMode(false);
    if (!operation) {
      if(featureIdentity.current){
        timeline.current=new GeometryTimeline();
        lastValid.current=null;
        setHistoryPulse(value=>value+1);
      }
      setLinked(false);
      setPendingShared(null);
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
    setEditing(false);setEdgeMoving(false);
    setMoving(false);
    setSelectedPlace(null);
    setCandidates([]);
    setDiscovered([]);
    setError('');
    setMessage(next==='point'?'Click a location, then Finish.':
      ['polygon','hole'].includes(next)?'Click corners, then Finish.':'Click start and end, then Finish.');
  }

  async function finishDrawing() {
    if (!drawingMode) return;
    const mode = drawingMode;
    const required = mode==='point'?1:['polygon','hole'].includes(mode) ? 3 : 2;
    if (vertices.length < required) {
      setError('Add more points before finishing.');
      return;
    }
    const sequence=++geometrySequence.current;
    setBusy(true); setError('');
    try {
      let result: GeoJSON.Geometry;
      let measured: Measurement;
      if(mode==='point'){
        result={type:'Point',coordinates:vertices[0]};
        measured=await measureGeometry(result);
      }else if (mode === 'trace-along') {
        const paths=(projectWorkspace?.features ?? [])
          .filter(feature=>feature.geometry.type==='LineString'||feature.geometry.type==='MultiLineString')
          .flatMap(feature=>pathsOf(feature.geometry));
        const traced=await traceExisting(vertices[0],vertices[1],paths);
        if(sequence!==geometrySequence.current)return;
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
        if(sequence!==geometrySequence.current)return;
        setSplitParts(divided.features.map(item => item.geometry));
        setDiscovered([]);
        result = divided.features[0].geometry;
        measured = divided.features[0].measurement;
        setSelectedFeatureId(null);
      }
      if(sequence!==geometrySequence.current)return;
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
      if(sequence===geometrySequence.current)
        setError(failure instanceof Error ? failure.message : 'Drawing failed.');
    } finally { setBusy(false); }
  }

  async function numericShape(mode: string, body: {
    vertices: Position[]; radius_m?: number; bearing_deg?: number; length_m?: number;
  }) {
    const sequence=++geometrySequence.current;
    setBusy(true); setError('');
    try {
      const created = mode==='point'
        ? {geometry:{type:'Point',coordinates:body.vertices[0]} as GeoJSON.Point}
        : await constructGeometry({mode:mode as 'rectangle'|'circle'|'bearing',...body});
      if(sequence!==geometrySequence.current)return;
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
    const sequence=++geometrySequence.current;
    setBusy(true); setError('');
    try {
      const result = await applyOverlay(mode, geometry, other.geometry);
      if(sequence!==geometrySequence.current)return;
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
    geometrySequence.current++;
    setGeometry(null);
    setPendingAnnotation(null);
    setSelectionBoxMode(false);setSelectionBox(null);
    setSpatialSelected([]);setQualityIssues([]);setProjectGrid(null);
    setLabelMoveMode(false);
    setExternalFeatures([]);setPagedFeatures([]);
    setPromptMode(null);setPositivePoints([]);setNegativePoints([]);setBoxPoints([]);
    setPendingShared(null);
    lastValid.current = null;
    timeline.current.push(null);
    setHistoryPulse(value => value + 1);
    setSelectedFeatureId(null);
    setSplitParts([]);
    setPreview(null);
    setEditing(false);setEdgeMoving(false);
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

  useEffect(()=>{
    function commands(event:KeyboardEvent){
      if(event.target instanceof HTMLInputElement||event.target instanceof HTMLTextAreaElement||
        event.target instanceof HTMLSelectElement||event.ctrlKey||event.metaKey)return;
      if(event.key==='Escape'){
        geometrySequence.current++;setDrawingMode(null);setVertices([]);
        setEditing(false);setEdgeMoving(false);setMoving(false);setTraceMode(false);setPromptMode(null);
        setSelectionBoxMode(false);setLabelMoveMode(false);setPendingAnnotation(null);
        if(preview||pendingShared){setGeometry(lastValid.current);setPreview(null);setPendingShared(null);}
      }else if(drawingMode&&!busy&&event.key==='Enter'){
        event.preventDefault();void finishDrawing();
      }else if(drawingMode&&!busy&&event.key==='Backspace'){
        event.preventDefault();setVertices(value=>value.slice(0,-1));
      }
    }
    window.addEventListener('keydown',commands);
    return ()=>window.removeEventListener('keydown',commands);
  });
  return (
    <div className="workspace desktop-gis">
      <header className="gis-header">
        <div className="gis-brand"><Globe2 size={19}/> <strong>GeoFathom</strong></div>
        <nav aria-label="Workspace tools" className="gis-menu">
          {([['Survey','tools-survey'],['GIS','tools-gis'],['Analysis','tools-spatial'],['Raster / AI','tools-raster'],['Cartography','tools-style'],['Data','tools-services'],['Assistant','tools-ai']] as const).map(([title,id])=>
            <button key={id} onClick={()=>revealPanel(id)}>{title}</button>)}
        </nav>
        <button className="gis-inspector-toggle" aria-pressed={showTools} onClick={()=>setShowTools(v=>!v)}>Inspector</button>
        <span className="gis-connection">{capabilities?<Wifi size={14}/>:<WifiOff size={14}/>} {capabilities?'Connected':'Offline'}</span>
      </header>
      <div className="gis-toolbar" aria-label="Survey toolbar" ref={setToolbarTarget}/>
      <div className="gis-body">
        <aside className="sidebar gis-layers">
          <div className="dock-heading"><Layers3 size={15}/> Project / Layers</div>
          <div className="sidebar-scroll">
          <section className="panel-section">
            <div className="section-heading"><Layers3 size={16} /><span>Projects & saved geometry</span></div>
            <ProjectsPanel
              geometry={preview || pendingShared ? null : geometry}
              featureName={selectedPlace?.name || 'Custom boundary'}
              featureSource={geometrySource || selectedPlace?.source || 'User drawn'}
              featureProperties={featureProperties}
              selectedFeatureId={selectedFeatureId}
              splitParts={splitParts}
              refreshToken={refreshToken}
              extraFeatures={pagedFeatures}
              onWorkspace={(data, id) => {
                if(projectIdentity.current!==id){
                  projectIdentity.current=id;
                  projectEpoch.current++;
                  geometrySequence.current++;
                  // Keep an explicitly unsaved draft when creating a project,
                  // but never carry a saved feature or its undo stack across
                  // project identities.
                  if(featureIdentity.current || pendingShared){
                    clearWorkspace();
                    timeline.current=new GeometryTimeline();
                    featureIdentity.current=null;
                  }else{
                    timeline.current=new GeometryTimeline();
                    if(lastValid.current)timeline.current.push(lastValid.current);
                    setHistoryPulse(value=>value+1);
                  }
                  setPendingAnnotation(null);setPendingShared(null);setLinked(false);
                  setPagedFeatures([]);setExternalFeatures([]);setExternalTiles([]);
                  setSpatialSelected([]);setQualityIssues([]);setProjectGrid(null);
                  setSelectionBox(null);setSelectionBoxMode(false);setLabelMoveMode(false);
                }
                setProjectWorkspace(data);
                setActiveProjectId(id);
              }}
              onOpen={openStoredFeature}
              onFeatureDeleted={clearWorkspace}
              onPlaceAnnotation={(projectId,layerId,text)=>{
                setPendingAnnotation({projectId,layerId,text});
                setDrawingMode(null);setTraceMode(false);setPromptMode(null);
                setEditing(false);setEdgeMoving(false);setMoving(false);
                setMessage('Click the map where the annotation should be placed.');
              }}
            />
          </section>


            <section className="panel-section gis-basemaps">
              <div className="section-heading"><Globe2 size={15}/><span>Basemap</span></div>
              <select aria-label="Basemap" value={basemap} onChange={event=>setBasemap(event.target.value as BasemapId)}>
                {BASEMAPS.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
              <label className="gis-check"><input type="checkbox" checked={showMeasurements} onChange={e=>setShowMeasurements(e.target.checked)}/> Map dimensions</label>
              {imageLayer&&<><label className="gis-check"><input type="checkbox" checked={rasterVisible} onChange={e=>setRasterVisible(e.target.checked)}/> {imageLayer.name}</label>
              <label>Raster opacity <input aria-label="Raster opacity" type="range" min="0" max="1" step=".05" value={rasterOpacity} onChange={e=>setRasterOpacity(Number(e.target.value))}/></label></>}
            </section>
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


          </div>
        </aside>
        <main className="main">
        <div className="map-wrap">
          <MapCanvas
            selected={geometry} drawingMode={drawingMode} vertices={vertices}
            editing={editing} moving={moving} edgeMoving={edgeMoving} snapping={snapping}
            selectedLocked={selectedLocked}
            layerFeatures={[...(projectWorkspace?.features ?? []),
              ...pagedFeatures.filter(feature=>!(projectWorkspace?.features??[])
                .some(row=>row.id===feature.id))].sort((a,b) => {
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
              if(!projectCurrent())return;
              geometrySequence.current++;
              setGeometry(next);
              setPreview(approximateMeasurement(next));
            }}
            onGeometryCommit={(next,movement) => {
              if(!projectCurrent())return;
              if(!movement){void commitGeometry(next);return;}
              if(selectedLocked){setError('Unlock the feature layer.');return;}
              const sequence=++geometrySequence.current;
              void moveMeasured(movement.original,movement.bearing_deg,movement.distance_m)
                .then(result=>{
                  if(sequence===geometrySequence.current)return commitGeometry(result.geometry,
                    'Shape translated by geodesic distance and azimuth.');
                })
                .catch(error=>{
                  if(sequence!==geometrySequence.current)return;
                  setError(error instanceof Error?error.message:'Geodesic translation failed.');
                  setGeometry(lastValid.current);setPreview(null);
                });
            }}
            onSelectSavedFeature={id => {
              const feature = projectWorkspace?.features.find(item => item.id === id) ??
                pagedFeatures.find(item=>item.id===id);
              if (feature) openStoredFeature(feature);
            }}
            focus={focus} basemap={basemap}
            measurement={preview?null:measurement} showMeasurements={showMeasurements}
            selectedFeatureId={selectedFeatureId}
            imageLayer={rasterVisible?imageLayer:null} rasterOpacity={rasterOpacity}
            traceMode={traceMode||promptMode!==null}
            promptPositive={positivePoints} promptNegative={negativePoints}
            promptBox={boxPoints}
            selectionBoxMode={selectionBoxMode}
            onSelectionBox={box=>{
              setSelectionBox(box);setSelectionBoxMode(false);
              setMessage('Selection rectangle ready. Choose a spatial relation and select matches.');
            }}
            selectedIds={spatialSelected}
            qualityIssues={qualityIssues.map(issue=>issue.geometry)}
            projectGrid={projectGrid}
            externalTiles={externalTiles}
            labelMoveMode={labelMoveMode}
            onLabelMove={(id,dx,dy)=>{
              const current=[...(projectWorkspace?.features??[]),...pagedFeatures]
                .find(item=>item.id===id);
              if(!activeProjectId||!current||busy)return;
              const activeLayer=projectWorkspace?.layers.find(
                layer=>layer.id===current.layer_id);
              if(activeLayer?.locked){
                setError('Unlock the feature layer before moving its label.');
                return;
              }
              setBusy(true);setError('');
              void updateProjectFeature(activeProjectId,id,{
                properties:{...current.properties,
                  label_offset_x:dx,label_offset_y:dy},
                expected_revision:current.revision,
              }).then(updated=>{
                if(!projectCurrent())return;
                setRefreshToken(value=>value+1);
                if(selectedFeatureId===id)openStoredFeature(updated);
                setMessage('Label position stored as a new feature revision.');
              }).catch(failure=>{
                setError(failure instanceof Error?failure.message:'Label movement failed.');
              }).finally(()=>setBusy(false));
            }}
            onTraceClick={async ([longitude, latitude]) => {
              if (promptMode!==null) {
                const location:Position=[longitude,latitude];
                if(promptMode==='positive')setPositivePoints(points=>points.length>=20?points:[...points,location]);
                else if(promptMode==='negative')setNegativePoints(points=>points.length>=20?points:[...points,location]);
                else setBoxPoints(points=>points.length>=2?[location]:[...points,location]);
                return;
              }
              if (!imageLayer || busy) return;
              const sequence=++geometrySequence.current;
              setBusy(true);
              setError('');
              try {
                const result = await traceImagery({
                  image_id: imageLayer.id, longitude, latitude,
                  ...traceSettings,
                });
                if(sequence!==geometrySequence.current)return;
                setGeometry(result.geometry);
                lastValid.current = structuredClone(result.geometry);
                timeline.current.push(result.geometry);
                setHistoryPulse(value => value + 1);
                setSelectedFeatureId(null);
                setEditing(false);setEdgeMoving(false);
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
            discovered={[...discovered.map(place => place.geometry).filter((item): item is GeoJSON.Geometry => item !== null),
              ...externalFeatures,...splitParts.slice(1)]}
            annotationMode={Boolean(pendingAnnotation)}
            onAnnotationClick={async position=>{
              if(!pendingAnnotation||busy||pendingAnnotation.projectId!==projectIdentity.current)return;
              setBusy(true);setError('');
              try{
                const {projectId,layerId,text}=pendingAnnotation;
                const created=await addMapAnnotation(projectId,text,position,layerId);
                const latest=await getWorkspace(projectId);
                if(!projectCurrent()||projectIdentity.current!==projectId)return;
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
              if(busy)return;
              const max=drawingMode==='point'?1:['rectangle','circle','trace-along'].includes(drawingMode??'')?2:4000;
              setVertices(value=>value.length>=max||(value.length>0&&value[value.length-1][0]===position[0]&&value[value.length-1][1]===position[1])?value:[...value,position]);
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
        </div>

        </main>
        <aside className="gis-inspector" hidden={!showTools}>
          <div className="dock-heading"><Compass size={15}/> Inspector</div>
          <div className="sidebar-scroll">
          <section className="panel-section results-summary">
            <div className="section-heading"><Compass size={16} /><span>Analysis</span></div>
            <div className="analysis-card">
              
              {measurement && !preview && (
                <>
                  <div className="metric">
                    <span>{measurement.area_m2 !== null ? 'Geographic area' : 'Distance'}</span>
                    <strong>{measurement.area_km2 !== null
                      ? number(measurement.area_km2, 4) + ' km²'
                      : measurement.length_m !== null ? number(measurement.length_m / 1000, 3) + ' km' : 'Location only'}</strong>
                  </div>
                  {measurement.perimeter_m !== null && <div className="metric secondary"><span>Perimeter</span><strong>{number(measurement.perimeter_m / 1000, 3)} km</strong></div>}
                  {measurement.area_m2 !== null && <div className="metric secondary"><span>Square meters</span><strong>{number(measurement.area_m2)} m²</strong></div>}
                  <p className="analysis-footnote">{measurement.method}</p>
                </>
              )}
              {(() => {
                const temporary = preview ?? (
                  drawingPreview(drawingMode,vertices)?approximateMeasurement(drawingPreview(drawingMode,vertices)!):null
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
                      <div key={index}><span>{edge.label}</span><strong>{!preview&&measurement?.edge_lengths_m?.[index]!==undefined?'':'~ '}{number(!preview?(measurement?.edge_lengths_m?.[index]??edge.length_m):edge.length_m,2)} m</strong></div>)}
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

          <section id="tools-survey" className="panel-section">
            <div className="section-heading"><Pencil size={16} /><span>Survey & geometry editor</span><span className="section-pill">Precision</span></div>
            <SurveyTools
              toolbarTarget={toolbarTarget} busy={busy} locked={selectedLocked}
              edgeMoving={edgeMoving} onEdgeMove={active=>{
                setEdgeMoving(active);setEditing(active);setMoving(false);setLinked(false);
                setDrawingMode(null);setVertices([]);setTraceMode(false);setPromptMode(null);
                setPendingAnnotation(null);setSelectionBoxMode(false);setLabelMoveMode(false);
              }}
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
                setLinked(enabled);if(enabled)setEdgeMoving(false);setPendingShared(null);
              }}
              canUndo={timeline.current.canUndo && historyPulse >= 0}
              canRedo={timeline.current.canRedo && historyPulse >= 0}
              saved={activeProjectId ? projectWorkspace?.features ?? [] : []}
              onStart={startDrawing}
              onFinish={() => { if(!busy)void finishDrawing(); }}
              onCancel={() => { geometrySequence.current++; setDrawingMode(null); setVertices([]); }}
              onUndoPoint={() => setVertices(value => value.slice(0,-1))}
              onUndo={() => applyHistory(timeline.current.undo())}
              onRedo={() => applyHistory(timeline.current.redo())}
              onEdit={(active, shouldMove) => {
                if (selectedLocked) {
                  setError('Unlock the feature layer before editing.');
                } else {
                  setEdgeMoving(false);setEditing(active); setMoving(shouldMove);
                  setDrawingMode(null); setVertices([]);setTraceMode(false);setPromptMode(null);setPendingAnnotation(null);setSelectionBoxMode(false);setLabelMoveMode(false);
                }
              }}
              onSnapping={setSnapping}
              onAddPoint={point => {
                if(drawingMode)setVertices(value=>value.length>=(drawingMode==='point'?1:['rectangle','circle','trace-along'].includes(drawingMode)?2:4000)?value:[...value,point]);
                else void numericShape('point',{vertices:[point]});
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
                      if(!projectCurrent())return;
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


          <section id="tools-raster" className="panel-section">
            <div className="section-heading"><Layers3 size={16} /><span>Georeferenced imagery</span></div>
            <RasterPanel
              asset={imageLayer}
              onSelect={(asset) => {
                geometrySequence.current++;
                setImageLayer(asset);setRasterVisible(true);
                setTraceMode(false);
                setPromptMode(null);setPositivePoints([]);setNegativePoints([]);setBoxPoints([]);
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
                if (enabled) {setRasterVisible(true);setDrawingMode(null);setVertices([]);setEditing(false);setEdgeMoving(false);setMoving(false);setPendingAnnotation(null);setSelectionBoxMode(false);setLabelMoveMode(false);setPromptMode(null);}
              }}
              settings={traceSettings}
              onSettings={setTraceSettings}
              viewport={viewport}
            />
            <GeoAIAnalysisPanel
              key={activeProjectId ?? 'no-project'}
              projectId={activeProjectId}
              image={imageLayer}
              onPreview={value=>{if(projectCurrent())setExternalFeatures(value);}}
              onSaved={()=>setRefreshToken(value=>value+1)}
            />
 
            <ImageCorrectionPanel
              enabled={Boolean(imageLayer)}
              mode={promptMode}
              onMode={mode=>{
                setRasterVisible(true);setPromptMode(mode);setTraceMode(false);setDrawingMode(null);setEditing(false);setEdgeMoving(false);setMoving(false);setPendingAnnotation(null);setSelectionBoxMode(false);setLabelMoveMode(false);
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
                if(!imageLayer||positivePoints.length===0||busy)return;
                const sequence=++geometrySequence.current;
                setBusy(true);setError('');
                try{
                  const refined=await refineRaster({
                    image_id:imageLayer.id,positive_points:positivePoints,
                    negative_points:negativePoints,
                    box:boxPoints.length===2?boxPoints:null,
                    window_size:traceSettings.window_size,
                  });
                  if(sequence!==geometrySequence.current)return;
                  setGeometry(refined.geometry);
                  lastValid.current=structuredClone(refined.geometry);
                  timeline.current.push(refined.geometry);
                  setHistoryPulse(x=>x+1);
                  setMeasurement(refined.measurement);
                  setSelectedFeatureId(null);setEditing(false);setEdgeMoving(false);
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


          <section id="tools-gis" className="panel-section">
            <div className="section-heading"><Layers3 size={16}/><span>Professional GIS tools</span></div>
            <ProfessionalPanel
              key={activeProjectId ?? 'no-project'}
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
            <TerrainWorkbench key={activeProjectId??'no-project'} projectId={activeProjectId} geometry={geometry}
              raster={imageLayer} onPreview={value=>{if(projectCurrent())setExternalFeatures(value);}}
              onSaved={()=>{if(projectCurrent())setRefreshToken(v=>v+1);}}/>
          </section>

          <section id="tools-spatial" className="panel-section">
            <div className="section-heading"><Layers3 size={16}/><span>GIS selection, QA & print layout</span></div>
            <SpatialToolsPanel
              key={activeProjectId ?? 'no-project'}
              projectId={activeProjectId}
              geometry={geometry}
              viewport={viewport}
              selectedIds={spatialSelected}
              onSelected={value=>{if(projectCurrent())setSpatialSelected(value);}}
              boxMode={selectionBoxMode}
              onBoxMode={active=>{
                setSelectionBoxMode(active);
                if(active){
                  setDrawingMode(null);setEditing(false);setEdgeMoving(false);
                  setMoving(false);setTraceMode(false);setPromptMode(null);
                  setPendingAnnotation(null);
                }
              }}
              box={selectionBox}
              onBox={value=>{if(projectCurrent())setSelectionBox(value);}}
              onIssues={value=>{if(projectCurrent())setQualityIssues(value);}}
              onOpen={id=>{
                const item=projectWorkspace?.features.find(f=>f.id===id);
                if(item)openStoredFeature(item);
              }}
            />
          </section>

          <section id="tools-style" className="panel-section">
            <div className="section-heading"><Layers3 size={16}/><span>Advanced cartography & EPSG</span></div>
            <CartographyProPanel
              key={activeProjectId ?? 'no-project'}
              projectId={activeProjectId}
              workspace={projectWorkspace}
              viewport={viewport}
              selectedGeometry={geometry}
              onChanged={()=>setRefreshToken(v=>v+1)}
              onGrid={value=>{if(projectCurrent())setProjectGrid(value);}}
              labelMoveMode={labelMoveMode}
              onLabelMoveMode={active=>{
                setLabelMoveMode(active);
                if(active){
                  setSelectionBoxMode(false);setTraceMode(false);
                  setDrawingMode(null);setEditing(false);setEdgeMoving(false);setMoving(false);
                  setPromptMode(null);setPendingAnnotation(null);
                }
              }}
            />
          </section>

          <section id="tools-services" className="panel-section">
            <div className="section-heading"><Layers3 size={16}/><span>OGC, indexed stores & background jobs</span></div>
            <DataServicesPanel
              key={activeProjectId ?? 'no-project'}
              projectId={activeProjectId}
              viewport={viewport}
              drawnGeometry={geometry}
              onTiles={value=>{if(projectCurrent())setExternalTiles(value);}}
              onPreview={value=>{if(projectCurrent())setExternalFeatures(value);}}
              onPage={value=>{if(projectCurrent())setPagedFeatures(value);}}
              onRefresh={()=>setRefreshToken(value=>value+1)}
            />
          </section>


          <section id="tools-ai" className="panel-section">
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


            <ApiAccessPanel/>
          </div>
        </aside>
      </div>
      <footer className="gis-status" role="status">
        <span>{error?<span className="error">{error}</span>:busy?'Processing…':message}</span>
        <span>{drawingMode?'Draw · '+drawingMode:editing?(moving?'Move feature':edgeMoving?'Move edge':'Edit vertices'):'Select / pan'} · WGS84</span>
      </footer>
    </div>
  );
}
