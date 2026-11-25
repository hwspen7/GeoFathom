import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import {createPortal} from 'react-dom';
import {
  ArrowRight, Compass, Globe2, Layers3, MapPin, Maximize2, Minimize2,
  Pencil, RotateCcw, Search, Send, Sparkles,
  Wifi, WifiOff,
} from 'lucide-react';

import {
  getCapabilities,checkReady,backendUnavailable, interpret, measureGeometry, searchPlaces,
  type Capabilities, type Measurement, type Place,
} from './api';
import MapCanvas, { type FocusPoint } from './MapCanvas';
import BoundaryEditor from './BoundaryEditor';
import ComputingResources from './ComputingResources';
import {loadDisplay,saveDisplay,areaText,distanceText,type AreaUnit} from './displaySettings';
import {BASEMAPS,BASEMAP_GROUPS,basemapAvailable,customBasemap,defaultCustom,mapTilerImagery,type BasemapId,type CustomBasemap} from './basemaps';
import {ScratchHistory} from './scratchHistory';
import {addRaster,changeRaster,selectDEM,hideDEMs,type RasterLayerView} from './rasterLayers';
import {terrainContainsCenter,terrainGeometryBounds,terrainRasterFitsStudyArea} from './terrainSource';
import {PIN_LIMIT,readPinnedPlaces,writePinnedPlaces,pinPlace,unpinPlace,visibleGeometry} from './pinnedPlaces';
import {studyParcels,suggestedParcel,parcelAt} from './studyArea';
import {localMeasurement,localShape,readScratch,writeScratch,SCRATCH_LIMIT,OFFLINE_METHOD,type ScratchFeature} from './scratch';
import SurveyTools from './SurveyTools';
import {sketchAddError,sketchFinishError,closedLineAsPolygon} from './sketch';
import ProfessionalPanel from './ProfessionalPanel';
import TerrainWorkbench from './TerrainWorkbench';
import {WorkspaceModuleBar,WorkspaceCommandPalette,WorkspaceDockHeading,
  WORKSPACE_MODULES,type WorkspaceCommand} from './WorkspaceChrome';
import GeometryAnalysis from './GeometryAnalysis';
import SpatialToolsPanel from './SpatialToolsPanel';
import CartographyProPanel from './CartographyProPanel';
import type {ExternalTile} from './DataServicesPanel';
import DataWorkbench from './DataWorkbench';
import ExportWorkbench from './ExportWorkbench';
import { featureColor, legendEntries, DEFAULT_LAYER_STYLE } from './labels';
import ImageCorrectionPanel, { type PromptMode } from './ImageCorrectionPanel';
import {
  GeometryTimeline, approximateMeasurement, previewEdgeLengths, pathsOf, drawingPreview,
  singleMovedVertex,moveVertex,removeVertex,type GeometryPath, type Position, type ShapeMode,
} from './editing';
import DiscoveryPanel from './DiscoveryPanel';
import type { DiscoveryResponse, GeoWorkspace, WorkspaceFeature, QualityIssue } from './api';
import ProjectsPanel from './ProjectsPanel';
import ModelControls from './ModelControls';
import RasterPanel, { type TraceSettings } from './RasterPanel';
import GeoAIAnalysisPanel from './GeoAIAnalysisPanel';
import {
  addMapAnnotation, applyOverlay, applyTopology, constructGeometry, editPair, getWorkspace, moveMeasured,
  previewTopology, refineRaster, traceExisting, traceImagery,
  updateProjectFeature,
  type SharedTopologyPreview, type RasterAsset, type TerrainRasterLayer,
  polygonizeNetwork,type NetworkPolygonization,type NetworkFace,
} from './api';

const number = (value: number, digits = 2) =>
  new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(value);

export default function App() {
  const [locationInput, setLocationInput] = useState('');
  const [prompt, setPrompt] = useState('');
  const [candidates, setCandidates] = useState<Place[]>([]);
  const [selectedPlace, setSelectedPlace] = useState<Place | null>(null);
  const [geometry, setGeometry] = useState<GeoJSON.Geometry | null>(null);
  const [selectedParcel,setSelectedParcel]=useState<number|'all'>('all');
  const [selectedBoundaryNode,setSelectedBoundaryNode]=useState<GeometryPath|null>(null);
  const scratchScope=useRef<string|null>(null);
  const [pins,setPins]=useState(()=>({scope:null as string|null,places:readPinnedPlaces(null)}));
  const [pinStorageError,setPinStorageError]=useState(false);
  const pinnedPlaces=pins.places;
  function retainPlace(place:Place){
    const scope=scratchScope.current;
    setPins(old=>({scope,places:pinPlace(old.scope===scope?old.places:readPinnedPlaces(scope),place)}));
  }
  function removePinnedPlace(id:string){
    setPins(old=>({...old,places:unpinPlace(old.places,id)}));
    if(selectedPlace?.id===id){
      // Removing the selected reference must not delete an independently drawn
      // profile line or any other local/saved project feature.
      geometrySequence.current++;
      setSelectedPlace(null);setGeometry(null);setMeasurement(null);
      setSelectedBoundaryNode(null);setSelectedParcel('all');
      lastValid.current=null;timeline.current=new GeometryTimeline();
      setHistoryPulse(v=>v+1);
      setError('');setMessage('Retained location removed. Other drawings are unchanged.');
    }
  }
  const [scratchDocument,setScratchDocument]=useState(()=>({scope:null as string|null,features:readScratch()}));
  const scratch=scratchDocument.features;
  const scratchHistory=useRef<ScratchHistory|null>(null);
  if(!scratchHistory.current)scratchHistory.current=new ScratchHistory(scratch);
  function setScratchState(features:ScratchFeature[]){
    setScratchDocument({scope:scratchScope.current,features});
  }
  function setScratch(update:(old:ScratchFeature[])=>ScratchFeature[]){
    setScratchState(scratchHistory.current!.change(update));
  }
  const [scratchId,setScratchId]=useState<string|null>(null);
  const [scratchStorageError,setScratchStorageError]=useState(false);
  const [measurement, setMeasurement] = useState<Measurement | null>(null);
  const [drawingMode, setDrawingMode] = useState<ShapeMode>(null);
  const [vertices, setVertices] = useState<Position[]>([]);
  const [vertexRedo,setVertexRedo]=useState<Position[]>([]);
  // MapLibre may dispatch click/dblclick before React paints the previous
  // vertex. Keep an immediately updated authoritative sketch for Finish.
  const drawingVerticesRef=useRef<Position[]>(vertices);
  const drawingCommit=useRef<number|null>(null);
  drawingVerticesRef.current=vertices;
  function setSketchVertices(next:Position[]){
    drawingVerticesRef.current=next;
    setVertices(next);
  }
  const [viewport, setViewport] = useState<[number, number, number, number] | null>(null);
  const [discovered, setDiscovered] = useState<Place[]>([]);
  const [focus, setFocus] = useState<FocusPoint | null>(null);
  const [message, setMessage] = useState('Search a place or draw a shape directly on the map.');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [connectionError,setConnectionError]=useState('');
  const [connectionRetry,setConnectionRetry]=useState(0);
  const [assistantQuery, setAssistantQuery] = useState('');
  const [modelId, setModelId] = useState('local-saluki');
  const [modelUsed, setModelUsed] = useState<boolean | null>(null);
  const [toolSteps, setToolSteps] = useState<string[]>([]);
  const [basemap,setBasemap]=useState<BasemapId>('street');
  const [custom,setCustom]=useState<CustomBasemap|null>(defaultCustom);
  const [tileURL,setTileURL]=useState(''),[tileCredit,setTileCredit]=useState(''),[tileZoom,setTileZoom]=useState(20);
  const [tileError,setTileError]=useState('');
  const [mapStatus,setMapStatus]=useState('Loading map');
  const [toolbarTarget,setToolbarTarget]=useState<HTMLDivElement|null>(null);
  const [showTools,setShowTools]=useState(true);
  const [resultsTarget,setResultsTarget]=useState<HTMLDivElement|null>(null);
  const [projectToolbarTarget,setProjectToolbarTarget]=useState<HTMLDivElement|null>(null);
  const [projectActionsTarget,setProjectActionsTarget]=useState<HTMLDivElement|null>(null);
  const [terrainExportTarget,setTerrainExportTarget]=useState<HTMLDivElement|null>(null);
  const [objectTreeTarget,setObjectTreeTarget]=useState<HTMLDivElement|null>(null);
  const [objectsOpen,setObjectsOpen]=useState(true);
  const [shortcutHelp,setShortcutHelp]=useState(false);
  const [commandOpen,setCommandOpen]=useState(false);
  const [contextMenu,setContextMenu]=useState<{x:number;y:number}|null>(null);
  const [activeTool,setActiveTool]=useState('tools-survey');
  const [terrainFeatures,setTerrainFeatures]=useState<GeoJSON.Feature[]>([]);
  const [terrainRasters,setTerrainRasters]=useState<TerrainRasterLayer[]>([]);
  const [terrainFetchTarget,setTerrainFetchTarget]=useState<[number,number,number,number]|null>(null);
  // A profile line is an independent analysis input, never the selected airport polygon.
  const [terrainProfileLine,setTerrainProfileLine]=useState<GeoJSON.LineString|null>(null);
  const [terrainLineDrawing,setTerrainLineDrawing]=useState(false);
  const [terrainVisible,setTerrainVisible]=useState(true);
  const [showLayers,setShowLayers]=useState(false);
  // Keep project management, map layers and place discovery on independent fixed pages.
  const [drawerTab,setDrawerTab]=useState<'project'|'layers'|'search'>('project');
  const [scratchPage,setScratchPage]=useState(0);
  const [pinPage,setPinPage]=useState(0);
  const [candidatePage,setCandidatePage]=useState(0);
  const scratchSize=6,pinSize=5,candidateSize=5;
  useEffect(()=>setScratchPage(page=>Math.min(page,Math.max(0,Math.ceil(scratch.length/scratchSize)-1))),[scratch.length]);
  useEffect(()=>setPinPage(page=>Math.min(page,Math.max(0,Math.ceil(pinnedPlaces.length/pinSize)-1))),[pinnedPlaces.length]);
  useEffect(()=>setCandidatePage(0),[candidates]);
  // Fixed-size workbench docks: map takes all remaining viewport width.
  // No draggable splitters, scrolling side panels, or stored widths.
  // Exceptional long controls open as an expanded workspace, not as a scrolling sidebar.
  const [expandedDock,setExpandedDock]=useState<'operations'|'results'|'project'|null>(null);
  useEffect(()=>{
    if(!expandedDock)return;
    const onKey=(event:KeyboardEvent)=>{if(event.key==='Escape')setExpandedDock(null);};
    document.addEventListener('keydown',onKey);
    return()=>document.removeEventListener('keydown',onKey);
  },[expandedDock]);
  const [operationsFooterTarget,setOperationsFooterTarget]=useState<HTMLDivElement|null>(null);
  const [resultsFooterTarget,setResultsFooterTarget]=useState<HTMLDivElement|null>(null);
  const [terrainPicking,setTerrainPicking]=useState(false);
  const [terrainOrigin,setTerrainOrigin]=useState<Position|null>(null);
  const [terrainHover,setTerrainHover]=useState<Position|null>(null);
  const [terrainProfileSamples,setTerrainProfileSamples]=useState<import('./TerrainCharts').ProfileSample[]>([]);
  const [terrainProfileMapIndex,setTerrainProfileMapIndex]=useState<number|null>(null);
  const [display,setDisplay]=useState(loadDisplay);
  const showMeasurements=display.dimensions;
  const setShowMeasurements=(value:boolean)=>setDisplay(old=>({...old,dimensions:value}));
  const [mapTilerKey,setMapTilerKey]=useState('');
  useEffect(()=>saveDisplay(display),[display]);
  const [rasterLayers,setRasterLayers]=useState<RasterLayerView[]>([]);
  const [imageLayer,setImageLayer]=useState<RasterAsset|null>(null);
  const [demLayer,setDemLayer]=useState<RasterAsset|null>(null);
  const [extentMode,setExtentMode]=useState(false);
  const [extentGeometry,setExtentGeometry]=useState<GeoJSON.Polygon|null>(null);
  const rasterScopes=useRef(new Map<string,{layers:RasterLayerView[];image:RasterAsset|null;dem:RasterAsset|null}>());
  const selectedRaster=imageLayer??demLayer;
  const setRasterVisible=(visible:boolean)=>{if(selectedRaster)setRasterLayers(old=>changeRaster(old,selectedRaster.id,{visible}));};
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
  // The legend is visible in ordinary map and survey workflows.
  // Geometry editing temporarily hides it so top-right vertex handles
  // cannot be intercepted by the floating overlay.
  const [showLegend,setShowLegend] = useState(true);
  const [selectionBoxMode,setSelectionBoxMode]=useState(false);
  const [selectionBox,setSelectionBox]=useState<[number,number,number,number]|null>(null);
  const [spatialSelected,setSpatialSelected]=useState<string[]>([]);
  const [qualityIssues,setQualityIssues]=useState<QualityIssue[]>([]);
  const [projectGrid,setProjectGrid]=useState<GeoJSON.FeatureCollection|null>(null);
  const [labelMoveMode,setLabelMoveMode]=useState(false);
  const [externalTiles,setExternalTiles]=useState<ExternalTile[]>([]);
  const [externalFeatures,setExternalFeatures]=useState<GeoJSON.Geometry[]>([]);
  const [networkAreas,setNetworkAreas]=useState<NetworkPolygonization|null>(null);
  const [networkNotice,setNetworkNotice]=useState('');
  const [networkPage,setNetworkPage]=useState(0);
  useEffect(()=>setNetworkPage(0),[networkAreas?.count,networkAreas?.area_m2]);
  const networkTicket=useRef(0);
  const networkTolerance=useRef(1);
  const networkMinimumArea=useRef(.01);
  const [pagedFeatures,setPagedFeatures]=useState<WorkspaceFeature[]>([]);
  const [linked,setLinked] = useState(false);
  const [pendingShared,setPendingShared] = useState<{
    preview:SharedTopologyPreview;old:[number,number];next:[number,number];
  }|null>(null);
  const [preview, setPreview] = useState<ReturnType<typeof approximateMeasurement> | null>(null);
  const areaUnit=display.area;
  const setAreaUnit=(value:AreaUnit)=>setDisplay(old=>({...old,area:value}));
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

  // Source geometries remain authoritative. A polygonized face is a derived
  // overlay, never automatically inserted back into its source network.
  const networkSources=useMemo(()=>{
    const sources:GeoJSON.Geometry[]=[];
    for(const item of scratch){
      if(item.visible&&item.properties?.source_type!=='polygonized_network'&&
         ['Polygon','MultiPolygon','LineString','MultiLineString'].includes(item.geometry.type))
        sources.push(item.geometry);
    }
    for(const item of projectWorkspace?.features??[]){
      if(item.properties?.source_type==='polygonized_network')continue;
      if(!projectWorkspace?.layers.find(layer=>layer.id===item.layer_id)?.visible)continue;
      if(['Polygon','MultiPolygon','LineString','MultiLineString'].includes(item.geometry.type))
        sources.push(item.geometry);
    }
    if(geometry&&featureProperties.source_type!=='polygonized_network'&&
      ['Polygon','MultiPolygon','LineString','MultiLineString'].includes(geometry.type)&&
       !sources.some(item=>JSON.stringify(item)===JSON.stringify(geometry)))
      sources.push(geometry);
    return sources;
  },[scratch,projectWorkspace,geometry,featureProperties.source_type]);

  async function rebuildNetwork(tolerance=networkTolerance.current,
                                minArea=networkMinimumArea.current){
    networkTolerance.current=tolerance;networkMinimumArea.current=minArea;
    const ticket=++networkTicket.current;
    if(networkSources.length===0){setNetworkAreas(null);setNetworkNotice('Draw connected lines first.');return;}
    if(networkSources.length>300){
      setNetworkAreas(null);setNetworkNotice('Network exceeds the 300-source limit. Subdivide it.');
      return;
    }
    try{
      const result=await polygonizeNetwork(networkSources,tolerance,minArea);
      if(ticket!==networkTicket.current)return;
      setNetworkAreas(result);
      setNetworkNotice(result.count?
        result.count+' independently measured enclosed area'+(result.count===1?'':'s')+'.':
        'No enclosed areas yet. Join line endpoints or increase the snap tolerance.');
    }catch(error){
      if(ticket!==networkTicket.current)return;
      setNetworkAreas(null);
      setNetworkNotice(error instanceof Error?error.message:String(error));
      throw error;
    }
  }
  useEffect(()=>{
    // Rebuild on committed vector edits; never run while actively drawing,
    // and cancel stale derived areas after project/source changes.
    networkTicket.current++;
    if(drawingMode||!capabilities||!networkSources.length){
      setNetworkAreas(null);
      return;
    }
    const timer=window.setTimeout(()=>{void rebuildNetwork().catch(()=>{});},300);
    return()=>window.clearTimeout(timer);
  },[networkSources,drawingMode,capabilities,activeProjectId]);

  function keepNetworkAreas(faces:NetworkFace[]){
    if(!faces.length)return;
    const existing=scratchHistory.current!.current.filter(
      item=>item.properties?.source_type==='polygonized_network');
    const missing=faces.filter(face=>!existing.some(item=>
      JSON.stringify(item.geometry)===JSON.stringify(face.geometry)));
    if(!missing.length){setMessage('All these enclosed areas already exist locally.');return;}
    if(scratchHistory.current!.current.length+missing.length>SCRATCH_LIMIT){
      setError('Too many local drawings. Save or delete sources before keeping enclosed areas.');return;
    }
    const saved=missing.map(face=>({
      id:'scratch-'+crypto.randomUUID(),name:face.name,
      geometry:structuredClone(face.geometry),measurement:face.measurement,visible:true,
      source:'GEOS line-network polygonization',properties:{...face.properties},
    } satisfies ScratchFeature));
    setScratch(old=>[...old,...saved]);
    setMessage('Kept '+saved.length+' independent closed areas; the original lines are unchanged.');
  }


  function activateNetworkFace(id:string){
    const face=networkAreas?.faces.find(item=>item.id===id);
    if(!face||drawingMode||busy)return;
    // Real GEOS polygon and ellipsoidal measurement, retained locally only
    // when the user selects the face; never rewrite connected source lines.
    const existing=scratchHistory.current!.current.find(item=>
      item.properties?.source_type==='polygonized_network'&&
      JSON.stringify(item.geometry)===JSON.stringify(face.geometry));
    if(!existing&&scratchHistory.current!.current.length>=SCRATCH_LIMIT){
      setError('Local feature limit reached. Save or remove unused drawings before selecting an enclosed area.');
      return;
    }
    const selected=existing??({
      id:'scratch-'+crypto.randomUUID(),name:face.name,
      geometry:structuredClone(face.geometry),measurement:face.measurement,
      visible:true,source:'GEOS line-network polygonization',
      properties:{...face.properties},
    } satisfies ScratchFeature);
    if(!existing)setScratch(old=>[...old,selected]);
    selectScratch(selected,false);
    setMessage(face.name+' · closed polygon selected with area and perimeter. Original lines preserved.');
  }

  useEffect(()=>{setScratchStorageError(!writeScratch(scratchDocument.features,scratchDocument.scope));},[scratchDocument]);
  useEffect(()=>{setPinStorageError(!writePinnedPlaces(pins.scope,pins.places));},[pins]);

  function storeScratch(next:GeoJSON.Geometry,measured:Measurement,id:string|null=scratchId,metadata?:{source:string;properties:Record<string,unknown>;name?:string}){
    const key=id??'scratch-'+crypto.randomUUID();
    if(!scratchHistory.current!.current.some(f=>f.id===key)&&scratchHistory.current!.current.length>=SCRATCH_LIMIT)throw Error('Local feature limit reached. Save or export your drawings first.');
    setScratchId(key);
    setScratch(old=>{
      const found=old.find(f=>f.id===key);
      const item:ScratchFeature={id:key,name:metadata?.name??found?.name??next.type+' '+(old.length+1),geometry:structuredClone(next),measurement:measured,visible:true,
        source:metadata?.source??found?.source??geometrySource,properties:metadata?.properties??found?.properties??featureProperties};
      return found?old.map(f=>f.id===key?item:f):[...old,item];
    });
  }
  function selectScratch(item:ScratchFeature,zoom=true){
    setExtentMode(false);setSelectedBoundaryNode(null);setSelectedParcel('all');
    geometrySequence.current++;setBusy(false);setScratchId(item.id);setSelectedFeatureId(null);featureIdentity.current=null;
    timeline.current=new GeometryTimeline();timeline.current.push(item.geometry);setHistoryPulse(v=>v+1);
    lastValid.current=structuredClone(item.geometry);setGeometry(item.geometry);setMeasurement(item.measurement);
    setGeometrySource(item.source||'Local scratch');setFeatureProperties(item.properties??{source_type:'user_drawn',draft_name:item.name});
    setPreview(null);setPendingShared(null);setLinked(false);setDrawingMode(null);setVertices([]);setTerrainPicking(false);
    setEditing(false);setEdgeMoving(false);setMoving(false);setTraceMode(false);setPromptMode(null);
    setSelectionBoxMode(false);setLabelMoveMode(false);setPendingAnnotation(null);
    setSelectedPlace(null);setSplitParts([]);setError('');setMessage('Selected '+item.name);
    if(zoom){const [west,south,east,north]=item.measurement.bounds;setFocus({longitude:(west+east)/2,latitude:(south+north)/2,bbox:[west,south,east,north],key:Date.now()});}
  }

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
      if(detached||!selectedFeatureId)storeScratch(next,checked,detached?null:scratchId,
        selectedPlace&&!detached?{
          source:'Edited mapped boundary (local copy)',
          name:selectedPlace.name+' · edited study area',
          properties:{source_type:'user_edited_osm_copy',original_place_id:selectedPlace.id},
        }:undefined);
      if(selectedPlace&&!detached&&!selectedFeatureId){
        // Source OSM reference remains pinned unchanged. All vertex edits are
        // committed into an independent local feature and can be reversed.
        setSelectedPlace(null);setSelectedParcel('all');
        setGeometrySource('Edited mapped boundary (local copy)');
        setFeatureProperties({source_type:'user_edited_osm_copy',original_place_id:selectedPlace.id});
      }
      if(detached){setSelectedFeatureId(null);featureIdentity.current=null;setSelectedPlace(null);setPendingShared(null);setLinked(false);}
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
      if((detached||!selectedFeatureId)&&backendUnavailable(failure)){
        try{
          const local=localMeasurement(next);
          storeScratch(next,local,detached?null:scratchId,selectedPlace&&!detached?{
            source:'Edited mapped boundary (local copy)',
            name:selectedPlace.name+' · edited study area',
            properties:{source_type:'user_edited_osm_copy',original_place_id:selectedPlace.id},
          }:undefined);
          if(selectedPlace&&!detached){setSelectedPlace(null);setSelectedParcel('all');}
          setGeometry(next);setMeasurement(local);
          lastValid.current=structuredClone(next);timeline.current.push(next);setHistoryPulse(v=>v+1);
          setPreview(null);setError('');setMessage('Local edit completed · approximate measurement, backend offline.');
          return;
        }catch(localError){setError(String(localError));}
      }else setError(failure instanceof Error ? failure.message : 'Invalid geometry.');
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
    if(!next&&scratchId)setScratch(old=>old.filter(item=>item.id!==scratchId));
    if(next)void measureGeometry(next).then(value=>{
      if(sequence===geometrySequence.current){setMeasurement(value);if(scratchId)storeScratch(next,value,scratchId);}
    }).catch(failure=>{
      if(sequence!==geometrySequence.current)return;
      if(scratchId&&backendUnavailable(failure))try{
        const value=localMeasurement(next);setMeasurement(value);storeScratch(next,value,scratchId);
      }catch{setMeasurement(null);}
      else setMeasurement(null);
    });
  }

  function openStoredFeature(feature: WorkspaceFeature) {
    // A callback from a previous project may finish after navigation.
    if (feature.project_id !== projectIdentity.current) return;
    setExtentMode(false);
    geometrySequence.current++;setBusy(false);setTerrainPicking(false);setTraceMode(false);setPromptMode(null);
    setPendingAnnotation(null);setSelectionBoxMode(false);setLabelMoveMode(false);
    if (featureIdentity.current !== feature.id) {
      timeline.current = new GeometryTimeline(feature.geometry);
      setLinked(false);
    }
    featureIdentity.current = feature.id;
    setScratchId(null);setPreview(null);setVertices([]);setPendingShared(null);
    setGeometry(feature.geometry);setSelectedBoundaryNode(null);setSelectedParcel('all');
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

  function revealPanel(id:string){
    if(drawingMode&&vertices.length&&id!==activeTool){
      setError('Finish or cancel the current drawing before switching tools. Your selected area is retained.');
      return;
    }
    setShowTools(true);setActiveTool(id);if(id!=='tools-terrain'){setTerrainPicking(false);setTerrainHover(null);}
    setObjectsOpen(id!=='tools-terrain');
    // Tool activation, including keyboard shortcuts, dismisses the transient
    // drawer so it cannot intercept input intended for the operations dock.
    // Its project/search state stays mounted and the selected place is retained.
    setShowLayers(false);setExpandedDock(null);
    // Only scroll the inspector's own pane. scrollIntoView also scrolls
    // the outer document and can move the central map off-screen when a
    // long Terrain chart is active.
    requestAnimationFrame(()=>{
      const scroll=document.querySelector<HTMLElement>('.gis-inspector .sidebar-scroll');
      if(scroll)scroll.scrollTop=0;
    });
  }

  useEffect(()=>{
    let cancelled=false;
    void Promise.all([checkReady(),getCapabilities()]).then(([,value])=>{
      if(!cancelled){setCapabilities(value);setConnectionError('');setRefreshToken(v=>v+1);}
    }).catch(error=>{
      if(!cancelled){setCapabilities(null);setConnectionError(error instanceof Error?error.message:String(error));}
    });
    return()=>{cancelled=true;};
  },[connectionRetry]);

  async function selectPlace(place: Place) {
    if(pinnedPlaces.length>=PIN_LIMIT&&!pinnedPlaces.some(item=>item.id===place.id)){
      setError('Retained location limit reached. Remove a pinned place explicitly before adding another.');return;
    }
    const sequence = ++geometrySequence.current;
    retainPlace(place);
    const mapped=place.geometry&&['Polygon','MultiPolygon','LineString','MultiLineString'].includes(place.geometry.type);
    const parcels=studyParcels(place.geometry??null);
    // A geocoder can return a disconnected university MultiPolygon including
    // remote airport/farm sites. Default to its component nearest the place
    // reference, but keep the entire original geometry pinned and selectable.
    const suggested=parcels.length>1?suggestedParcel(place.geometry!,[place.longitude,place.latitude]):null;
    const selectedIndex=suggested??'all';
    const target:GeoJSON.Geometry=(mapped&&(suggested!==null?parcelAt(place.geometry!,suggested):place.geometry))||
      {type:'Point',coordinates:[place.longitude,place.latitude]};
    setSelectedParcel(selectedIndex);setSelectedBoundaryNode(null);
    setSelectedPlace(place);setScratchId(null);setPreview(null);setPendingShared(null);
    // Validate the selected campus parcel, not unrelated properties elsewhere.
    const requestedBounds=terrainGeometryBounds(target);
    const matchesDEM=demLayer&&(requestedBounds?terrainRasterFitsStudyArea(demLayer,requestedBounds):
      terrainContainsCenter(demLayer.bbox,[place.longitude,place.latitude,place.longitude,place.latitude]));
    if(demLayer&&!matchesDEM){
      setDemLayer(null);setRasterLayers(old=>hideDEMs(old));setExtentMode(false);setExtentGeometry(null);
      setTerrainRasters([]);setTerrainFeatures([]);
    }
    timeline.current=new GeometryTimeline();lastValid.current=null;setHistoryPulse(v=>v+1);
    setTerrainPicking(false);setPromptMode(null);setPendingAnnotation(null);setSelectionBoxMode(false);setLabelMoveMode(false);
    setSelectedFeatureId(null);
    setLinked(false);
    setEditing(false);setEdgeMoving(false);
    setMoving(false);
    setSplitParts([]);
    setDrawingMode(null);
    setTraceMode(false);
    setVertices([]);
    // Geocoders may return a point, even for an airport. Never treat a point
    // marker or its search bounding box as a surveyed analysis polygon.
    setGeometry(target);
    setMeasurement(null);
    lastValid.current=structuredClone(target);
    timeline.current.push(target);
    setHistoryPulse(value => value + 1);
    setGeometrySource(place.source);
    setFeatureProperties({ source_type:mapped?'mapped_openstreetmap':'geocoded_location', osm_id: place.osm_id, osm_type: place.osm_type });
    // Geocoding result bboxes can cover unrelated institutional facilities.
    // Center the visible map on the actual selected polygon, not a broad
    // provider-defined search envelope or a distant representative point.
    const realBounds=terrainGeometryBounds(target);
    const focusBounds=realBounds??place.bbox;
    setFocus({
      latitude: focusBounds?(focusBounds[1]+focusBounds[3])/2:place.latitude,
      longitude: focusBounds?(focusBounds[0]+focusBounds[2])/2:place.longitude,
      bbox: focusBounds,
      key: Date.now(),
    });
    if (mapped) {
      try {
        const result = await measureGeometry(target);
        if (sequence !== geometrySequence.current) return;
        setMeasurement(result);
        setMessage(parcels.length>1?
          'Selected nearby mapped parcel '+(Number(selectedIndex)+1)+'/'+parcels.length+
          '. Other disconnected sites remain in retained search results.':
          'Mapped boundary loaded. Check that it represents your intended area.');
      } catch (problem) {
        if (sequence !== geometrySequence.current) return;
        setError(problem instanceof Error ? problem.message : 'Could not measure boundary.');
        setMessage('Place found, but the mapped geometry could not be measured.');
      }
    } else {
      setMessage('Location selected (point only). Terrain can fetch the current map view; draw an area or use DEM extent for area analysis.');
    }
    if(sequence===geometrySequence.current)setBusy(false);
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
      if (found.length===1) {
        await selectPlace(found[0]);
      } else if(found.length>1){
        // A first search hit is not necessarily the requested airport.
        setMessage('Multiple candidates found. Select the intended location from search results.');
      } else {
        setMessage('No place found. Try a different spelling or draw directly on the map.');
      }
    } catch (problem) {
      if(sequence===geometrySequence.current)setError(problem instanceof Error ? problem.message : 'Search failed.');
    } finally {
      if(sequence===geometrySequence.current)setBusy(false);
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
      } else {
        setDiscovered([]);
        if (answer.results.length===1) await selectPlace(answer.results[0]);
        if (answer.results.length > 1) setMessage(answer.message + ' Select the correct candidate.');
      }
    } catch (problem) {
      if(sequence===geometrySequence.current)setError(problem instanceof Error ? problem.message : 'Assistant request failed.');
    } finally {
      if(sequence===geometrySequence.current)setBusy(false);
    }
  }

  async function chooseSelectedParcel(value:number|'all'){
    if(!selectedPlace?.geometry||busy)return;
    const next=parcelAt(selectedPlace.geometry,value);
    if(!next)return;
    const ticket=++geometrySequence.current;
    setSelectedParcel(value);setSelectedBoundaryNode(null);
    setEditing(false);setMoving(false);setEdgeMoving(false);setExtentMode(false);
    setGeometry(next);setMeasurement(null);setPreview(null);setError('');
    lastValid.current=structuredClone(next);
    timeline.current=new GeometryTimeline();timeline.current.push(next);setHistoryPulse(v=>v+1);
    // Previously acquired multi-site DEM remains in the library but must not
    // obscure a newly chosen connected campus analysis parcel.
    setDemLayer(null);setRasterLayers(old=>hideDEMs(old));
    setTerrainRasters([]);setTerrainFeatures([]);
    const bounds=terrainGeometryBounds(next);
    if(bounds){const [w,s,e,n]=bounds;
      setFocus({longitude:(w+e)/2,latitude:(s+n)/2,bbox:bounds,key:Date.now()});}
    try{
      const checked=await measureGeometry(next);
      if(ticket!==geometrySequence.current)return;
      setMeasurement(checked);
      setMessage(value==='all'?'Full mapped place selected (including detached sites).':
        'Connected campus parcel selected. DEM target now follows this parcel.');
    }catch(err){if(ticket===geometrySequence.current)setError(err instanceof Error?err.message:String(err));}
  }

  // Undo/Redo while sketching operate on the pending coordinates, not the
  // previously selected geometry's history. A new click clears redo.
  function undoSketchPoint(){
    if(!drawingMode||!vertices.length||busy)return;
    const current=drawingVerticesRef.current;
    setVertexRedo(old=>[current[current.length-1],...old]);
    setSketchVertices(current.slice(0,-1));setError('');
  }
  function redoSketchPoint(){
    if(!drawingMode||!vertexRedo.length||busy)return;
    const next=vertexRedo[0];
    const current=drawingVerticesRef.current;
    const reason=sketchAddError(drawingMode,current,next);
    if(reason){setError(reason);return;}
    setSketchVertices([...current,next]);setVertexRedo(old=>old.slice(1));setError('');
  }

  function startTerrainLine(){
    if(busy)return;
    if(drawingMode&&vertices.length){setError('Finish or cancel the current sketch before starting a profile line.');return;}
    // Deliberately retain geometry, measurement, selectedPlace, search candidates,
    // scratch selection and all existing map layers.
    geometrySequence.current++;
    setTerrainLineDrawing(true);
    setDrawingMode('line');setVertices([]);setVertexRedo([]);
    setEditing(false);setMoving(false);setEdgeMoving(false);
    setTerrainPicking(false);setTerrainHover(null);setTraceMode(false);
    setPromptMode(null);setPendingAnnotation(null);setSelectionBoxMode(false);setLabelMoveMode(false);
    setExtentMode(false);setExtentGeometry(null);
    setError('');
    setMessage('Draw a terrain profile line. The selected location and study area stay in place.');
  }

  function startDrawing(next: Exclude<ShapeMode, null>) {
    if(drawingMode===next){stopInteraction();return;}
    if(busy)return;
    if(drawingMode&&vertices.length){setError('Finish or cancel the existing sketch before starting another.');return;}
    if(!['hole','split'].includes(next)&&scratch.length>=SCRATCH_LIMIT){setError('Local drawing limit reached. Save or export drawings and remove unused ones.');return;}
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
    setTerrainLineDrawing(false);
    setDrawingMode(next);setEdgeMoving(false);setTerrainPicking(false);setTerrainHover(null);setExtentMode(false);
    setTraceMode(false);
    setPromptMode(null);setPendingAnnotation(null);setSelectionBoxMode(false);setLabelMoveMode(false);
    if (!operation) {
      setLinked(false);
      setPendingShared(null);
      // Do not overwrite the selected area's metadata while an independent
      // sketch is still being drawn. The new geometry takes focus at Finish.
    }
    setVertices([]);setVertexRedo([]);
    // Existing selection and search candidates are stable through drawing.
    // Only a successful Finish may select the new independent feature.
    setEditing(false);setEdgeMoving(false);
    setMoving(false);
    setError('');
    setMessage(next==='point'?'Click a location to create a point.':
      ['polygon','hole'].includes(next)?
        'Click vertices, then click the green first vertex, double-click or press Enter to close. Esc cancels; Backspace undoes.':
        next==='line'||next==='split'?'Click vertices, then double-click or press Enter to finish.':
        'Click the required points to complete the shape.');
  }

  async function finishDrawing(points:Position[]=drawingVerticesRef.current) {
    if (!drawingMode||busy||drawingCommit.current===geometrySequence.current) return;
    const mode = drawingMode;
    // Reject self-crossings, degenerate rings and repeated non-closing nodes
    // before calling GIS APIs or creating approximate offline geometry.
    const sketchError=sketchFinishError(mode,points);
    if(sketchError){setError(sketchError);return;}
    if(terrainLineDrawing){
      if(mode!=='line'||points.length<2){setError('Place at least two profile line points.');return;}
      const line:GeoJSON.LineString={type:'LineString',coordinates:points};
      const ticket=++geometrySequence.current;drawingCommit.current=ticket;setBusy(true);setError('');
      try{
        // This measurement validates the path without replacing the original selection.
        await measureGeometry(line);
        if(ticket!==geometrySequence.current)return;
        setTerrainProfileLine(line);setTerrainLineDrawing(false);
        setDrawingMode(null);setVertices([]);
        setMessage('Profile line ready. Your selected study area remains unchanged.');
      }catch(failure){
        if(ticket!==geometrySequence.current)return;
        if(backendUnavailable(failure)){
          setTerrainProfileLine(line);setTerrainLineDrawing(false);setDrawingMode(null);setVertices([]);
          setMessage('Profile line saved locally; connect the API before running terrain analysis.');
        }else setError(failure instanceof Error?failure.message:'Invalid profile line.');
      }finally{if(drawingCommit.current===ticket)drawingCommit.current=null;if(ticket===geometrySequence.current)setBusy(false);}
      return;
    }
    const required = mode==='point'?1:['polygon','hole'].includes(mode) ? 3 : 2;
    if (points.length < required) {
      setError('Add more points before finishing.');
      return;
    }
    const sequence=++geometrySequence.current;
    drawingCommit.current=sequence;
    setBusy(true); setError('');
    try {
      let result: GeoJSON.Geometry;
      let measured: Measurement;
      if(mode==='point'){
        result={type:'Point',coordinates:points[0]};
        measured=await measureGeometry(result);
      }else if (mode === 'trace-along') {
        const paths=(projectWorkspace?.features ?? [])
          .filter(feature=>feature.geometry.type==='LineString'||feature.geometry.type==='MultiLineString')
          .flatMap(feature=>pathsOf(feature.geometry));
        const traced=await traceExisting(points[0],points[1],paths);
        if(sequence!==geometrySequence.current)return;
        result=traced.geometry;
        measured=traced.measurement;
        setSelectedFeatureId(null);
        setGeometrySource('Vector network tracing');
        setFeatureProperties({source_type:'vector_trace',method:'shortest connected path'});
      } else if (mode === 'polygon' || mode === 'rectangle' || mode === 'circle') {
        let constructed;
        if (mode === 'circle') {
          const path = { type: 'LineString', coordinates: points.slice(0,2) } as GeoJSON.LineString;
          const line = await measureGeometry(path);
          constructed = await constructGeometry({
            mode, vertices: points.slice(0,1), radius_m: line.length_m ?? 0,
          });
        } else {
          constructed = await constructGeometry({
            mode, vertices: mode === 'rectangle' ? points.slice(0,2) : points,
          });
        }
        result = constructed.geometry; measured = constructed.measurement;
      } else if (mode === 'line' || mode === 'split') {
        result = (mode==='line'?closedLineAsPolygon(points):null) ??
          {type:'LineString',coordinates:points};
        measured = await measureGeometry(result);
      } else {
        const constructed = await constructGeometry({ mode: 'polygon', vertices:points });
        result = constructed.geometry; measured = constructed.measurement;
      }
      if (mode === 'hole' && geometry) {
        const cut = await editPair('hole',geometry,result);
        result = cut.geometry; measured = cut.measurement;
      } else if (mode === 'split' && geometry) {
        const divided = await editPair('split',geometry,result);
        if(sequence!==geometrySequence.current)return;
        if(!divided.features.length)throw Error('The split did not produce a polygon.');
        const pieces:ScratchFeature[]=divided.features.map((item,index)=>({
          id:'scratch-'+crypto.randomUUID(),name:'Split part '+(index+1),geometry:item.geometry,
          measurement:item.measurement,visible:true,source:geometrySource||'User drawn',
          properties:{...featureProperties,operation:'split'}
        }));
        // Local source replacement is atomic and undoable. A saved source
        // stays intact: the pieces are independent drafts until explicitly saved.
        const prior=scratchHistory.current!.current.filter(f=>f.id!==scratchId);
        if(prior.length+pieces.length>SCRATCH_LIMIT)throw Error('Split exceeds the local feature limit.');
        setScratch(()=>[...prior,...pieces]);setScratchId(pieces[0].id);
        setSplitParts([]);setDiscovered([]);
        result=pieces[0].geometry;measured=pieces[0].measurement;
        setSelectedFeatureId(null);featureIdentity.current=null;
        // The split parts become new local objects; the source reference stays pinned.
        setSelectedPlace(null);
      }
      if(sequence!==geometrySequence.current)return;
      if(mode!=='hole'&&mode!=='split'){
        timeline.current=new GeometryTimeline();
        setSelectedFeatureId(null);featureIdentity.current=null;setSelectedPlace(null);
        setGeometrySource(mode==='trace-along'?'Vector network tracing':'User drawn');
        setFeatureProperties(mode==='trace-along'?{source_type:'vector_trace',method:'shortest connected path'}:
          mode==='line'&&result.type==='Polygon'?{source_type:'user_drawn_region',method:'closed_line'}:{source_type:'user_drawn'});
      }
      if(mode!=='split'&&(!selectedFeatureId||mode!=='hole'))storeScratch(result,measured,mode==='hole'?scratchId:null,
        mode==='hole'?undefined:{source:mode==='trace-along'?'Vector network tracing':'User drawn',
          properties:mode==='trace-along'?{source_type:'vector_trace',method:'shortest connected path'}:
            mode==='line'&&result.type==='Polygon'?{source_type:'user_drawn_region',method:'closed_line'}:{source_type:'user_drawn'}});
      setGeometry(result);
      lastValid.current = structuredClone(result);
      timeline.current.push(result);
      setHistoryPulse(value => value + 1);
      setMeasurement(measured);
      setDrawingMode(null); setVertices([]);setVertexRedo([]); setPreview(null);
      setMessage(mode === 'split'
        ? 'Polygon divided into independent local features. Original saved features are unchanged.'
        : mode==='line'&&result.type==='Polygon'?
          'Closed line converted to a measured region. Area and perimeter are available.':
          'Drawing completed and measured on the WGS84 ellipsoid.');
    } catch (failure) {
      if(sequence!==geometrySequence.current)return;
      if(backendUnavailable(failure)){
        try{
          const closed=mode==='line'?closedLineAsPolygon(points):null;
          const local=closed?{geometry:closed,measurement:localMeasurement(closed)}:localShape(mode,points);
          if(local){
            const isRegion=mode==='line'&&local.geometry.type==='Polygon';
            const properties=isRegion?{source_type:'user_drawn_region',method:'closed_line'}:{source_type:'user_drawn'};
            storeScratch(local.geometry,local.measurement,null,{source:'User drawn',properties});
            setSelectedFeatureId(null);featureIdentity.current=null;setSelectedPlace(null);
            setGeometrySource('User drawn');setFeatureProperties(properties);
            setGeometry(local.geometry);setMeasurement(local.measurement);
            lastValid.current=structuredClone(local.geometry);timeline.current.push(local.geometry);
            setHistoryPulse(v=>v+1);setDrawingMode(null);setVertices([]);setVertexRedo([]);setPreview(null);
            setError('');setMessage(isRegion?'Closed line formed a locally measured region · approximate until API validation.':
              'Drawing completed locally · approximate measurement. Connect API for exact validation.');
            return;
          }
        }catch(error){setError(error instanceof Error?error.message:String(error));return;}
      }
      setError(failure instanceof Error ? failure.message : 'Drawing failed.');
    } finally { if(drawingCommit.current===sequence)drawingCommit.current=null;if(sequence===geometrySequence.current)setBusy(false); }
  }

  async function numericShape(mode: string, body: {
    vertices: Position[]; radius_m?: number; bearing_deg?: number; length_m?: number;
  }) {
    if(drawingMode){setError('Finish or cancel the current sketch before constructing another shape.');return;}
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
      setBusy(false);await commitGeometry(created.geometry,'Precise construction created with PyProj.',true);
    } catch (failure) {
      if(sequence===geometrySequence.current)setError(failure instanceof Error ? failure.message : 'Numeric construction failed.');
    } finally { if(sequence===geometrySequence.current)setBusy(false); }
  }

  async function combineWith(mode: 'union' | 'difference' | 'intersection', featureId: string) {
    if(drawingMode){setError('Finish or cancel the active sketch before combining features.');return;}
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
      setBusy(false);await commitGeometry(result.geometry, 'Spatial ' + mode + ' completed.',true);
    } catch (failure) {
      if(sequence===geometrySequence.current)setError(failure instanceof Error ? failure.message : 'Spatial overlay failed.');
    } finally { if(sequence===geometrySequence.current)setBusy(false); }
  }


  function clearWorkspace() {
    geometrySequence.current++;
    setGeometry(null);setScratchId(null);setBusy(false);setTerrainPicking(false);setTerrainOrigin(null);setTerrainHover(null);
    setTerrainProfileLine(null);setTerrainLineDrawing(false);
    setPendingAnnotation(null);
    setSelectionBoxMode(false);setSelectionBox(null);
    setSpatialSelected([]);setQualityIssues([]);setProjectGrid(null);
    setLabelMoveMode(false);
    setExternalFeatures([]);setTerrainFeatures([]);setTerrainRasters([]);setTerrainFetchTarget(null);setPagedFeatures([]);
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
        measured_using: measurement?.method??'Unverified geometry',
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

  function stopInteraction(){
    geometrySequence.current++;setBusy(false);setTerrainLineDrawing(false);setDrawingMode(null);setSketchVertices([]);setVertexRedo([]);setTerrainPicking(false);
    setEditing(false);setEdgeMoving(false);setMoving(false);setTraceMode(false);setPromptMode(null);
    setSelectionBoxMode(false);setLabelMoveMode(false);setPendingAnnotation(null);setContextMenu(null);
    if(preview||pendingShared){setGeometry(lastValid.current);setPreview(null);setPendingShared(null);}
    setError('');setMessage(drawingMode?'Drawing cancelled. Retained locations are unchanged.':'Select / pan');
  }
  function editMode(mode:'vertices'|'edge'|'move'){
    if(!geometry||selectedLocked||busy||drawingMode)return;
    // The legend is temporarily hidden by the editing state in the map
    // render. Preserve the user's expanded/collapsed preference when editing
    // ends, instead of permanently changing it during an edit transition.
    if(preview||pendingShared){setGeometry(lastValid.current);setPreview(null);setPendingShared(null);}
    geometrySequence.current++;
    setEditing(true);setMoving(mode==='move');setEdgeMoving(mode==='edge');
    if(mode!=='vertices')setLinked(false);
    setTraceMode(false);setPromptMode(null);setTerrainPicking(false);setPendingAnnotation(null);
    setSelectionBoxMode(false);setLabelMoveMode(false);setContextMenu(null);
    setMessage(mode==='move'?'Drag feature':mode==='edge'?'Drag edge midpoint':'Drag vertices · right-click to delete');
  }
  function fitSelection(){
    if(!measurement||preview)return;
    const [west,south,east,north]=measurement.bounds;
    setFocus({longitude:(west+east)/2,latitude:(south+north)/2,bbox:[west,south,east,north],key:Date.now()});
  }
  function deselect(){
    geometrySequence.current++;setBusy(false);setGeometry(null);setMeasurement(null);
    setSelectedBoundaryNode(null);setSelectedParcel('all');
    // Deselect does not delete the independent profile line or retained map references.
    setTerrainLineDrawing(false);
    setScratchId(null);setSelectedFeatureId(null);featureIdentity.current=null;setSelectedPlace(null);
    setDrawingMode(null);setVertices([]);setEditing(false);setMoving(false);setEdgeMoving(false);setLinked(false);
    setPreview(null);setPendingShared(null);setPromptMode(null);setTraceMode(false);setPendingAnnotation(null);
    setTerrainPicking(false);setSelectionBoxMode(false);setLabelMoveMode(false);setSplitParts([]);
    lastValid.current=null;timeline.current=new GeometryTimeline();setHistoryPulse(v=>v+1);
    setGeometrySource('');setFeatureProperties({});setContextMenu(null);setExtentMode(false);setExtentGeometry(null);setError('');
  }
  function historyStep(redo=false){
    if(busy||drawingMode)return;
    if(selectedFeatureId){
      if(selectedLocked)return;
      const history=timeline.current;
      if(redo?history.canRedo:history.canUndo)applyHistory(redo?history.redo():history.undo());
      return;
    }
    const history=scratchHistory.current!;
    if(!(redo?history.canRedo:history.canUndo))return;
    const before=history.current;
    const after=redo?history.redo():history.undo();
    setScratchState(after);
    const changed=after.find(item=>item.visible&&JSON.stringify(before.find(old=>old.id===item.id))!==JSON.stringify(item));
    const selected=after.find(item=>item.id===scratchId&&item.visible);
    if(changed||selected)selectScratch((changed??selected)!,false);
    else deselect();
    setMessage(redo?'Local operation redone.':'Local operation undone.');
  }
  function removeLocal(id:string|null=scratchId){
    if(!id||busy||drawingMode)return;
    setScratch(old=>old.filter(f=>f.id!==id));
    if(id===scratchId)deselect();
    setContextMenu(null);setMessage('Local feature deleted · Ctrl Z to restore.');
  }
  function saveSelection(){
    if(!geometry||busy||drawingMode||preview||pendingShared)return;
    if(activeProjectId){
      const button=document.querySelector<HTMLButtonElement>('[data-project-save]');
      if(button&&!button.disabled){button.click();return;}
    }
    exportGeoJSON();
  }
  useEffect(()=>{
    function commands(event:KeyboardEvent){
      if(event.defaultPrevented||event.isComposing)return;
      const target=event.target;
      if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){
        event.preventDefault();setCommandOpen(v=>!v);return;
      }
      if(event.key==='Escape'){
        event.preventDefault();if(commandOpen){setCommandOpen(false);return;}
        if(shortcutHelp){setShortcutHelp(false);return;}stopInteraction();return;
      }
      if(commandOpen)return;
      if(target instanceof HTMLElement&&(target.isContentEditable||target.closest('input,textarea,select,[contenteditable="true"]')))return;
      if(event.ctrlKey||event.metaKey){
        if(event.key.toLowerCase()==='s'){event.preventDefault();saveSelection();return;}
        if(event.key.toLowerCase()==='z'){
          event.preventDefault();
          if(busy)return;
          if(drawingMode){if(event.shiftKey)redoSketchPoint();else undoSketchPoint();return;}
          historyStep(event.shiftKey);
        }else if(event.key.toLowerCase()==='y'){
          event.preventDefault();if(!busy){if(drawingMode)redoSketchPoint();else historyStep(true);}
        }
        return;
      }
      if(event.altKey||event.repeat)return;
      if(drawingMode&&!busy&&(event.key==='Enter'||event.key==='F2')){
        event.preventDefault();
        if(!drawingVerticesRef.current.length)stopInteraction();else void finishDrawing();
        return;
      }
      if(editing&&(event.key==='Enter'||event.key==='F2')){
        event.preventDefault();stopInteraction();return;
      }
      if(drawingMode&&!busy&&event.key==='Backspace'){
        event.preventDefault();undoSketchPoint();return;
      }
      if(contextMenu&&event.key==='Tab'){setContextMenu(null);return;}
      if(shortcutHelp||busy)return;
      const key=event.key.toLowerCase();
      const modes:Record<string,Exclude<ShapeMode,null>>={p:'point',g:'polygon',l:'line',r:'rectangle',c:'circle'};
      if(modes[key]){event.preventDefault();setContextMenu(null);startDrawing(modes[key]);return;}
      if(key==='v'){event.preventDefault();stopInteraction();}
      else if(key==='e'){event.preventDefault();editMode('vertices');}
      else if(key==='b'){event.preventDefault();if(geometry?.type!=='Point')editMode('edge');}
      else if(key==='m'){event.preventDefault();editMode('move');}
      else if(key==='f'){event.preventDefault();fitSelection();}
      else if(key==='s'){event.preventDefault();setSnapping(v=>!v);}
      else if(key==='t'){event.preventDefault();revealPanel('tools-terrain');}
      else if(key==='delete'&&!drawingMode&&(scratchId||selectedFeatureId)){
        event.preventDefault();if(scratchId)removeLocal();else document.querySelector<HTMLButtonElement>('[data-project-delete]')?.click();
      }
      else if(key==='?'){event.preventDefault();setShortcutHelp(true);}
    }
    function outside(event:MouseEvent){
      if(event.target instanceof HTMLElement&&!event.target.closest('.gis-context-menu'))setContextMenu(null);
    }
    window.addEventListener('keydown',commands);
    window.addEventListener('mousedown',outside);
    return()=>{window.removeEventListener('keydown',commands);window.removeEventListener('mousedown',outside);};
  });
  // A single command registry powers Ctrl+K for every workbench. Commands
  // invoke existing, revision-safe actions rather than duplicating GIS state.
  const workspaceCommands:WorkspaceCommand[]=[
    ...WORKSPACE_MODULES.map(module=>({
      id:'module:'+module.id,label:module.label,group:'Workbenches',
      description:module.description,run:()=>revealPanel(module.id),
    })),
    {id:'map:select',label:'Select / pan',group:'Map',
      shortcut:'V',run:stopInteraction},
    {id:'map:fit',label:'Fit selected area',group:'Map',shortcut:'F',
      disabled:!geometry,run:fitSelection},
    {id:'map:vertices',label:'Edit boundary vertices',group:'Geometry',
      shortcut:'E',disabled:!geometry||selectedLocked||busy,
      run:()=>editMode('vertices')},
    {id:'map:polygon',label:'Draw study area polygon',group:'Geometry',
      shortcut:'G',disabled:busy,run:()=>startDrawing('polygon')},
    {id:'map:line',label:'Draw a line',group:'Geometry',
      shortcut:'L',disabled:busy,run:()=>startDrawing('line')},
    {id:'map:snapping',label:snapping?'Disable snapping':'Enable snapping',
      group:'Geometry',shortcut:'S',run:()=>setSnapping(v=>!v)},
    {id:'map:save',label:'Save / export selection',group:'File',
      shortcut:'Ctrl S',disabled:!geometry||busy,run:saveSelection},
    {id:'map:layers',label:showLayers?'Hide object tree':'Show object tree',
      group:'View',run:()=>setShowLayers(v=>!v)},
    {id:'map:inspector',label:'Focus operations',
      group:'View',run:()=>setShowTools(true)},
    {id:'map:help',label:'Keyboard shortcuts',group:'Help',
      shortcut:'?',run:()=>setShortcutHelp(true)},
  ];
  return (
    <div className="workspace desktop-gis">
      <header className="gis-header">
        <div className="gis-brand"><Globe2 size={19}/> <strong>GeoFathom</strong></div>
        <WorkspaceModuleBar active={activeTool} open={true}
          onActivate={id=>revealPanel(id)}/>

        {/* Native details grouping prevents header popovers from covering each other. */}
        <details className="gis-settings" name="gis-header-menu">
          <summary>Settings</summary>
          <div className="gis-settings-panel">
            <div className="section-heading">Display</div>
              <label className="gis-check"><input aria-label="Map dimensions" type="checkbox" checked={showMeasurements} onChange={e=>setShowMeasurements(e.target.checked)}/> Map dimensions</label>
            <label>Area unit <select aria-label="Default area unit" value={areaUnit} onChange={event=>setAreaUnit(event.target.value as typeof areaUnit)}>
              <option value="auto">Automatic</option><option value="m2">m²</option><option value="ha">ha</option><option value="km2">km²</option><option value="mu">亩</option>
            </select></label>
            <label>Distance <select aria-label="Distance unit" value={display.distance} onChange={e=>setDisplay(old=>({...old,distance:e.target.value as typeof display.distance}))}>
              <option value="auto">Automatic</option><option value="m">m</option><option value="km">km</option></select></label>
            <label>Map contrast <select aria-label="Map contrast" value={display.contrast} onChange={e=>setDisplay(old=>({...old,contrast:e.target.value as typeof display.contrast}))}>
              <option value="auto">Automatic</option><option value="light">Light lines</option><option value="dark">Dark lines</option></select></label>
            <label>Selection fill <input aria-label="Selection fill opacity" type="range" min="0" max=".7" step=".02" value={display.fill} onChange={e=>setDisplay(old=>({...old,fill:Number(e.target.value)}))}/></label>
            <ComputingResources/>
            <div className="section-heading">Imagery sources</div>
            <form className="professional-form" onSubmit={event=>{event.preventDefault();try{setCustom(mapTilerImagery(mapTilerKey));setTileError('');setMapTilerKey('');setMessage('HD imagery connected. Choose Licensed HD under Map type.');}catch(e){setTileError(String(e));}}}>
              <input type="password" autoComplete="off" aria-label="MapTiler browser API key" placeholder="MapTiler key (licensed)" value={mapTilerKey} onChange={e=>setMapTilerKey(e.target.value)}/>
              <button disabled={!mapTilerKey.trim()}>Connect global HD imagery</button>
            </form>
              <details className="custom-basemap">
                <summary>Connect high-resolution imagery</summary>
                <form className="professional-form" onSubmit={event=>{
                  event.preventDefault();setTileError('');
                  try{setCustom(customBasemap(tileURL,tileCredit,tileZoom));setMessage('Custom tiles connected. Select Licensed HD under Map type.');}
                  catch(failure){setTileError(failure instanceof Error?failure.message:'Invalid tile settings.');}
                }}>
                  <input aria-label="Licensed XYZ tile URL" placeholder="https://…/{z}/{x}/{y}.jpg" value={tileURL} onChange={e=>setTileURL(e.target.value)} required/>
                  <input aria-label="Imagery attribution" placeholder="Provider attribution" value={tileCredit} onChange={e=>setTileCredit(e.target.value)} required/>
                  <label>Native maximum zoom <input type="number" min="1" max="23" value={tileZoom} onChange={e=>setTileZoom(Number(e.target.value))}/></label>
                  <button type="submit">Connect imagery</button>
                  <small className="compact-notice" title="Use a provider you are licensed to access. URLs are session-only; never enter private long-lived credentials.">Licensed source · session only</small>
                  {tileError&&<p className="discovery-error">{tileError}</p>}
                </form>
              </details>

            <div className="section-heading">Diagnostics</div>
            <small aria-label="Build revision" className="compact-notice">Frontend revision {import.meta.env.VITE_GEOFATHOM_REVISION}</small>
          </div>
        </details>
        <button className="gis-command-trigger" title="Search actions (Ctrl K)"
          aria-label="Command search" onClick={()=>setCommandOpen(true)}>
          <Search size={14}/> <span>Commands</span><kbd>Ctrl K</kbd>
        </button>
        <div className="gis-active-project" ref={setProjectToolbarTarget} aria-label="Active workspace"/>
        <details className="gis-header-menu gis-workspace-menu" name="gis-header-menu">
          <summary aria-label="Workspace menu">Workspace</summary>
          <div className="gis-header-popover">
            <button type="button" aria-expanded={showLayers} onClick={()=>{setDrawerTab('project');setShowLayers(v=>!v);}}>Project / Layers</button>
            <button type="button" onClick={()=>{setDrawerTab('search');setShowLayers(true);}}>Find a place</button>
            <button type="button" onClick={()=>setShortcutHelp(true)}>Shortcuts</button>
          </div>
        </details>
        <details className="gis-header-menu gis-file-menu" name="gis-header-menu">
          <summary aria-label="File actions">File</summary>
          <div className="gis-header-popover" aria-label="Unified save and export actions">
            <div className="gis-project-actions" ref={setProjectActionsTarget}/>
            <button type="button" onClick={()=>revealPanel('tools-export')}>Open Export module</button>
          </div>
        </details>
        <button className="gis-connection" title={connectionError||'Check backend connection'} onClick={()=>setConnectionRetry(v=>v+1)}>{capabilities?<Wifi size={14}/>:<WifiOff size={14}/>} {capabilities?'Connected':'Reconnect API'}</button>
      </header>
      <div className="gis-toolbar" aria-label="Survey toolbar">
        <div className="gis-navigation-tools">
          <button aria-label="Pan and select" title="Pan and select (V / Esc)" onClick={stopInteraction}>Pan</button>
          <button disabled={!measurement||!!preview} title="Zoom to selected geometry (F)" onClick={fitSelection}>Fit selection</button>
          <button disabled={!geometry} onClick={deselect} title="Clear selection without deleting saved features"><RotateCcw size={14}/> Deselect</button>
        </div>
        <div className="gis-survey-commands" ref={setToolbarTarget}/>
        <label className="gis-quick-basemap" aria-label="Basemap picker">
          <Globe2 size={15} aria-hidden="true"/>
          <select aria-label="Map type" value={basemap}
            title={BASEMAPS.find(item=>item.id===basemap)?.note??mapStatus}
            onChange={event=>setBasemap(event.target.value as BasemapId)}>
            {BASEMAP_GROUPS.map(group=><optgroup key={group.category} label={group.label}>
              {BASEMAPS.filter(item=>item.category===group.category).map(item=>
                <option key={item.id} value={item.id} disabled={!basemapAvailable(item,custom)}>
                  {item.name}
                </option>)}
            </optgroup>)}
          </select>
          <span className="gis-basemap-health" title={mapStatus} aria-label="Basemap status">{mapStatus.startsWith('Imagery unavailable')?'!':'●'}</span>
        </label>
      </div>
      <div className="gis-body">
        {expandedDock&&<div className="workspace-dock-backdrop" role="presentation" onClick={()=>setExpandedDock(null)}/>}
        <aside className={'sidebar gis-layers gis-project-drawer'+(expandedDock==='project'?' workspace-dock-expanded':'')}
          hidden={!showLayers} aria-label="Project and layers" style={{width:340}}>
          <WorkspaceDockHeading actions={<button className="workspace-dock-expand-button"
            aria-label={expandedDock==='project'?'Close full project view':'Open full project view'}
            title={expandedDock==='project'?'Return to workspace':'Open larger workspace'}
            onClick={()=>setExpandedDock(v=>v==='project'?null:'project')}>
            {expandedDock==='project'?<Minimize2 size={14}/>:<Maximize2 size={14}/>}
          </button>}><Layers3 size={15}/> Workspace</WorkspaceDockHeading>
          <nav className="gis-drawer-tabs" role="tablist" aria-label="Workspace pages">
            {([['project','Project'],['layers','Layers'],['search','Search']] as const).map(([key,label])=>
              <button key={key} type="button" role="tab" aria-selected={drawerTab===key}
                onClick={()=>setDrawerTab(key)}>{label}</button>)}
          </nav>
          <div className="sidebar-scroll">
          <section className="panel-section" hidden={drawerTab!=='project'}>
            <div className="section-heading"><Layers3 size={16} /><span>Projects</span></div>
            {!capabilities&&connectionError&&<div className="discovery-error" role="alert">{connectionError} <button onClick={()=>setConnectionRetry(v=>v+1)}>Reconnect</button></div>}
            <ProjectsPanel toolbarTarget={projectToolbarTarget} toolbarActionsTarget={projectActionsTarget} treeTarget={objectTreeTarget}
              interactionBusy={busy||Boolean(drawingMode)} objectPageSize={3}
              onObjectMutation={(id,feature)=>{
                // Search/attribute results may lie outside the workspace's
                // first page. Update their owner as well, avoiding ghost
                // rows and stale map labels after rename/delete/restore.
                setPagedFeatures(old=>feature?[feature,...old.filter(item=>item.id!==id)]:old.filter(item=>item.id!==id));
                setProjectWorkspace(old=>old?{...old,features:feature?
                  old.features.map(item=>item.id===id?feature:item):old.features.filter(item=>item.id!==id)}:old);
              }}
              objectGroups={[{id:'local-drawings',name:'Local drawings',items:scratch,
                selectedId:scratchId,onOpen:id=>{const item=scratch.find(f=>f.id===id);if(item){
                  setScratch(old=>old.map(f=>f.id===id?{...f,visible:true}:f));selectScratch({...item,visible:true});
                  if(activeTool==='tools-terrain')setObjectsOpen(false);
                }},
                onRename:async(id,name)=>{setScratch(old=>old.map(item=>item.id===id?{...item,name}:item));setMessage('Local drawing renamed · Ctrl Z to undo.');},
                onDelete:async id=>removeLocal(id)}]}
              geometry={busy || preview || pendingShared || drawingMode ? null : geometry}
              featureName={scratch.find(f=>f.id===scratchId)?.name||selectedPlace?.name||'Custom boundary'}
              featureSource={geometrySource || selectedPlace?.source || 'User drawn'}
              featureProperties={featureProperties}
              selectedFeatureId={selectedFeatureId}
              splitParts={splitParts}
              refreshToken={refreshToken}
              extraFeatures={pagedFeatures}
              onProjectSwitch={(id,created)=>{
                const previous=scratchScope.current;
                if(previous===id)return;
                const source=scratchHistory.current!.current;
                // Move only an explicitly selected local draft into a newly
                // created project; never carry saved objects into another project.
                const carry=created&&scratchId?source.find(f=>f.id===scratchId):null;
                const unbound=created&&!selectedFeatureId&&!scratchId&&geometry&&measurement&&!preview;
                const next=readScratch(id);
                if(carry&&!next.some(f=>f.id===carry.id))next.push(carry);
                const old=carry&&previous===null?source.filter(f=>f.id!==carry.id):source;
                if(!writeScratch(old,previous))setScratchStorageError(true);
                rasterScopes.current.set(previous??'local',{layers:rasterLayers,image:imageLayer,dem:demLayer});
                const view=rasterScopes.current.get(id??'local');
                setRasterLayers(view?.layers??[]);setImageLayer(view?.image??null);setDemLayer(view?.dem??null);
                scratchScope.current=id;scratchHistory.current=new ScratchHistory(next);setScratchState(next);
                setPins({scope:id,places:readPinnedPlaces(id)});
                projectEpoch.current++;projectIdentity.current=null;geometrySequence.current++;
                setProjectWorkspace(null);setActiveProjectId(null);clearWorkspace();
                setExtentMode(false);setExtentGeometry(null);
                if(carry)selectScratch(carry,false);
                else if(unbound&&geometry&&measurement){
                  storeScratch(geometry,measurement,null,{source:geometrySource,properties:featureProperties});
                  lastValid.current=structuredClone(geometry);setGeometry(geometry);setMeasurement(measurement);setGeometrySource(geometrySource);setFeatureProperties(featureProperties);
                }
              }}
              onWorkspace={(data, id) => {
                if(projectIdentity.current!==id){
                  projectIdentity.current=id;
                  projectEpoch.current++;
                  geometrySequence.current++;setBusy(false);setTerrainPicking(false);setTerrainOrigin(null);setTerrainHover(null);setExtentMode(false);setExtentGeometry(null);
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
                  setPagedFeatures([]);setExternalFeatures([]);setTerrainFeatures([]);setTerrainRasters([]);setTerrainFetchTarget(null);setExternalTiles([]);
                  setSpatialSelected([]);setQualityIssues([]);setProjectGrid(null);
                  setSelectionBox(null);setSelectionBoxMode(false);setLabelMoveMode(false);
                }
                setProjectWorkspace(data);
                setActiveProjectId(id);
              }}
              onOpen={feature=>{openStoredFeature(feature);if(activeTool==='tools-terrain')setObjectsOpen(false);}}
              onSavedDraft={()=>{if(scratchId)setScratchState(scratchHistory.current!.checkpoint(scratchHistory.current!.current.filter(f=>f.id!==scratchId)));setScratchId(null);}}
              onFeatureDeleted={deselect}
              onPlaceAnnotation={(projectId,layerId,text)=>{
                setPendingAnnotation({projectId,layerId,text});
                setDrawingMode(null);setTraceMode(false);setPromptMode(null);
                setEditing(false);setEdgeMoving(false);setMoving(false);
                setMessage('Click the map where the annotation should be placed.');
              }}
            />
          </section>


            <section className="panel-section scratch-layer" hidden={drawerTab!=='layers'}>
              <div className="section-heading"><Layers3 size={15}/><span>Local drawings · {scratch.length}</span></div>
              {scratchStorageError&&<p className="discovery-error">Browser storage unavailable. Export drawings before closing.</p>}
              {!scratch.length&&<small className="compact-notice">No drawings</small>}
              <div className="scratch-list" aria-label="Local drawings">
                {scratch.slice(scratchPage*scratchSize,(scratchPage+1)*scratchSize).map(item=><div key={item.id} className={'scratch-row '+(scratchId===item.id?'active':'')}>
                  <input type="checkbox" aria-label={'Show '+item.name} checked={item.visible} onChange={event=>{
                    if(!event.target.checked&&scratchId===item.id)deselect();
                    setScratch(old=>old.map(f=>f.id===item.id?{...f,visible:event.target.checked}:f));
                  }}/>
                  <button onClick={()=>{setScratch(old=>old.map(f=>f.id===item.id?{...f,visible:true}:f));selectScratch(item);}}>{item.name}</button>
                  <button title={'Delete '+item.name} aria-label={'Delete '+item.name} onClick={()=>{
                    removeLocal(item.id);
                  }}>×</button>
                </div>)}
              </div>
              {scratch.length>scratchSize&&<div className="gis-record-pager">
                <button type="button" disabled={scratchPage===0} onClick={()=>setScratchPage(v=>Math.max(0,v-1))}>Previous</button>
                <span>{Math.min(scratchPage*scratchSize+1,scratch.length)}–{Math.min((scratchPage+1)*scratchSize,scratch.length)} / {scratch.length}</span>
                <button type="button" disabled={(scratchPage+1)*scratchSize>=scratch.length}
                  onClick={()=>setScratchPage(v=>v+1)}>Next</button>
              </div>}
              {scratchId&&<input aria-label="Rename local drawing" value={scratch.find(f=>f.id===scratchId)?.name??''} maxLength={80}
                onChange={e=>setScratch(old=>old.map(f=>f.id===scratchId?{...f,name:e.target.value}:f))}/>}

            </section>
            <section className="panel-section gis-basemaps" hidden={drawerTab!=='layers'}>
              <div className="section-heading"><Layers3 size={15}/><span>Map overlays</span></div>
              {(terrainFeatures.length+terrainRasters.length)>0&&<label className="gis-check"><input aria-label="Terrain result layer" type="checkbox" checked={terrainVisible} onChange={e=>setTerrainVisible(e.target.checked)}/> Terrain result · {terrainFeatures.length+terrainRasters.length}</label>}
              {rasterLayers.map(layer=><div key={layer.asset.id} className="raster-layer-row">
                <label className="gis-check"><input aria-label={'Show raster '+layer.asset.name} type="checkbox" checked={layer.visible}
                  onChange={e=>setRasterLayers(old=>changeRaster(old,layer.asset.id,{visible:e.target.checked}))}/> {layer.kind==='dem'?'DEM · ':''}{layer.asset.name}</label>
                <label>Opacity <input aria-label={'Opacity '+layer.asset.name} type="range" min="0" max="1" step=".05" value={layer.opacity}
                  onChange={e=>setRasterLayers(old=>changeRaster(old,layer.asset.id,{opacity:Number(e.target.value)}))}/></label>
                <div className="survey-action-bar"><button onClick={()=>{
                  const [w,s,e,n]=layer.asset.bbox;setFocus({longitude:(w+e)/2,latitude:(s+n)/2,bbox:layer.asset.bbox,key:Date.now()});
                }}>Fit</button>
                <button title="Remove layer; original library file is retained" aria-label={'Remove raster '+layer.asset.name} onClick={()=>{
                  geometrySequence.current++;setBusy(false);setRasterLayers(old=>old.filter(l=>l.asset.id!==layer.asset.id));
                  if(imageLayer?.id===layer.asset.id){setImageLayer(null);setTraceMode(false);setPromptMode(null);setPositivePoints([]);setNegativePoints([]);setBoxPoints([]);}
                  if(demLayer?.id===layer.asset.id){setDemLayer(null);setExtentMode(false);setExtentGeometry(null);setTerrainPicking(false);setTerrainOrigin(null);setTerrainHover(null);}
                  setMessage('Raster removed from map. Source retained in library.');
                }}>Remove</button></div>
              </div>)}
            </section>
          <section className="panel-section" hidden={drawerTab!=='search'}>
            <div className="section-heading"><Search size={16} /><span>Find a place</span></div>
            <form onSubmit={runSearch} className="search-form">
              <input aria-label="Search for a place" placeholder="Airport, landmark, city, address…" value={locationInput}
                onChange={event => setLocationInput(event.target.value)} maxLength={200} />
              <button aria-label="Search" type="submit" disabled={busy || locationInput.trim().length < 2}>
                <ArrowRight size={17} />
              </button>
            </form>
            {pinStorageError&&<small role="alert" className="discovery-error">Pinned locations cannot be saved in browser storage.</small>}
            {!!pinnedPlaces.length&&<div className="pinned-places" aria-label="Pinned places">
              <small>Retained locations · remove manually ({pinnedPlaces.length}/{PIN_LIMIT})</small>
              {pinnedPlaces.slice(pinPage*pinSize,(pinPage+1)*pinSize).map(place=><div key={place.id} className="survey-action-bar">
                <button aria-label={'Select pinned '+place.name} aria-pressed={selectedPlace?.id===place.id}
                  onClick={()=>void selectPlace(place)}>{place.name}</button>
                <button aria-label={'Remove pinned '+place.name} title="Remove this retained location"
                  onClick={()=>removePinnedPlace(place.id)}>Remove</button>
              </div>)}
              {pinnedPlaces.length>pinSize&&<div className="gis-record-pager">
                <button type="button" disabled={pinPage===0} onClick={()=>setPinPage(v=>Math.max(0,v-1))}>Previous</button>
                <span>{Math.min(pinPage*pinSize+1,pinnedPlaces.length)}–{Math.min((pinPage+1)*pinSize,pinnedPlaces.length)} / {pinnedPlaces.length}</span>
                <button type="button" disabled={(pinPage+1)*pinSize>=pinnedPlaces.length}
                  onClick={()=>setPinPage(v=>v+1)}>Next</button>
              </div>}
            </div>}
          </section>


          <section className="panel-section" hidden={drawerTab!=='search'}>
            <div className="section-heading"><Search size={16} /><span>Find areas by size</span><span className="section-pill">Spatial query</span></div>
            <DiscoveryPanel viewport={viewport} busy={busy} onFound={(result: DiscoveryResponse) => {
              setDiscovered(result.results);
              setCandidates(result.results);
              // Discovery updates candidate results but does not delete retained map locations.
              setMessage(result.results.length
                ? 'Found ' + result.results.length + ' mapped features. ' + result.warning
                : 'No mapped features matched the filter. ' + result.warning);
              setError('');
            }} />
          </section>


          {candidates.length > 0 && (
            <section className="panel-section" hidden={drawerTab!=='search'}>
              <div className="section-heading"><MapPin size={16} /><span>Search results</span><span className="result-count">{candidates.length}</span></div>
              <div className="results">
                {candidates.slice(candidatePage*candidateSize,(candidatePage+1)*candidateSize).map(place => (
                  <button key={place.id} className={selectedPlace?.id === place.id ? 'result active' : 'result'} onClick={() => { setError(''); void selectPlace(place); }}>
                    <MapPin size={15} />
                    <span className="result-text"><strong>{place.name}</strong><small>{place.display_name}</small></span>
                    <span className={place.boundary_status === 'mapped' ? 'result-tag mapped' : 'result-tag'}>
                      {place.boundary_status === 'mapped' ? 'Boundary' : 'Point'}
                    </span>
                  </button>
                ))}
              </div>
              {candidates.length>candidateSize&&<div className="gis-record-pager">
                <button type="button" disabled={candidatePage===0} onClick={()=>setCandidatePage(v=>Math.max(0,v-1))}>Previous</button>
                <span>{Math.min(candidatePage*candidateSize+1,candidates.length)}–{Math.min((candidatePage+1)*candidateSize,candidates.length)} / {candidates.length}</span>
                <button type="button" disabled={(candidatePage+1)*candidateSize>=candidates.length}
                  onClick={()=>setCandidatePage(v=>v+1)}>Next</button>
              </div>}
            </section>
          )}


          </div>
        </aside>
        <main className="main">
        <div className="map-wrap">
          <MapCanvas
            selected={geometry} drawingMode={drawingMode} vertices={vertices}
            networkFaces={!drawingMode?(networkAreas?.faces??[]):[]}
            onSelectNetworkFace={activateNetworkFace}
            terrainPicking={terrainPicking}
            terrainMarker={showTools&&activeTool==='tools-terrain'?
              (terrainHover??(terrainProfileMapIndex!==null?terrainProfileSamples[terrainProfileMapIndex]?.coordinate??null:null)??terrainOrigin):null}
            profileSamples={showTools&&activeTool==='tools-terrain'?terrainProfileSamples:[]}
            onProfileCursor={setTerrainProfileMapIndex}
            preservePlaceSelection={!!selectedPlace}
            pinnedPlaces={pinnedPlaces.map(place=>({id:place.id,geometry:visibleGeometry(place)}))}
            onSelectPinnedPlace={id=>{const place=pinnedPlaces.find(p=>p.id===id);if(place)void selectPlace(place);}}
            terrainResults={[...(terrainVisible?terrainFeatures:[]),...(terrainProfileLine?[{type:'Feature' as const,geometry:terrainProfileLine,properties:{name:'Profile measurement line',color:'#d26b2f'}}]:[])]} terrainRasters={terrainVisible?terrainRasters:[]}
            terrainFetchTarget={showTools&&activeTool==='tools-terrain'?terrainFetchTarget:null}
            onTerrainPick={position=>{setTerrainOrigin(position);setTerrainPicking(false);setMessage('Terrain point selected.');}}
            onContextMenu={(x,y)=>setContextMenu({x,y})} onDeselect={deselect}
            selectedBoundaryNode={selectedBoundaryNode} onSelectBoundaryNode={setSelectedBoundaryNode}
            onEditingError={setError}
            editing={editing} moving={moving} edgeMoving={edgeMoving} snapping={snapping}
            selectedLocked={selectedLocked}
            layerFeatures={[...scratch.map(item=>({id:item.id,layer_id:'scratch',geometry:item.geometry,name:item.name,source:'Local scratch',
              properties:{},measurement:item.measurement,style:DEFAULT_LAYER_STYLE,color:'#168047',visible:item.visible,locked:false})),
              ...[...(projectWorkspace?.features ?? []),
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
            })]}
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
              const local=scratch.find(f=>f.id===id);
              if(local){selectScratch(local,false);return;}
              const feature = projectWorkspace?.features.find(item => item.id === id) ??
                pagedFeatures.find(item=>item.id===id);
              if (feature) openStoredFeature(feature);
            }}
            focus={focus} basemap={basemap} customBasemap={custom} onBasemapStatus={setMapStatus}
            measurement={preview?null:measurement} showMeasurements={showMeasurements} display={display}
            selectedFeatureId={selectedFeatureId??scratchId}
            onFinishDrawing={(closeLine=false)=>{
              const points=drawingVerticesRef.current;
              void finishDrawing(closeLine&&drawingMode==='line'&&points.length>=3?[...points,points[0]]:points);
            }}
            rasterLayers={rasterLayers} onRasterError={setError}
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
                storeScratch(result.geometry,result.measurement,null,{source:imageLayer.provenance+' · '+result.engine,
                  properties:{source_type:'image_derived',image_id:imageLayer.id,method:result.provider,quality:'requires_user_review'}});
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
                if(sequence===geometrySequence.current)setError(failure instanceof Error ? failure.message : 'Automatic outline failed.');
              } finally {
                if(sequence===geometrySequence.current)setBusy(false);
              }
            }}
            discovered={[...discovered.map(place => place.geometry).filter((item): item is GeoJSON.Geometry => item !== null),
              ...externalFeatures,...splitParts.slice(1),...(extentMode&&extentGeometry?[extentGeometry]:[])]}
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
              if(busy||!drawingMode)return;
              // The MapCanvas handles start-node pixel snapping and closure.
              // Every other newly committed vertex must preserve simple-ring topology.
              const current=drawingVerticesRef.current;
              const reason=sketchAddError(drawingMode,current,position);
              if(reason){
                if(reason!=='Duplicate of the last point.')setError(reason);
                return;
              }
              const next=[...current,position];
              setSketchVertices(next);setVertexRedo([]);setError('');
              const complete=drawingMode==='point'?1:
                ['rectangle','circle','trace-along'].includes(drawingMode)?2:4000;
              if(complete<4000&&next.length===complete)void finishDrawing(next);
            }}
          />
          <div className="map-legend">
            <button className="map-legend-toggle" aria-label="Toggle map legend"
              aria-expanded={showLegend&&!editing} disabled={editing}
              title={editing?'Finish geometry editing to open the map legend':'Toggle map legend'}
              onClick={()=>setShowLegend(value=>!value)}>
              <Layers3 size={15}/> Legend
            </button>
            {showLegend&&!editing&&<div className="map-legend-items" aria-label="Map legend">
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
              {!!networkAreas?.count&&<div className="map-legend-item"><span className="legend-swatch" style={{background:'#238d89'}}/><span>Enclosed areas · {networkAreas.count}</span></div>}
              {scratch.some(f=>f.visible)&&<div className="map-legend-item"><span className="legend-swatch" style={{background:'#168047'}}/><span>Local drawings · {scratch.filter(f=>f.visible).length}</span></div>}
              {rasterLayers.filter(l=>l.visible).map(l=><div key={l.asset.id} className="map-legend-item"><span className="legend-swatch" style={{background:'#a8adb0'}}/><span>{l.kind==='dem'?'DEM':'Raster'} · {l.asset.name}</span></div>)}
              {terrainVisible&&(terrainFeatures.length+terrainRasters.length)>0&&<div className="map-legend-item"><span className="legend-swatch" style={{background:'#d7b65e'}}/><span>Terrain results · {terrainFeatures.length+terrainRasters.length}</span></div>}
              {terrainVisible&&terrainRasters.map(item=><details key={item.id} className="terrain-map-legend"><summary>{item.title}</summary>{item.raster.legend.map(bin=><div key={bin.label} className="map-legend-item"><span className="legend-swatch" style={{background:bin.color}}/><span>{bin.label}</span></div>)}</details>)}
              {!(projectWorkspace?.layers??[]).some(layer=>Boolean(layer.visible))&&!scratch.some(f=>f.visible)&&!rasterLayers.some(l=>l.visible)&&!(terrainFeatures.length+terrainRasters.length)&&
                <small>No visible overlays</small>}
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
        <aside className={'gis-inspector gis-operations'+(expandedDock==='operations'?' workspace-dock-expanded':'')}
          data-object-browser={activeTool==='tools-terrain'&&objectsOpen?'true':'false'}
          aria-label="Operations">
          <WorkspaceDockHeading actions={<button className="workspace-dock-expand-button"
            aria-label={expandedDock==='operations'?'Close full operations view':'Open full operations view'}
            title={expandedDock==='operations'?'Return to workspace':'Open larger workspace'}
            onClick={()=>setExpandedDock(v=>v==='operations'?null:'operations')}>
            {expandedDock==='operations'?<Minimize2 size={14}/>:<Maximize2 size={14}/>}
          </button>}><Compass size={15}/> Tools</WorkspaceDockHeading>
          <div className={'sidebar-scroll'+(['tools-services','tools-export'].includes(activeTool)?' data-fixed-operations':'')}
            tabIndex={0} aria-label="Operations scrolling region">
          <details className="workspace-objects" hidden={['tools-services','tools-export'].includes(activeTool)}
            open={objectsOpen} onToggle={event=>setObjectsOpen(event.currentTarget.open)}>
            <summary>Objects{activeTool==='tools-terrain'&&!objectsOpen&&<small className="workspace-object-current">
              {selectedSaved?.name??scratch.find(item=>item.id===scratchId)?.name??selectedPlace?.name??'Choose an object'}
            </small>}</summary>
            {activeTool==='tools-terrain'&&objectsOpen&&<button type="button" className="workspace-object-back"
              onClick={()=>setObjectsOpen(false)}>Back to terrain tools</button>}
            <div ref={setObjectTreeTarget}/>
            {geometry&&<details className="geometry-edit-controls">
              <summary>Geometry / vertices</summary>
              <BoundaryEditor geometry={geometry} sourcePlace={selectedPlace} selectedParcel={selectedParcel}
                onChooseParcel={value=>void chooseSelectedParcel(value)}
                editing={editing&&!moving&&!edgeMoving} busy={busy} selectedNode={selectedBoundaryNode}
                onSelectNode={setSelectedBoundaryNode}
                onToggleEditing={()=>{if(editing){setEditing(false);setMoving(false);setEdgeMoving(false);}
                  else editMode('vertices');}}
                onMoveNode={(path,coordinate)=>{
                  if(!geometry||selectedLocked)return;
                  void commitGeometry(moveVertex(geometry,path,coordinate),'Boundary node coordinates validated.');
                }}
                onRemoveNode={path=>{
                  if(!geometry||selectedLocked)return;
                  try{void commitGeometry(removeVertex(geometry,path),'Boundary node removed and validated.');}
                  catch(e){setError(e instanceof Error?e.message:String(e));}
                }}/>
            </details>}

          </details>
          {resultsTarget&&['tools-survey','tools-services'].includes(activeTool)&&
            (networkAreas?.count??0)>0&&createPortal(
            <section className="panel-section data-network-results" aria-label="Independent enclosed areas">
              <div className="data-metric-band">
                <div><small>Enclosed areas</small><strong>{networkAreas!.count}</strong></div>
                <div><small>Combined area</small><strong>{areaText(networkAreas!.area_m2,areaUnit)}</strong></div>
              </div>
              {networkAreas!.faces.slice(networkPage*4,(networkPage+1)*4).map(face=>
                <div className="data-network-result-row" key={face.id}>
                  <strong>{face.name}</strong>
                  <span>{areaText(face.measurement.area_m2??0,areaUnit)}</span>
                  <small>{distanceText(face.measurement.perimeter_m??0,display.distance)} perimeter</small>
                </div>)}
              {networkAreas!.count>4&&<div className="gis-record-pager">
                <button disabled={networkPage===0} onClick={()=>setNetworkPage(v=>v-1)}>Previous</button>
                <span>{networkPage+1}/{Math.ceil(networkAreas!.count/4)}</span>
                <button disabled={(networkPage+1)*4>=networkAreas!.count}
                  onClick={()=>setNetworkPage(v=>v+1)}>Next</button>
              </div>}
            </section>,resultsTarget)}
          {resultsTarget&&activeTool!=='tools-terrain'&&!(['tools-survey','tools-services'].includes(activeTool)&&(networkAreas?.count??0)>1)&&(geometry||measurement||preview)&&createPortal(<section className="panel-section results-summary">
            <div className="section-heading"><Compass size={16} /><span>Selection</span></div>
            <div className="analysis-card">
              
              {measurement && !preview && (
                <>
                  <div className="metric">
                    <span>{measurement.area_m2 !== null ? 'Geographic area' : 'Distance'}</span>
                    <strong>{measurement.area_m2 !== null
                      ? areaText(measurement.area_m2,areaUnit)
                      : measurement.length_m !== null ? distanceText(measurement.length_m,display.distance) : 'Location only'}</strong>
                  </div>
                  {measurement.perimeter_m !== null && <div className="metric secondary"><span>Perimeter</span><strong>{distanceText(measurement.perimeter_m,display.distance)}</strong></div>}
                  <span className="analysis-measurement-method" title={measurement.method} aria-label="Measurement method">{measurement.method}</span>
                  {measurement.method===OFFLINE_METHOD&&<button onClick={()=>{if(geometry)void commitGeometry(geometry,'Exact measurement updated.');}}>Validate exact measurement</button>}
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
              {geometry && ['Polygon','MultiPolygon','LineString','MultiLineString'].includes(geometry.type) && (
                <details className="edge-measurements">
                  <summary>Edge lengths · {previewEdgeLengths(geometry).total} segments</summary>
                  <div>
                    {previewEdgeLengths(geometry).edges.map((edge, index) =>
                      <div key={index}><span>{edge.label}</span><strong>{!preview&&measurement?.method!==OFFLINE_METHOD&&measurement?.edge_lengths_m?.[index]!==undefined?'':'~ '}{number(!preview?(measurement?.edge_lengths_m?.[index]??edge.length_m):edge.length_m,2)} m</strong></div>)}
                  </div>
                  <small className="compact-notice" title="Live spherical preview. Final area and perimeter use the WGS84 ellipsoid.">~ estimated · WGS84 after validation</small>
                </details>
              )}
              {selectedPlace && <p className="data-source">Data: {selectedPlace.source} · {geometry&&['Polygon','MultiPolygon','LineString','MultiLineString'].includes(geometry.type) ? 'Mapped outline':'Coordinates only · use DEM extent or draw a study area'}</p>}

            </div>
          </section>,resultsTarget)}

          <section id="tools-survey" hidden={activeTool!=='tools-survey'} className="panel-section">
            <div className="section-heading"><Pencil size={16} /><span>Survey & geometry editor</span><span className="section-pill">Precision</span></div>
            <SurveyTools
              toolbarTarget={showTools&&(activeTool==='tools-survey'||terrainLineDrawing||drawingMode!==null)?toolbarTarget:null} busy={busy} locked={selectedLocked}
              edgeMoving={edgeMoving} onEdgeMove={active=>{
                setEdgeMoving(active);setEditing(active);setMoving(false);setLinked(false);
                setDrawingMode(null);setVertices([]);setTraceMode(false);setPromptMode(null);
                setPendingAnnotation(null);setSelectionBoxMode(false);setLabelMoveMode(false);
              }}
              mode={drawingMode}
              sketchError={drawingMode?error:null}
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
              canUndo={drawingMode?vertices.length>0:
                (selectedFeatureId?timeline.current.canUndo:scratchHistory.current!.canUndo) && historyPulse >= 0}
              canRedo={drawingMode?vertexRedo.length>0:
                (selectedFeatureId?timeline.current.canRedo:scratchHistory.current!.canRedo) && historyPulse >= 0}
              saved={activeProjectId ? projectWorkspace?.features ?? [] : []}
              onStart={startDrawing}
              onFinish={() => { if(!busy)void finishDrawing(); }}
              onCancel={stopInteraction}
              onUndoPoint={undoSketchPoint}
              onUndo={()=>drawingMode?undoSketchPoint():historyStep()}
              onRedo={()=>drawingMode?redoSketchPoint():historyStep(true)}
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
                if(drawingMode){
                  const current=drawingVerticesRef.current;
                  if(['polygon','hole'].includes(drawingMode)&&current.length>=3&&
                    point[0]===current[0][0]&&point[1]===current[0][1]){
                    void finishDrawing();return;
                  }
                  const problem=sketchAddError(drawingMode,current,point);
                  if(problem){setError(problem);return;}
                  const next=[...current,point];setSketchVertices(next);setVertexRedo([]);setError('');
                  const complete=drawingMode==='point'?1:
                    ['rectangle','circle','trace-along'].includes(drawingMode)?2:4000;
                  if(complete<4000&&next.length===complete)void finishDrawing(next);
                }else void numericShape('point',{vertices:[point]});
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


          <section id="tools-raster" hidden={activeTool!=='tools-raster'} className="panel-section">
            <div className="section-heading"><Layers3 size={16} /><span>Georeferenced imagery</span></div>
            <RasterPanel
              asset={imageLayer} localImport={capabilities?.local_raster_import===true} refreshToken={connectionRetry+refreshToken}
              onSelect={(asset) => {
                geometrySequence.current++;
                if(!projectCurrent())return;
                setImageLayer(asset);setRasterLayers(old=>addRaster(old,asset,'image'));
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
                  storeScratch(refined.geometry,refined.measurement,null,{source:'SAM 2 · '+imageLayer.name,
                    properties:{source_type:'image_derived',image_id:imageLayer.id,model_id:refined.model_id,quality:'requires_user_review'}});
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
                  if(sequence===geometrySequence.current)setError(failure instanceof Error?failure.message:'SAM 2 refinement unavailable.');
                }finally{if(sequence===geometrySequence.current)setBusy(false);}
              }}
            />
         </section>


          <section id="tools-gis" hidden={activeTool!=='tools-gis'} className="panel-section">
            <div className="section-heading"><Layers3 size={16}/><span>Professional GIS tools</span></div>
            <ProfessionalPanel
              resultsTarget={resultsTarget} active={activeTool==='tools-gis'}
              key={activeProjectId ?? 'no-project'}
              projectId={activeProjectId}
              workspace={projectWorkspace}
              geometry={geometry}
              raster={demLayer??imageLayer}
              refreshToken={refreshToken}
              onRefresh={()=>setRefreshToken(v=>v+1)}
              onOpen={id=>{
                const feature=projectWorkspace?.features.find(item=>item.id===id);
                if(feature)openStoredFeature(feature);
              }}
            />

          </section>

          <section id="tools-terrain" hidden={activeTool!=='tools-terrain'} className="panel-section">
            <TerrainWorkbench key={'terrain-'+(activeProjectId??'no-project')} projectId={activeProjectId}
              resultsTarget={resultsTarget}
              operationsFooterTarget={operationsFooterTarget}
              resultsFooterTarget={resultsFooterTarget}
              exportTarget={terrainExportTarget}
              active={activeTool==='tools-terrain'}
              geometry={preview||drawingMode&&!terrainLineDrawing?null:extentMode?extentGeometry:geometry}
              profileGeometry={terrainProfileLine} raster={demLayer} imageRaster={imageLayer} viewport={viewport}
              connected={Boolean(capabilities)} localImport={capabilities?.local_raster_import===true}
              refreshToken={refreshToken+connectionRetry} origin={terrainOrigin} picking={terrainPicking}
              onSelectRaster={asset=>{
                if(!projectCurrent())return;
                setDemLayer(asset);setRasterLayers(old=>asset?selectDEM(old,asset):hideDEMs(old));
                setTerrainOrigin(null);setTerrainPicking(false);setTerrainHover(null);
                setExtentMode(false);setExtentGeometry(null);
                // Selecting a stored DEM must NEVER reposition the current map.
                // Users can explicitly choose Fit in the raster layer panel.
                setMessage(asset?'DEM selected: '+asset.name+' · current map position retained.':'Elevation source cleared; downloaded files are retained.');
              }}
              onDraw={line=>{if(line)startTerrainLine();else{setExtentMode(false);setExtentGeometry(null);startDrawing('polygon');}}}
              onClearProfile={()=>setTerrainProfileLine(null)}
              extentMode={extentMode} onUseSelection={()=>setExtentMode(false)}
              onUseExtent={()=>{
                if(!demLayer)return;
                setExtentGeometry({type:'Polygon',coordinates:[[...demLayer.corners,demLayer.corners[0]]]});
                setExtentMode(true);setMessage('DEM footprint selected for analysis only.');
              }}
              onPick={()=>{
                setTerrainPicking(value=>!value);setDrawingMode(null);setVertices([]);
                setEditing(false);setEdgeMoving(false);setMoving(false);setTraceMode(false);setPromptMode(null);
                setSelectionBoxMode(false);setLabelMoveMode(false);setPendingAnnotation(null);
              }}
              onFetchTarget={setTerrainFetchTarget}
              onFitSelectedArea={()=>{
                const g=geometry;
                if(!g)return;
                const bounds=terrainGeometryBounds(g);
                if(bounds){const [w,s,e,n]=bounds;
                  setFocus({longitude:(w+e)/2,latitude:(s+n)/2,bbox:bounds,key:Date.now()});
                }
              }}
              onHover={setTerrainHover}
              profileMapIndex={terrainProfileMapIndex}
              onProfileSamples={samples=>{setTerrainProfileSamples(samples);setTerrainProfileMapIndex(null);}}
              onPreview={value=>{if(projectCurrent())setTerrainFeatures(value);}}
              onRasterPreview={value=>{if(projectCurrent())setTerrainRasters(value);}}
              onSaved={()=>{if(projectCurrent())setRefreshToken(v=>v+1);}}/>
          </section>

          <section id="tools-spatial" hidden={activeTool!=='tools-spatial'} className="panel-section">
            <div className="section-heading"><Layers3 size={16}/><span>Geometry processing</span></div>
            <GeometryAnalysis geometry={preview||drawingMode?null:geometry} selectedId={selectedFeatureId??scratchId}
              features={[...scratch,...(projectWorkspace?.features??[])]} connected={Boolean(capabilities)}
              onResult={(g,measured,name)=>{
                if(!projectCurrent())return;
                geometrySequence.current++;setSelectedFeatureId(null);setScratchId(null);setLinked(false);
                storeScratch(g,measured,null);setGeometry(g);setMeasurement(measured);setPreview(null);
                lastValid.current=structuredClone(g);timeline.current=new GeometryTimeline();timeline.current.push(g);setHistoryPulse(v=>v+1);
                setGeometrySource('GIS geometry analysis');setFeatureProperties({source_type:'spatial_operation',operation:name});setMessage(name+' created as a new local feature.');
              }}/>
            <div className="section-heading"><Layers3 size={16}/><span>GIS selection, QA & print layout</span></div>
            <SpatialToolsPanel
              resultsTarget={resultsTarget} active={activeTool==='tools-spatial'}
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

          <section id="tools-style" hidden={activeTool!=='tools-style'} className="panel-section">
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

          <section id="tools-services" hidden={activeTool!=='tools-services'} className="panel-section">
            <DataWorkbench
              projectId={activeProjectId} workspace={projectWorkspace}
              geometry={geometry} viewport={viewport} connected={Boolean(capabilities)}
              network={networkAreas} networkNotice={networkNotice}
              sourceCount={networkSources.length}
              vectorSources={[
                ...scratch.map(item=>({id:item.id,name:item.name,geometry:item.geometry})),
                ...(projectWorkspace?.features??[]).map(item=>({id:item.id,name:item.name,geometry:item.geometry})),
              ]}
              onDerived={(next,_measured,name)=>{void commitGeometry(next,'Data · '+name,true);}}
              onRebuild={rebuildNetwork} onStoreAreas={keepNetworkAreas}
              onSelectArea={activateNetworkFace}
              onOpenLayers={()=>{setDrawerTab('layers');setShowLayers(true);}}
              onTiles={value=>{if(projectCurrent())setExternalTiles(value);}}
              onPreview={value=>{if(projectCurrent())setExternalFeatures(value);}}
              onPage={value=>{if(projectCurrent())setPagedFeatures(value);}}
              onRefresh={()=>setRefreshToken(value=>value+1)}
              onRasterAdded={(asset,kind)=>{
                // Do not silently reinterpret imagery (RGB, satellite, masks)
                // as an elevation model. DEM is selected only explicitly.
                if(kind==='dem'){
                  setDemLayer(asset);setRasterLayers(old=>selectDEM(old,asset));
                }else{
                  setImageLayer(asset);setRasterLayers(old=>addRaster(old,asset,'image'));
                }
                setMessage('Raster added to the active map.');
              }}
            />
          </section>

          <section id="tools-export" hidden={activeTool!=='tools-export'} className="panel-section">
            <ExportWorkbench
              projectId={activeProjectId} workspace={projectWorkspace}
              selected={geometry} measurement={measurement}
              selectedProperties={selectedSaved?{...selectedSaved.properties,name:selectedSaved.name,source:selectedSaved.source}:scratch.find(f=>f.id===scratchId)?.properties}
              scratch={scratch} faces={networkAreas?.faces??[]}
              terrainRasters={terrainRasters} viewport={viewport}
              rasterSources={rasterLayers.map(l=>({id:l.asset.id,kind:l.kind}))}/>
            <div className="gis-terrain-export-action export-specialized-actions"
              ref={setTerrainExportTarget}/>
          </section>


          <section id="tools-ai" hidden={activeTool!=='tools-ai'} className="panel-section">
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


          </div>
          <div className="workspace-fixed-footer" ref={setOperationsFooterTarget}/>
        </aside>
        <aside className={'gis-results-monitor'+(expandedDock==='results'?' workspace-dock-expanded':'')} aria-label="Results monitor">
          <WorkspaceDockHeading actions={<button className="workspace-dock-expand-button"
            aria-label={expandedDock==='results'?'Close full results view':'Open full results view'}
            title={expandedDock==='results'?'Return to workspace':'Open larger workspace'}
            onClick={()=>setExpandedDock(v=>v==='results'?null:'results')}>
            {expandedDock==='results'?<Minimize2 size={14}/>:<Maximize2 size={14}/>}
          </button>}><Layers3 size={15}/> Results</WorkspaceDockHeading>
          <div className="sidebar-scroll" ref={setResultsTarget} tabIndex={0} aria-label="Results scrolling region">
            {!measurement&&activeTool==='tools-survey'&&<div className="workspace-monitor-empty">No selection</div>}
          </div>
          <div className="workspace-fixed-footer" ref={setResultsFooterTarget}/>
        </aside>
      </div>
      {contextMenu&&<div className="gis-context-menu" role="menu" aria-label="Map commands"
        style={{left:Math.max(4,Math.min(contextMenu.x,window.innerWidth-210)),top:Math.max(4,Math.min(contextMenu.y,window.innerHeight-260))}}>
        <button role="menuitem" onClick={()=>{stopInteraction();}}>Select / pan <kbd>V</kbd></button>
        <button role="menuitem" disabled={!geometry||selectedLocked||busy} onClick={()=>editMode('vertices')}>Edit vertices <kbd>E</kbd></button>
        <button role="menuitem" disabled={!geometry||geometry.type==='Point'||selectedLocked||busy} onClick={()=>editMode('edge')}>Move edge <kbd>B</kbd></button>
        <button role="menuitem" disabled={!geometry||selectedLocked||busy} onClick={()=>editMode('move')}>Move feature <kbd>M</kbd></button>
        <button role="menuitem" disabled={!measurement} onClick={()=>{fitSelection();setContextMenu(null);}}>Fit selection <kbd>F</kbd></button>
        <button role="menuitem" disabled={!geometry||busy||!!preview} onClick={()=>{setContextMenu(null);saveSelection();}}>Save / export <kbd>Ctrl S</kbd></button>
        <button role="menuitem" disabled={(!scratchId&&!selectedFeatureId)||busy||selectedLocked} onClick={()=>{if(scratchId)removeLocal();else{setContextMenu(null);document.querySelector<HTMLButtonElement>('[data-project-delete]')?.click();}}}>Delete feature <kbd>Del</kbd></button>
        <button role="menuitem" onClick={()=>{setContextMenu(null);revealPanel('tools-terrain');}}>Terrain <kbd>T</kbd></button>
      </div>}
      {shortcutHelp&&<div className="gis-dialog-shade" onClick={()=>setShortcutHelp(false)}>
        <div role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" className="gis-shortcuts" onClick={e=>e.stopPropagation()}>
          <header><strong>Keyboard / mouse</strong><button aria-label="Close shortcuts" onClick={()=>setShortcutHelp(false)}>×</button></header>
          <div className="shortcut-table">{[
            ['Select / pan','V / Esc'],['Point / line','P / L'],['Polygon / rectangle / circle','G / R / C'],
            ['Edit vertices / edge / move','E / B / M'],['Finish drawing','Enter / double-click / right-click'],
            ['Remove last vertex','Backspace / Ctrl Z'],['Undo / redo','Ctrl Z / Ctrl Y'],['Delete edit vertex','Right-click vertex'],
            ['Insert vertex','Double-click edge'],['Context menu','Right-click map'],['Fit selection','F'],['Toggle snapping','S'],
            ['Save or export','Ctrl S'],['Delete local drawing','Delete'],['Terrain tools','T'],
            ['Command search','Ctrl K'],['Help','?'],
          ].map(([action,key])=><div key={action}><span>{action}</span><kbd>{key}</kbd></div>)}</div>
        </div>
      </div>}
      <WorkspaceCommandPalette open={commandOpen}
        commands={workspaceCommands} onClose={()=>setCommandOpen(false)}/>
      <footer className="gis-status" role="status">
        <span>{error?<span className="error">{error}</span>:busy?'Processing…':message}</span>
        <span>{drawingMode?'Draw · '+drawingMode:editing?(moving?'Move feature':edgeMoving?'Move edge':'Edit vertices'):'Select / pan'} · WGS84</span>
      </footer>
    </div>
  );
}
