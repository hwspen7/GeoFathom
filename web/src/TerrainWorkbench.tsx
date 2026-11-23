import {useEffect,useMemo,useRef,useState,type ChangeEvent} from 'react';
import {createPortal} from 'react-dom';
import {Mountain} from 'lucide-react';
import {advancedTerrain,saveFeatureBatch,analyzeTerrain,terrainProfile,listImagery,uploadImagery,fetchPublicDEM,prepareDEM,type DEMProcessMode,type TerrainMesh,type TerrainOperation,type RasterAsset,type TerrainRasterLayer} from './api';
import {ProfilePlot,MetricBars,ElevationDistribution,AspectRose,SectionPlot,ResultPane,HypsometricPlot,ProfileGradePlot,TerrainClassShare,TerrainCumulativeArea,TerrainClassTable,terrainClassesCsv} from './TerrainCharts';
import {GPUView} from './TerrainMeshView';
import type {Position} from './editing';
import {measurementAnchor} from './editing';
import {terrainMetricDifferences,sameGeometryFootprint} from './terrainComparison';
import {readTerrainRuns,writeTerrainRuns,insertTerrainRun,summarizeTerrainRun} from './terrainRunRegistry';
import {terrainParametersForOperation} from './terrainRunParameters';
import {loadTerrainResults,cacheTerrainResult,deleteTerrainResult,markTerrainResultSaved,type PersistedTerrainResult} from './terrainResultStore';
import WorkspaceToolShelf from './WorkspaceToolShelf';
import {terrainFetchBounds,terrainGeometryBounds,terrainFetchBudget,terrainBoundsOverlap,terrainRasterMatchesTarget,describeTerrainBounds,preferredTerrainFetchScope,terrainSupportsUSGS,recommendDEMResolution,availableDEMResolutions,type FetchScope,type TerrainBBox} from './terrainSource';

function MeshView({mesh}:{mesh:TerrainMesh}){
  const canvas=useRef<HTMLCanvasElement>(null);
  const [angle,setAngle]=useState(-.6);
  const [tilt,setTilt]=useState(.9);
  const [exaggeration,setExaggeration]=useState(1);
  const drag=useRef<{x:number;y:number}|null>(null);
  useEffect(()=>{
    const node=canvas.current,ctx=node?.getContext('2d');if(!node||!ctx)return;
    const valid=mesh.heights.filter((v):v is number=>v!==null);
    if(!valid.length)return;
    const lo=Math.min(...valid),hi=Math.max(...valid);
    const span=Math.max(mesh.cols*mesh.dx_m,mesh.rows*mesh.dy_m,(hi-lo)*exaggeration,1);
    const scale=260/span;
    const project=(r:number,c:number)=> {
      const h=mesh.heights[r*mesh.cols+c];
      if(h===null)return null;
      const x=(c-(mesh.cols-1)/2)*mesh.dx_m,y=(r-(mesh.rows-1)/2)*mesh.dy_m;
      const xx=x*Math.cos(angle)-y*Math.sin(angle),yy=x*Math.sin(angle)+y*Math.cos(angle);
      const z=(h-(hi+lo)/2)*exaggeration;
      return {x:160+xx*scale,y:108+(yy*Math.cos(tilt)-z*Math.sin(tilt))*scale,depth:yy*Math.sin(tilt)+z*Math.cos(tilt),h};
    };
    const cells:Array<{points:Array<NonNullable<ReturnType<typeof project>>>;depth:number;h:number}>=[];
    for(let r=0;r+1<mesh.rows;r++)for(let c=0;c+1<mesh.cols;c++){
      const p=[project(r,c),project(r,c+1),project(r+1,c+1),project(r+1,c)];
      if(p.some(v=>v===null))continue;
      const q=p as Array<NonNullable<ReturnType<typeof project>>>;
      cells.push({points:q,depth:q.reduce((sum,v)=>sum+v.depth,0)/4,h:q.reduce((sum,v)=>sum+v.h,0)/4});
    }
    ctx.fillStyle='#edf2f5';ctx.fillRect(0,0,320,220);
    cells.sort((a,b)=>b.depth-a.depth);
    for(const cell of cells){
      ctx.beginPath();cell.points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.closePath();
      const ratio=(cell.h-lo)/(hi-lo||1);
      ctx.fillStyle='hsl('+(120-95*ratio)+' 38% '+(35+30*ratio)+'%)';
      ctx.fill();ctx.strokeStyle='#203a3b45';ctx.lineWidth=.4;ctx.stroke();
    }
  },[mesh,angle,tilt,exaggeration]);
  return <div className="dem-mesh">
    <canvas ref={canvas} width={320} height={220} aria-label="Interactive 3D terrain preview" data-renderer="canvas2d"
      onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);drag.current={x:e.clientX,y:e.clientY};}}
      onPointerMove={e=>{if(!drag.current)return;const dx=e.clientX-drag.current.x,dy=e.clientY-drag.current.y;
        setAngle(a=>a+dx*.012);setTilt(t=>Math.max(.2,Math.min(1.45,t+dy*.008)));drag.current={x:e.clientX,y:e.clientY};}}
      onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}/>
    <label>Vertical exaggeration <input aria-label="Terrain vertical exaggeration" type="range" min="1" max="5" step=".5"
      value={exaggeration} onChange={e=>setExaggeration(Number(e.target.value))}/></label>
    <div className="survey-action-bar"><small>Drag to rotate · elevations in meters</small><button onClick={()=>{setAngle(-.6);setTilt(.9);setExaggeration(1);}}>Reset view</button></div>
  </div>;
}

type Operation=TerrainOperation|'slope'|'profile';
type ProfileResult=Awaited<ReturnType<typeof terrainProfile>>;
type TerrainRecord=PersistedTerrainResult;
const modes:Array<{id:Operation;title:string}>=[
 {id:'slope',title:'Slope / aspect'},{id:'profile',title:'Elevation profile'},{id:'contours',title:'Contours'},{id:'dem_difference',title:'DEM difference'},
 {id:'volume',title:'Cut / fill'},{id:'visibility',title:'Viewshed'},{id:'watershed',title:'Watershed (D8)'},{id:'mesh',title:'3D terrain'},
 {id:'distribution',title:'Elevation distribution'},
 {id:'elevation',title:'Elevation map'},{id:'slope_map',title:'Slope map'},{id:'aspect_map',title:'Aspect map'},{id:'hillshade',title:'Hillshade'},
 {id:'tri',title:'Ruggedness (TRI)'},{id:'tpi',title:'Position (TPI)'},{id:'curvature',title:'Curvature (Laplacian)'},{id:'plan_curvature',title:'Plan curvature'},{id:'profile_curvature',title:'Profile curvature'},
 {id:'flow_direction',title:'Flow direction'},{id:'flow_accumulation',title:'Flow accumulation'},
 {id:'flow_accumulation_mfd',title:'MFD accumulation'},{id:'stream_order',title:'Stream order (Strahler)'},
 {id:'streams',title:'Drainage network'},{id:'viewshed_multi',title:'Multi-observer viewshed'},
 {id:'cutfill_map',title:'Cut / fill map'},{id:'suitability',title:'Site suitability'},{id:'least_cost',title:'Least-cost route'},{id:'cross_sections',title:'Cross sections'}
];
const categories:Record<string,Operation[]>={
 Quick:['slope','profile','contours','volume','visibility','watershed','mesh','distribution'],
 Surface:['elevation','slope_map','aspect_map','hillshade','tri','tpi','curvature','plan_curvature','profile_curvature','distribution','contours','dem_difference'],
 Hydrology:['flow_direction','flow_accumulation','flow_accumulation_mfd','streams','stream_order','watershed'],
 Visibility:['visibility','viewshed_multi'],
 Engineering:['profile','cross_sections','volume','cutfill_map','suitability','least_cost'],
};
const units:Record<string,string>={cut_m3:'m³',fill_m3:'m³',net_cut_m3:'m³',covered_grid_area_m2:'m²',reference_elevation_m:'m',
 contour_lines:'',contour_levels:'',product_valid_cells:'',product_p10:'',product_p50:'',product_p90:'',product_std:'',observer_count:'',visible_by_all_cells:'',channel_cells:'',max_stream_order:'',mfd_exponent:'',stream_threshold_cells:'',flat_cells:'',directional_cells:'',route_cells:'',dataset_overlap_pct:'%',valid_grid_pct:'%',comparison_coverage_pct:'%',interval_m:'m',visible_cells:'',visible_grid_area_m2:'m²',unknown_cells:'',upstream_cells:'',upstream_grid_area_m2:'m²',elevation_change_mean_m:'m',elevation_change_min_m:'m',elevation_change_max_m:'m',elevation_change_rmse_m:'m',elevation_change_mae_m:'m',raised_volume_m3:'m³',lowered_volume_m3:'m³',net_elevation_volume_m3:'m³',maximum_fill_depth_m:'m',total_fill_depth_m:'m',conditioning_fill_volume_m3:'m³',minimum_m:'m',maximum_m:'m',mean_m:'m',median_m:'m',stddev_m:'m',p10_m:'m',p90_m:'m',relief_m:'m',circular_mean_aspect_deg:'°'};
const names:Record<string,string>={cut_m3:'Cut',fill_m3:'Fill',net_cut_m3:'Net cut',covered_grid_area_m2:'Grid area',reference_elevation_m:'Reference',
 contour_lines:'Contour paths',contour_levels:'Elevation levels',product_p10:'10th percentile',product_p50:'Median',product_p90:'90th percentile',product_std:'Standard deviation',dataset_overlap_pct:'DEM footprint coverage',valid_grid_pct:'Valid grid coverage',interval_m:'Interval',visible_cells:'Visible cells',visible_grid_area_m2:'Visible area',unknown_cells:'Unknown cells',
 observer_count:'Observers',visible_by_all_cells:'Visible from all observers',
 visible_any_known_cells:'Visible from at least one confirmed observer',
 channel_cells:'Channel cells',max_stream_order:'Maximum Strahler order',mfd_exponent:'MFD slope exponent',stream_threshold_cells:'Stream threshold',
 upstream_cells:'Upstream cells',upstream_grid_area_m2:'Catchment area',comparison_cells:'Matched cells',comparison_coverage_pct:'Coverage (%)',increased_cells:'Raised cells',decreased_cells:'Lowered cells',unchanged_cells:'Unchanged cells',datum_labels_match:'Datum labels match (1=yes)',elevation_change_mean_m:'Mean elevation difference',elevation_change_min_m:'Minimum difference',elevation_change_max_m:'Maximum difference',elevation_change_rmse_m:'RMS difference (not accuracy)',elevation_change_mae_m:'Mean absolute difference',raised_volume_m3:'Raised volume',lowered_volume_m3:'Lowered volume',net_elevation_volume_m3:'Net volume',conditioned_cells:'Depression-filled cells',flat_routing_cells:'Numerically routed flat cells',outlet_cells:'Outlets',maximum_fill_depth_m:'Max fill depth',conditioning_fill_volume_m3:'Conditioning volume',total_fill_depth_m:'Sum of fill depths',minimum_m:'Lowest elevation',maximum_m:'Highest elevation',mean_m:'Mean elevation',median_m:'Median elevation',stddev_m:'Standard deviation',p10_m:'10th percentile',p90_m:'90th percentile',relief_m:'Relief',hypsometric_integral:'Hypsometric integral',circular_mean_aspect_deg:'Mean downslope bearing',product_min:'Minimum',product_max:'Maximum',product_mean:'Mean',product_valid_cells:'Calculated raster cells'};
const fmt=(n:number)=>n.toLocaleString('en-US',{maximumFractionDigits:2});
interface Props{
 projectId:string|null;geometry:GeoJSON.Geometry|null;profileGeometry?:GeoJSON.LineString|null;raster:RasterAsset|null;imageRaster?:RasterAsset|null;active:boolean;connected:boolean;
 resultsTarget?:HTMLElement|null;
 operationsFooterTarget?:HTMLElement|null;
 resultsFooterTarget?:HTMLElement|null;
 exportTarget?:HTMLElement|null;
 viewport:[number,number,number,number]|null;
 localImport:boolean;refreshToken:number;origin:Position|null;picking:boolean;
 onSelectRaster:(r:RasterAsset|null)=>void;onDraw:(line:boolean)=>void;onClearProfile?:()=>void;onUseExtent:()=>void;onPick:()=>void;
 onFetchTarget?:(bbox:TerrainBBox|null)=>void;
 onFitSelectedArea?:()=>void;
 extentMode:boolean;onUseSelection:()=>void;
 onHover:(point:Position|null)=>void;onPreview:(g:GeoJSON.Feature[])=>void;onRasterPreview?:(layers:TerrainRasterLayer[])=>void;onSaved:()=>void;
 onProfileSamples?:(samples:ProfileResult['samples'])=>void;profileMapIndex?:number|null;
}
export default function TerrainWorkbench(p:Props){
 // Opening Terrain never preselects a calculation.
 const [operation,setOperation]=useState<Operation|null>(null);
 const [category,setCategory]=useState('Quick');
 // One non-scrolling page at a time; form values remain mounted in their panels.
 const [leftTab,setLeftTab]=useState<'source'|'tools'|'setup'|'process'>('source');
 const [assets,setAssets]=useState<RasterAsset[]>([]),[token,setToken]=useState('');
 const [resolution,setResolution]=useState<1|3|10|30|90>(30),[fetching,setFetching]=useState(false),[sourceInfo,setSourceInfo]=useState('');
 // The displayed fetch choice tracks a genuine selected area automatically.
 // An explicit dropdown choice takes precedence until the user changes it again.
 const [fetchChoice,setFetchChoice]=useState<'auto'|FetchScope>('auto');
 const fetchScope=fetchChoice==='auto'?preferredTerrainFetchScope(p.geometry):fetchChoice;
 const [interval,setInterval]=useState('10'),[reference,setReference]=useState('0');
 const [lon,setLon]=useState(''),[lat,setLat]=useState(''),[height,setHeight]=useState('1.7'),[target,setTarget]=useState('0');
 const [endLon,setEndLon]=useState(''),[endLat,setEndLat]=useState('');
 // Map-selected observers are independent of the selected study boundary.
 const [observerPoints,setObserverPoints]=useState<[string,string][]>([['',''],['','']]);
 const [comparisonId,setComparisonId]=useState('');
 const [demProcessMode,setDemProcessMode]=useState<DEMProcessMode>('clip'),[processSecond,setProcessSecond]=useState('');
 const [processResolution,setProcessResolution]=useState('30'),[processSampling,setProcessSampling]=useState<'nearest'|'bilinear'|'average'>('bilinear');
 const [maxSlope,setMaxSlope]=useState('30'),[minElevation,setMinElevation]=useState('-12000'),[maxElevation,setMaxElevation]=useState('12000'),[maxTri,setMaxTri]=useState('100');
 const [streamCells,setStreamCells]=useState('100'),[azimuth,setAzimuth]=useState('315'),[altitude,setAltitude]=useState('45');
 const [gradientMethod,setGradientMethod]=useState<'horn'|'zevenbergen_thorne'>('horn');
 const [slopeClasses,setSlopeClasses]=useState<'standard'|'detailed'|'broad'>('standard');
 const [mfdExponent,setMfdExponent]=useState('1.1');
 const [neighborhoodRadius,setNeighborhoodRadius]=useState('1');
 const [viewshedDistance,setViewshedDistance]=useState('0');
 const [viewshedAzimuth,setViewshedAzimuth]=useState('0');
 const [viewshedWidth,setViewshedWidth]=useState('360');
 const [routeModel,setRouteModel]=useState<'surface'|'distance'|'gentle'>('surface');
 const [meshSamples,setMeshSamples]=useState('256');
 const [streamOrderScheme,setStreamOrderScheme]=useState<'strahler'|'shreve'>('strahler');
 const [hillshadeMode,setHillshadeMode]=useState<'single'|'four_direction'>('single');
 const [flowRoutingMethod,setFlowRoutingMethod]=useState<'d8'|'dinf'>('d8');
 const [depressionMethod,setDepressionMethod]=useState<'fill'|'breach'>('fill');
 const [curvatureMethod,setCurvatureMethod]=useState<'finite_difference'|'quadratic'>('finite_difference');
 const [curvatureRadius,setCurvatureRadius]=useState('2');
 const [designEastGrade,setDesignEastGrade]=useState('0'),[designNorthGrade,setDesignNorthGrade]=useState('0');
 const [designMaxGrade,setDesignMaxGrade]=useState('0.3'),[elevationSigma,setElevationSigma]=useState('0');
 const [designCurvatureEast,setDesignCurvatureEast]=useState('0');
 const [designCurvatureCross,setDesignCurvatureCross]=useState('0');
 const [designCurvatureNorth,setDesignCurvatureNorth]=useState('0');
 const [dsmImageId,setDsmImageId]=useState(''),[optimizeObservers,setOptimizeObservers]=useState('0');
 const [externalInflowImageId,setExternalInflowImageId]=useState('');
 const [meshLod,setMeshLod]=useState(false);
 const [suitabilityModel,setSuitabilityModel]=useState<'binary'|'weighted'>('binary');
 const [suitabilitySlopeWeight,setSuitabilitySlopeWeight]=useState('0.5');
 const [suitabilityTriWeight,setSuitabilityTriWeight]=useState('0.25');
 const [suitabilityElevationWeight,setSuitabilityElevationWeight]=useState('0.25');
 const [fillSinks,setFillSinks]=useState(true),[considerCurvature,setConsiderCurvature]=useState(true),[refractionCoeff,setRefractionCoeff]=useState('0.13');
 const [sectionSpacing,setSectionSpacing]=useState('50'),[sectionWidth,setSectionWidth]=useState('20'),[drape,setDrape]=useState(false),[expanded,setExpanded]=useState(false);
 const [pickEnd,setPickEnd]=useState(false);
 const [records,setRecords]=useState<TerrainRecord[]>([]);
 const [resultCacheReady,setResultCacheReady]=useState(false);
 const [resultCacheError,setResultCacheError]=useState('');
 const [runHistory,setRunHistory]=useState(()=>readTerrainRuns(p.projectId));
 const [historyStorageError,setHistoryStorageError]=useState(false);
 useEffect(()=>{setHistoryStorageError(!writeTerrainRuns(p.projectId,runHistory));},[runHistory,p.projectId]);
 useEffect(()=>{
   let current=true;
   // App keys this component by project. Restore only its own outputs;
   // no historical layer is drawn until the user explicitly shows it.
   void loadTerrainResults(p.projectId).then(restored=>{
     if(!current)return;
     setRecords(old=>{
       const ids=new Set(old.map(r=>r.id));
       return [...restored.filter(r=>!ids.has(r.id)),...old].slice(-24);
     });
   }).catch(error=>{
     if(current)setResultCacheError(error instanceof Error?error.message:'Unable to restore Terrain results.');
   }).finally(()=>{if(current)setResultCacheReady(true);});
   return()=>{current=false;};
 },[p.projectId]);
 const [selectedRecord,setSelectedRecord]=useState<string|null>(null);
 const [resultTab,setResultTab]=useState<'overview'|'visual'|'details'>('overview');
 const [figureView,setFigureView]=useState('analysis');
 const [classMeasure,setClassMeasure]=useState<'cells'|'percent'|'area'>('cells');
 useEffect(()=>{setResultTab('overview');setFigureView('analysis');setExpanded(false);},[selectedRecord]);
 const [historyFocus,setHistoryFocus]=useState('');
 const [layerPage,setLayerPage]=useState(0);
 const layerPageSize=5;
 const layerPageCount=Math.max(1,Math.ceil(records.length/layerPageSize));
 const visibleLayerPage=Math.min(layerPage,layerPageCount-1);
 const [compareRecordId,setCompareRecordId]=useState('');
 const selected=records.find(r=>r.id===selectedRecord);
 const result=selected?.advanced??null,slope=selected?.slope??null,profile=selected?.profile??null;
 const researchFigures=[
   ...(result?.distribution?.length&&['distribution','elevation'].includes(result.operation)?[{id:'hypsometry',label:'Hypsometry',
     plot:<HypsometricPlot bins={result.distribution}/>}] : []),
   ...(profile?.samples?.length?[{id:'gradient',label:'Gradient',
     plot:<ProfileGradePlot samples={profile.samples}/>}] : []),
   ...(result?.raster?.legend?.length?[{id:'composition',label:'Composition',
     plot:<TerrainClassShare bins={result.raster.legend}/>},
     ...(['elevation','slope_map','hillshade','tri','tpi','curvature',
          'plan_curvature','profile_curvature','flow_accumulation',
          'flow_accumulation_mfd','stream_order','cutfill_map','dem_difference'].includes(result.operation)
        ?[{id:'cumulative',label:'Cumulative',
          plot:<TerrainCumulativeArea bins={result.raster.legend} cellAreaM2={result.cell_area_m2}/>}]:[])]:[]),
 ];
 const activeResearch=researchFigures.find(item=>item.id===figureView);
 // Show operation-critical metrics first; keep all scientific fields in More.
 const metricEntries=Object.entries(result?.metrics??{});
 const preferredMetricKeys:Record<string,string[]>={
   elevation:['product_min','product_max','product_p50','product_p90'],
   slope_map:['product_mean','product_p50','product_p90','product_std'],
   aspect_map:['circular_mean_aspect_deg','flat_cells','directional_cells'],
   contours:['contour_levels','contour_lines','interval_m'],
   hillshade:['product_min','product_max','product_mean'],
   flow_direction:['outlet_cells','flat_routing_cells','product_valid_cells'],
   flow_accumulation:['product_max','product_mean','outlet_cells'],
   flow_accumulation_mfd:['product_max','product_mean','mfd_exponent'],
   streams:['channel_cells','drainage_edges','vector_edges'],
   stream_order:['max_stream_order','channel_cells','stream_threshold_cells'],
   watershed:['upstream_cells','upstream_grid_area_m2'],
   visibility:['visible_cells','visible_grid_area_m2','unknown_cells'],
   viewshed_multi:['visible_cells','visible_by_all_cells','unknown_cells'],
   volume:['cut_m3','fill_m3','net_cut_m3'],
   cutfill_map:['cut_m3','fill_m3','net_cut_m3'],
   least_cost:['route_length_m','route_cells','route_cost'],
   dem_difference:['elevation_change_mean_m','comparison_coverage_pct','elevation_change_rmse_m'],
 };
 const priority=preferredMetricKeys[result?.operation??'']??[];
 const preferred=metricEntries.filter(([key])=>priority.includes(key));
 const featuredMetrics=(preferred.length?preferred:metricEntries.filter(([key])=>
   !['dataset_overlap_pct','valid_grid_pct','product_valid_cells'].includes(key))).slice(0,4);
 const shownKeys=new Set(featuredMetrics.map(([key])=>key));
 const additionalMetrics=metricEntries.filter(([key])=>!shownKeys.has(key));
 const activeProfileSamples=profile?.samples??null;
 const comparableRuns=selected?records.filter(r=>r.id!==selected.id&&r.operation===selected.operation):[];
 const comparison=comparableRuns.find(r=>r.id===compareRecordId)??null;
 function physicalMetrics(r:TerrainRecord):Record<string,number>{
   if(r.advanced)return r.advanced.metrics;
   if(r.slope)return {mean_slope_deg:r.slope.mean_slope_deg,maximum_slope_deg:r.slope.maximum_slope_deg,
     mean_elevation_m:r.slope.elevation_mean_m};
   if(r.profile){const values=r.profile.samples.map(p=>p.elevation_m).filter((n):n is number=>n!==null&&Number.isFinite(n));
     return {length_m:r.profile.length_m,...(values.length?{mean_elevation_m:values.reduce((a,b)=>a+b,0)/values.length}:{})};}
   return {};
 }
 const matchingStudy=!!selected&&!!comparison&&sameGeometryFootprint(selected.geometry,comparison.geometry);
 const comparisons=matchingStudy&&selected&&comparison?
   terrainMetricDifferences(physicalMetrics(selected),physicalMetrics(comparison)):[];
 const analysisRequest=useRef<AbortController|null>(null);
 const alive=useRef(true);
 const sourceIntent=useRef(0);
 const fetchAbort=useRef<AbortController|null>(null);
 const [verticalConfirmed,setVerticalConfirmed]=useState(false);
 const [live,setLive]=useState(false),[busy,setBusy]=useState(false),[importing,setImporting]=useState(false);
 const [error,setError]=useState(''),[info,setInfo]=useState('');
 const selectedGeometry=useMemo(()=>terrainGeometryBounds(p.geometry),[p.geometry]);
 const selectedAreaKey=JSON.stringify([p.geometry?.type,selectedGeometry]);
 const previousAreaKey=useRef(selectedAreaKey);
 // A new polygon is a new download intent. Do not retain an explicit
 // 'viewport' override from an earlier unrelated place or workflow.
 useEffect(()=>{
   if(previousAreaKey.current!==selectedAreaKey){
     previousAreaKey.current=selectedAreaKey;
     setFetchChoice('auto');
   }
 },[selectedAreaKey]);
 const fetchArea=useMemo(()=>terrainFetchBounds(p.viewport,p.geometry,fetchScope),[p.viewport,p.geometry,fetchScope]);
 const supportsUSGS=terrainSupportsUSGS(fetchArea);
 const recommendedResolution=recommendDEMResolution(fetchArea);
 const supportedResolutions=availableDEMResolutions(fetchArea);
 // Never advertise US-only 3DEP coverage at global locations such as HKG.
 useEffect(()=>{
   if(fetchArea&&!supportsUSGS&&resolution<30){
     setResolution(30);
     setInfo('USGS 3DEP is unavailable here. Selected Copernicus GLO-30; requested output grid is not native resolution.');
   }
 },[supportsUSGS,resolution,fetchArea?.[0],fetchArea?.[1],fetchArea?.[2],fetchArea?.[3]]);
 const budget=terrainFetchBudget(fetchArea,resolution);
 const fetchKey=JSON.stringify([fetchScope,fetchArea,resolution]);
 const currentFetchKey=useRef(fetchKey);currentFetchKey.current=fetchKey;
 const sequence=useRef(0),latest=useRef(p);latest.current=p;
 const area=p.geometry?.type==='Polygon'||p.geometry?.type==='MultiPolygon';
 const needsPoint=operation==='watershed'||operation==='visibility'||operation==='least_cost';
 const lineOperation=operation==='profile'||operation==='cross_sections';
 // A manually drawn profile line is independent; existing saved line features also remain valid.
 const analysisGeometry=lineOperation?(p.profileGeometry??(p.geometry?.type==='LineString'?p.geometry:null)):p.geometry;
 const correctShape=lineOperation?analysisGeometry?.type==='LineString':area;
 const dem=p.raster?.bands===1?p.raster:null;
 const analysisBounds=useMemo(()=>terrainGeometryBounds(analysisGeometry??null),[analysisGeometry]);
 const sourceMismatch=!!dem&&!!analysisBounds&&!terrainRasterMatchesTarget(dem,analysisBounds);
 const mapMismatch=!!dem&&!!p.viewport&&!terrainBoundsOverlap(dem.bbox,p.viewport);
 const verified=!!dem&&(/Copernicus DEM GLO-|USGS 3DEP Bare Earth DEM/.test(dem.provenance)||verticalConfirmed);
 const validNumber=(value:string,min:number,max:number)=>value.trim()!==''&&Number.isFinite(Number(value))&&Number(value)>=min&&Number(value)<=max;
 const multiObserversValid=observerPoints.length>=2&&observerPoints.length<=(Number(optimizeObservers)>0?12:4)&&
   observerPoints.every(([x,y])=>validNumber(x,-180,180)&&validNumber(y,-90,90))&&
   new Set(observerPoints.map(([x,y])=>Number(x)+','+Number(y))).size===observerPoints.length;
 const parametersValid=(operation!=='viewshed_multi'||multiObserversValid&&validNumber(optimizeObservers,0,4)&&Number.isInteger(Number(optimizeObservers))&&Number(optimizeObservers)<=observerPoints.length)&&
   (!['volume','cutfill_map'].includes(operation??'')||validNumber(designEastGrade,-1,1)&&validNumber(designNorthGrade,-1,1)&&
     validNumber(designMaxGrade,.00001,1)&&Math.hypot(Number(designEastGrade),Number(designNorthGrade))<=Number(designMaxGrade)+1e-12&&
     validNumber(elevationSigma,0,10000)&&[designCurvatureEast,designCurvatureCross,designCurvatureNorth].every(n=>validNumber(n,-1,1)))&&
   (!['curvature','plan_curvature','profile_curvature'].includes(operation??'')||curvatureMethod!=='quadratic'||validNumber(curvatureRadius,1,4)&&Number.isInteger(Number(curvatureRadius)))&&
   (!['visibility','viewshed_multi'].includes(operation??'')||!dsmImageId||assets.some(a=>a.id===dsmImageId&&a.bands===1&&a.id!==dem?.id))&&
   (operation!=='flow_accumulation'||!externalInflowImageId||flowRoutingMethod==='dinf'&&assets.some(a=>a.id===externalInflowImageId&&a.bands===1&&a.id!==dem?.id))&&
   (operation!=='cross_sections'||validNumber(sectionSpacing,1,10000)&&validNumber(sectionWidth,1,2000))&&
   (operation!=='contours'||validNumber(interval,.01,1e6))&&
   (operation!=='dem_difference'||!!comparisonId&&comparisonId!==dem?.id&&assets.some(a=>a.id===comparisonId&&a.bands===1))&&
   ((operation!=='volume'&&operation!=='cutfill_map')||validNumber(reference,-12000,12000))&&
   (operation!=='least_cost'||validNumber(endLon,-180,180)&&validNumber(endLat,-90,90)&&validNumber(maxSlope,.01,90))&&
   (operation!=='suitability'||validNumber(maxSlope,0,90)&&validNumber(minElevation,-12000,12000)&&validNumber(maxElevation,-12000,12000)&&Number(minElevation)<=Number(maxElevation)&&validNumber(maxTri,0,100000)&&
      (suitabilityModel==='binary'||[suitabilitySlopeWeight,suitabilityTriWeight,suitabilityElevationWeight].every(n=>validNumber(n,0,100))&&
        [suitabilitySlopeWeight,suitabilityTriWeight,suitabilityElevationWeight].reduce((sum,w)=>sum+Number(w),0)>0))&&
   (!['streams','stream_order'].includes(operation??'')||validNumber(streamCells,1,1000000)&&Number.isInteger(Number(streamCells)))&&
   (operation!=='hillshade'||validNumber(azimuth,0,360)&&validNumber(altitude,0,90))&&
   (!needsPoint||validNumber(lon,-180,180)&&validNumber(lat,-90,90))&&
   (operation!=='flow_accumulation_mfd'||validNumber(mfdExponent,.5,8))&&
   (!['visibility','viewshed_multi'].includes(operation??'')||!considerCurvature||validNumber(refractionCoeff,0,.5))&&
   (!['visibility','viewshed_multi'].includes(operation??'')||validNumber(height,0,1000)&&validNumber(target,0,1000)&&
     validNumber(viewshedDistance,0,10000)&&validNumber(viewshedAzimuth,0,360)&&validNumber(viewshedWidth,.01,360))&&
   (!['tri','tpi'].includes(operation??'')||validNumber(neighborhoodRadius,1,4)&&Number.isInteger(Number(neighborhoodRadius)))&&
   (operation!=='mesh'||validNumber(meshSamples,64,512)&&Number.isInteger(Number(meshSamples)));
 const canRun=operation!==null&&p.connected&&resultCacheReady&&verified&&!!correctShape&&!sourceMismatch&&!mapMismatch&&parametersValid;
 useEffect(()=>{latest.current.onProfileSamples?.(activeProfileSamples??[]);},[activeProfileSamples]);
 const scientificParameters=terrainParametersForOperation(operation,{
   interval,reference,lon,lat,height,target,endLon,endLat,
   maxSlope,minElevation,maxElevation,maxTri,streamCells,
   azimuth,altitude,sectionSpacing,sectionWidth,fillSinks,mfdExponent,
   considerCurvature,refractionCoeff,comparisonId,observerPoints,drape,
   textureImageId:p.imageRaster?.id??null,gradientMethod,slopeClasses,
   neighborhoodRadius,viewshedDistance,viewshedAzimuth,viewshedWidth,
   routeModel,meshSamples,streamOrderScheme,hillshadeMode,
   flowRoutingMethod,depressionMethod,curvatureMethod,curvatureRadius,
   designEastGrade,designNorthGrade,designMaxGrade,elevationSigma,
   designCurvatureEast,designCurvatureCross,designCurvatureNorth,
   dsmImageId,optimizeObservers,meshLod,externalInflowImageId,
   suitabilityModel,suitabilitySlopeWeight,suitabilityTriWeight,suitabilityElevationWeight,
 });
 // Only edits to the actual operation inputs invalidate a scientific run.
 const inputKey=JSON.stringify([dem?.id,analysisGeometry,operation,scientificParameters]);
 const inputsChanged=!!selected&&selected.inputKey!==inputKey;
 useEffect(()=>{
   setVerticalConfirmed(false);sourceIntent.current++;
   // Historical calculations remain available, but never overlay a newly selected source.
   setRecords(old=>old.some(r=>r.visible&&r.source.id!==dem?.id)?old.map(r=>r.source.id!==dem?.id?{...r,visible:false}:r):old);
   setSelectedRecord(null);setExpanded(false);
 },[dem?.id]);
 // A map move to an unrelated location must not publish a stale analysis result.
 useEffect(()=>{if(mapMismatch&&analysisRequest.current)cancelAnalysis();},[mapMismatch]);
 // Map extent outline and request coordinates always derive from the same explicit target.
 useEffect(()=>{latest.current.onFetchTarget?.(p.active?fetchArea:null);},[fetchKey,p.active]);
 // Changing the download target aborts the old request rather than selecting stale data.
 useEffect(()=>()=>{fetchAbort.current?.abort();},[fetchKey]);
 useEffect(()=>()=>{latest.current.onFetchTarget?.(null);},[]);
 // Published result layers are independent from the currently selected input.
 useEffect(()=>{latest.current.onPreview(records.filter(r=>r.visible).flatMap(r=>r.advanced?.features??[]));latest.current.onRasterPreview?.(records.flatMap(r=>r.visible&&r.advanced?.raster?[{id:r.id,title:r.title,raster:r.advanced.raster,opacity:r.opacity,resampling:r.resampling}]:[]));},[records]);
 useEffect(()=>{
   if(!p.active||!p.connected)return;
   let current=true;
   listImagery().then(list=>{if(current)setAssets(list.filter(a=>a.bands===1));})
     .catch(e=>{if(current)setError(e instanceof Error?e.message:String(e));});
   return()=>{current=false;};
 },[p.active,p.connected,p.refreshToken]);
 useEffect(()=>{
  if(!p.origin)return;
  if(operation==='viewshed_multi'){
   const longitude=String(p.origin[0]),latitude=String(p.origin[1]);
   setObserverPoints(old=>{
    const next=old.map(point=>[...point] as [string,string]);
    let index=next.findIndex(([x,y])=>!x.trim()||!y.trim());
    if(index<0&&next.length<4)index=next.length;
    if(index<0)return old;
    if(index===next.length)next.push([longitude,latitude]);
    else next[index]=[longitude,latitude];
    return next;
   });
  }else if(pickEnd){
   setEndLon(String(p.origin[0]));setEndLat(String(p.origin[1]));setPickEnd(false);
  }else{
   setLon(String(p.origin[0]));setLat(String(p.origin[1]));
  }
 },[p.origin]);
 function cancelAnalysis(){
   sequence.current++;analysisRequest.current?.abort();analysisRequest.current=null;setBusy(false);
 }
 async function run(){
   if(!operation||!canRun||!dem||!analysisGeometry||analysisRequest.current)return;
   if(records.length>=24&&!records.some(r=>r.inputKey===inputKey&&!r.saved)){
     setLive(false);setError('Result limit reached (24). Export or remove a result before another calculation.');return;
   }
   // A live run replaces only the previous run with identical input, never
   // hidden or historical results from different source geometry.
   // The request guard above excludes concurrent calculations.
   const controller=new AbortController();analysisRequest.current=controller;
   const ticket=++sequence.current;setBusy(true);setError('');setInfo('');
   const parameters=structuredClone(scientificParameters);
   const record:TerrainRecord={id:crypto.randomUUID(),title:modes.find(m=>m.id===operation)!.title,
     operation,source:dem,geometry:structuredClone(analysisGeometry),inputKey,parameters,visible:true,opacity:.5,
     referenceSource:operation==='dem_difference'?assets.find(a=>a.id===comparisonId):undefined,
     resampling:operation==='slope_map'||operation==='hillshade'?'linear':'nearest',createdAt:Date.now()};
   try{
     if(operation==='profile')record.profile=await terrainProfile(dem.id,analysisGeometry,controller.signal);
     else if(operation==='slope')record.slope=await analyzeTerrain(dem.id,analysisGeometry,controller.signal,gradientMethod);
     else record.advanced=await advancedTerrain({image_id:dem.id,geometry:analysisGeometry,operation,
       interval:Number(interval),reference:Number(reference),point:needsPoint?[Number(lon),Number(lat)]:null,
       observer_height:Number(height),target_height:Number(target),end_point:operation==='least_cost'?[Number(endLon),Number(endLat)]:null,
       max_slope:Number(maxSlope),min_elevation:Number(minElevation),max_elevation:Number(maxElevation),max_tri:Number(maxTri),stream_cells:Number(streamCells),azimuth:Number(azimuth),altitude:Number(altitude),section_spacing:Number(sectionSpacing),section_width:Number(sectionWidth),fill_sinks:fillSinks,consider_curvature:considerCurvature,refraction_coeff:Number(refractionCoeff),comparison_image_id:operation==='dem_difference'?comparisonId:null,
        observer_points:operation==='viewshed_multi'?observerPoints.map(([x,y])=>[Number(x),Number(y)] as [number,number]):null,
        texture_image_id:operation==='mesh'&&drape&&p.imageRaster&&p.imageRaster.bands>=3?p.imageRaster.id:null,
         gradient_method:gradientMethod,slope_classes:slopeClasses,mfd_exponent:Number(mfdExponent),
         neighborhood_radius:Number(neighborhoodRadius),
         max_distance_m:Number(viewshedDistance),view_azimuth:Number(viewshedAzimuth),
         view_width:Number(viewshedWidth),route_model:routeModel,
         mesh_samples:Number(meshSamples),stream_order_scheme:streamOrderScheme,hillshade_mode:hillshadeMode,
         flow_routing_method:flowRoutingMethod,depression_method:depressionMethod,
         curvature_method:curvatureMethod,curvature_radius:Number(curvatureRadius),
         design_east_grade:Number(designEastGrade),design_north_grade:Number(designNorthGrade),
         design_max_grade:Number(designMaxGrade),elevation_sigma_m:Number(elevationSigma),
         design_curvature_east:Number(designCurvatureEast),design_curvature_cross:Number(designCurvatureCross),
         design_curvature_north:Number(designCurvatureNorth),
         optimize_observers:operation==='viewshed_multi'?Number(optimizeObservers):0,
         dsm_image_id:['visibility','viewshed_multi'].includes(operation)?dsmImageId||null:null,
         mesh_lod:operation==='mesh'&&meshLod,
         suitability_model:suitabilityModel,
         suitability_weights:[Number(suitabilitySlopeWeight),Number(suitabilityTriWeight),Number(suitabilityElevationWeight)],
         external_inflow_image_id:operation==='flow_accumulation'&&flowRoutingMethod==='dinf'?externalInflowImageId||null:null},controller.signal);
     if(ticket!==sequence.current||controller.signal.aborted)return;
     // Commit scientific data before reporting a completed run. An immediate
     // reload or project switch must never race a pending cache write.
     let cached=false;
     try{
       await cacheTerrainResult(p.projectId,record);
       cached=true;
       if(alive.current)setResultCacheError('');
     }catch(error){
       if(alive.current)setResultCacheError(error instanceof Error?error.message:'Terrain cache write failed.');
     }
     if(ticket!==sequence.current||controller.signal.aborted){
       // A superseded/cancelled result must not reappear from the cache.
       if(cached)await deleteTerrainResult(p.projectId,record.id);
       return;
     }
     setRecords(old=>{
       const kept=old.filter(r=>r.inputKey!==inputKey||r.saved);
       // Show only the newest derived raster by default. Older results remain
       // available but must be explicitly enabled to avoid opaque stacking.
       return [...kept.map(r=>r.advanced?.raster?{...r,visible:false}:r),record];
     });
     setRunHistory(old=>insertTerrainRun(old,summarizeTerrainRun(
       record.id,record.createdAt,record.operation,record.source,record.geometry,
       physicalMetrics(record),record.referenceSource,parameters,
     )));
     setSelectedRecord(record.id);latest.current.onHover(null);
   }catch(e){if(ticket===sequence.current&&!controller.signal.aborted)setError(e instanceof Error?e.message:'Terrain analysis failed.');}
   finally{if(ticket===sequence.current){setBusy(false);analysisRequest.current=null;}}
 }
 useEffect(()=>{
   cancelAnalysis();setError('');setInfo('');latest.current.onHover(null);
   if(!live||!canRun||!p.active)return;
   const timer=window.setTimeout(()=>void run(),450);
   return()=>{window.clearTimeout(timer);sequence.current++;analysisRequest.current?.abort();};
 },[inputKey,live,p.connected,p.active,verified]);
 useEffect(()=>{
   alive.current=true;
   return()=>{alive.current=false;sequence.current++;sourceIntent.current++;analysisRequest.current?.abort();fetchAbort.current?.abort();};
 },[]);
 async function importDEM(e:ChangeEvent<HTMLInputElement>){
   const file=e.target.files?.[0];e.target.value='';if(!file)return;
   const ticket=++sourceIntent.current;
   setImporting(true);setError('');
   try{
     if(!p.localImport&&!token.trim())throw Error('Enter import access token.');
     const item=await uploadImagery(file,token);
     if(!alive.current||ticket!==sourceIntent.current)return;
     if(item.bands!==1)throw Error('Select a single-band DEM, not RGB imagery.');
     setAssets(old=>[item,...old.filter(v=>v.id!==item.id)]);
     latest.current.onSelectRaster(item);
   }catch(e){if(alive.current&&ticket===sourceIntent.current)setError(e instanceof Error?e.message:String(e));}
   finally{if(alive.current)setImporting(false);}
 }
 async function processDEM(){
   if(!dem||!p.connected||importing||fetching)return;
   const polygon=p.geometry?.type==='Polygon'||p.geometry?.type==='MultiPolygon'?p.geometry:null;
   if(demProcessMode==='clip'&&!polygon){setError('Select a polygon to clip DEM.');return;}
   if(demProcessMode==='mosaic'&&(!processSecond||processSecond===dem.id)){setError('Choose a different second DEM for mosaic.');return;}
   const spacing=Number(processResolution);
   if(!Number.isFinite(spacing)||spacing<1||spacing>1000){setError('DEM output resolution must be 1–1,000 m.');return;}
   const ticket=++sourceIntent.current;
   setImporting(true);setError('');setInfo('');
   try{
     if(!p.localImport&&!token.trim())throw Error('Enter import access token.');
     const data=await prepareDEM({
       image_ids:demProcessMode==='mosaic'?[dem.id,processSecond]:[dem.id],
       mode:demProcessMode,resolution_m:spacing,sampling:processSampling,
       geometry:demProcessMode==='clip'?polygon:null
     },token);
     if(!alive.current||ticket!==sourceIntent.current)return;
     setAssets(old=>[data.asset,...old.filter(a=>a.id!==data.asset.id)]);
     latest.current.onSelectRaster(data.asset);
     setInfo('DEM '+data.operation+' · '+data.valid_cells.toLocaleString()+'/'+data.total_cells.toLocaleString()+' valid cells · '+data.warning);
   }catch(e){if(alive.current&&ticket===sourceIntent.current)setError(e instanceof Error?e.message:String(e));}
   finally{if(alive.current)setImporting(false);}
 }
 async function fetchDEM(){
   if(!p.connected||fetching||importing)return;
   const bbox=fetchArea,requestKey=currentFetchKey.current;
   if(!bbox){setError(fetchScope==='selection'?'Select a polygon or line before downloading.':'Map bounds unavailable. Zoom to the target location.');return;}
   if(budget?.warning){setError(budget.warning);return;}
   const ticket=++sourceIntent.current;
   const controller=new AbortController();fetchAbort.current=controller;
   setFetching(true);setError('');setSourceInfo('');
   try{
     if(!p.localImport&&!token.trim())throw Error('Enter import access token.');
     const data=await fetchPublicDEM(bbox,resolution,token,controller.signal);
     if(!alive.current||ticket!==sourceIntent.current)return;
     if(currentFetchKey.current!==requestKey){
       setInfo('Download completed, but the target changed. Old DEM was not selected.');
       return;
     }
     if(JSON.stringify(data.requested_bbox)!==JSON.stringify(bbox)||!terrainRasterMatchesTarget(data.asset,bbox)){
       throw Error('Downloaded DEM does not cover the displayed target coordinates. Source rejected.');
     }
     setAssets(old=>[data.asset,...old.filter(item=>item.id!==data.asset.id)]);
     latest.current.onSelectRaster(data.asset);
     setSourceInfo((resolution<30?'USGS 3DEP · requested '+resolution+' m grid':'GLO-'+resolution+' · DSM')+
       ' · '+data.valid_cells+'/'+data.total_cells+' cells'+(data.missing_tiles.length?' · partial coverage':'')+
       ' · '+data.valid_coverage_pct.toFixed(1)+'% valid · center '+((bbox[0]+bbox[2])/2).toFixed(5)+', '+((bbox[1]+bbox[3])/2).toFixed(5));
     if(data.warning)setInfo(data.warning);
   }catch(e){if(alive.current&&ticket===sourceIntent.current&&!controller.signal.aborted)setError(e instanceof Error?e.message:String(e));}
   finally{if(fetchAbort.current===controller)fetchAbort.current=null;if(alive.current)setFetching(false);}
 }
 async function save(){
   if(!p.projectId||!selected||selected.saved||busy||!result||result.features.length>512)return;
   const ticket=sequence.current;setBusy(true);setError('');
   const source=selected.source;
   try{
     const saved=await saveFeatureBatch(p.projectId,result.features.map((f,i)=>({
       geometry:f.geometry,name:String(f.properties.name||result.operation)+' '+(i+1),
       source:'DEM '+source.name,properties:{
         ...f.properties,source_image:source.id,operation:result.operation,
         terrain_run_id:selected.id,
         source_sha256:source.sha256??null,
         source_vertical_datum:source.vertical_datum??null,
         research_parameters:structuredClone(selected.parameters??{}),
       }
     })));
     if(alive.current){
       setRecords(old=>old.map(r=>r.id===selected.id?{...r,saved:true}:r));
       void markTerrainResultSaved(p.projectId,selected.id).catch(error=>{
         if(alive.current)setResultCacheError(error instanceof Error?error.message:'Unable to mark saved result.');
       });
       latest.current.onSaved();
       if(ticket===sequence.current)setInfo('Saved '+saved.created+' terrain features.');
     }
   }catch(e){if(ticket===sequence.current)setError(e instanceof Error?e.message:'Save failed.');}
   finally{if(ticket===sequence.current)setBusy(false);}
 }
 function exportResult(){
   if(!selected)return;
   // A portable scientific manifest contains the exact input geometry and
   // parameters, not only its bounding rectangle. Keep pixel arrays in their
   // native GeoTIFF download rather than embedding base64 twice.
   const run={
     schema:'geofathom.terrain-run.v2',
     id:selected.id,operation:selected.operation,
     created_at:new Date(selected.createdAt).toISOString(),
     geometry:structuredClone(selected.geometry),
     parameters:structuredClone(selected.parameters??{}),
     source:{
       id:selected.source.id,name:selected.source.name,
       sha256:selected.source.sha256??null,
       crs:selected.source.crs,bbox:selected.source.bbox,
       vertical_unit:selected.source.vertical_unit??null,
       vertical_datum:selected.source.vertical_datum??null,
       acquired_at:selected.source.acquired_at,
       provenance:selected.source.provenance,
     },
     reference:selected.referenceSource?{
       id:selected.referenceSource.id,name:selected.referenceSource.name,
       sha256:selected.referenceSource.sha256??null,
       crs:selected.referenceSource.crs,
       vertical_datum:selected.referenceSource.vertical_datum??null,
       provenance:selected.referenceSource.provenance,
     }:null,
   };
   let payload:unknown;
   let extension='.json';
   if(result?.features.length){
     // A .geojson file must be a valid FeatureCollection. Previous exports
     // sometimes used that suffix for a non-GeoJSON analysis object.
     payload={type:'FeatureCollection',features:result.features,
       geofathom_run:run,geofathom_metrics:result.metrics,
       geofathom_warning:result.warning};
     extension='.geojson';
   }else if(result){
     payload={...result,
       raster:result.raster?{...result.raster,png:undefined,geotiff:undefined,
         export_hint:'Download the separate georeferenced GeoTIFF'}:undefined,
       mesh:result.mesh?{...result.mesh,texture:result.mesh.texture?
         {...result.mesh.texture,png:undefined}:undefined}:undefined,
       geofathom_run:run};
   }else{
     payload={...(slope??profile??{}),geofathom_run:run};
   }
   const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{
     type:extension==='.geojson'?'application/geo+json':'application/json'}));
   const link=document.createElement('a');
   link.href=url;link.download='terrain-'+selected.operation+extension;
   document.body.appendChild(link);link.click();link.remove();
   window.setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 const resultActions=(result||slope||profile)&&selected?<div className="terrain-result-footer" aria-label="Terrain result actions">
   {result?.features.length? <button disabled={!p.projectId||busy||selected.saved||result.features.length>512}
     title={result.features.length>512?'Export GeoJSON for large contour outputs':'Save terrain features'}
     onClick={()=>void save()}>{selected.saved?'Saved to project':'Save terrain features'}</button>:null}
   {result&&(result.raster||result.features.length>0)&&<button onClick={()=>setRecords(old=>old.map(r=>r.id===selectedRecord?{...r,visible:!r.visible}:r))}>
     {selected.visible?'Hide':'Show on map'}</button>}
 </div>:null;
 const terrainFileActions=<div className="terrain-file-actions">
   {selected&&(result||slope||profile)&&<button type="button" onClick={exportResult}>Terrain result JSON</button>}
   {runHistory.length>0&&<button type="button" onClick={()=>{
     const url=URL.createObjectURL(new Blob([JSON.stringify(runHistory,null,2)],{type:'application/json'}));
     const a=document.createElement('a');a.href=url;a.download='terrain-run-history.json';
     document.body.appendChild(a);a.click();a.remove();
     window.setTimeout(()=>URL.revokeObjectURL(url),1000);
   }}>Terrain history JSON</button>}
 </div>;
 const runActions=operation?<div className="terrain-run-row">
   <button className="primary-tool" disabled={!canRun||busy} onClick={()=>void run()}>{busy?'Calculating…':'Run terrain operation'}</button>
   {busy&&<button onClick={()=>{setLive(false);cancelAnalysis();setInfo('Analysis request cancelled.');}}>Cancel</button>}
   <label><input aria-label="Live terrain updates" type="checkbox" checked={live} onChange={e=>setLive(e.target.checked)}/> Live</label>
 </div>:null;
 const monitor=<div className="terrain-monitor-content">
   {!!records.length&&<section className="terrain-run-list" aria-label="Analysis result layers">
     <div className="terrain-run-selector">
       <label>Result
         <select aria-label="Choose terrain result" value={selectedRecord??''} onChange={e=>{
           setSelectedRecord(e.target.value||null);setInfo('');latest.current.onHover(null);
         }}>
           <option value="">Choose result · {records.length}</option>
           {[...records].reverse().map(r=><option value={r.id} key={r.id}>
             {r.title} · {new Date(r.createdAt).toLocaleTimeString()}
           </option>)}
         </select>
       </label>
     </div>
   </section>}
   {resultCacheError&&<small role="alert" className="discovery-error">
     Result cache: {resultCacheError} Export active results before leaving this page.
   </small>}
   {(records.length>0||runHistory.length>0)&&<nav className="terrain-result-tabs" role="tablist"
     aria-label="Terrain result views" onKeyDown={event=>{
       const keys=['overview','visual','details'] as const;
       const position=keys.indexOf(resultTab);
       const next=event.key==='ArrowRight'?(position+1)%keys.length:
         event.key==='ArrowLeft'?(position+keys.length-1)%keys.length:
         event.key==='Home'?0:event.key==='End'?keys.length-1:-1;
       if(next<0)return;
       event.preventDefault();
       setResultTab(keys[next]);
       const items=event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]');
       items[next]?.focus();
     }}>
     {([
       ['overview','Overview'],['visual','Figures'],['details','Data'],
     ] as const).map(([key,label])=><button key={key} type="button" role="tab"
       aria-selected={resultTab===key} aria-controls="terrain-result-content"
       onClick={()=>setResultTab(key)}>{label}</button>)}
   </nav>}
   {resultTab==='details'&&<section className="terrain-outputs-list" aria-label="Terrain output layers">
     <details className="terrain-layer-manager">
       <summary>Layers · {records.length}</summary>
       <div className="terrain-result-layer-list">
         {[...records].reverse().slice(visibleLayerPage*layerPageSize,(visibleLayerPage+1)*layerPageSize)
           .map(record=><div key={record.id} className={'scratch-row '+(selectedRecord===record.id?'active':'')}>
           <input type="checkbox" aria-label={'Show '+record.title+' '+record.id}
             checked={record.visible} disabled={!record.advanced?.features.length&&!record.advanced?.raster}
             onChange={e=>setRecords(old=>old.map(r=>r.id===record.id?{...r,visible:e.target.checked}:r))}/>
           <button title={record.source.name} onClick={()=>{setSelectedRecord(record.id);setInfo('');latest.current.onHover(null);}}>
             {record.title} · {new Date(record.createdAt).toLocaleTimeString()}</button>
           <button aria-label={'Remove result '+record.title} onClick={()=>{
             setRecords(old=>old.filter(r=>r.id!==record.id));
             void deleteTerrainResult(p.projectId,record.id).catch(error=>{
               if(alive.current)setResultCacheError(error instanceof Error?error.message:'Unable to delete cached result.');
             });
             if(selectedRecord===record.id)setSelectedRecord(null);
           }}>×</button>
         </div>)}
       </div>
       {layerPageCount>1&&<div className="terrain-layer-pager" aria-label="Terrain layer pages">
         <button type="button" disabled={visibleLayerPage===0} onClick={()=>setLayerPage(p=>Math.max(0,p-1))}>Previous</button>
         <span>{visibleLayerPage+1} / {layerPageCount}</span>
         <button type="button" disabled={visibleLayerPage===layerPageCount-1}
           onClick={()=>setLayerPage(p=>Math.min(layerPageCount-1,p+1))}>Next</button>
       </div>}
     </details>

   </section>}
   {(result||slope||profile)&&<ResultPane expanded={expanded} onClose={()=>setExpanded(false)}>
     <div id="terrain-result-content" role="tabpanel" aria-label={resultTab[0].toUpperCase()+resultTab.slice(1)+' terrain result'} className="terrain-tab-content">
     <div className="section-heading">{selected?.title} <span><button onClick={()=>{if(expanded)setExpanded(false);else{setResultTab('visual');setExpanded(true);}}}>{expanded?'Close expanded':'Expand'}</button></span></div>
     {resultTab==='visual'&&researchFigures.length>0&&<nav className="terrain-figure-tabs" aria-label="Research figures">
       <button type="button" aria-pressed={figureView==='analysis'} onClick={()=>setFigureView('analysis')}>Analysis</button>
       {researchFigures.map(item=><button type="button" key={item.id} aria-pressed={figureView===item.id}
         onClick={()=>setFigureView(item.id)}>{item.label}</button>)}
     </nav>}
     {resultTab==='visual'&&activeResearch&&<div className="terrain-figure-stage">{activeResearch.plot}</div>}
     {inputsChanged&&<small role="status" className="discovery-error">Inputs changed since this run</small>}
     {resultTab==='details'&&<>
     {selected&&<details className="terrain-run-provenance" aria-label="Terrain run provenance">
       <summary>Source · {selected.id.slice(0,8)}</summary>
       <div className="terrain-source-details">
         <div>Operation: {selected.title}</div>
          {selected.parameters&&Object.keys(selected.parameters).length>0&&
            <div className="terrain-parameter-grid" aria-label="Terrain algorithm parameters">
              {Object.entries(selected.parameters).map(([key,value])=><div key={key}>
                <span>{key.replaceAll('_',' ')}</span>
                <strong>{Array.isArray(value)?JSON.stringify(value):String(value??'None')}</strong>
              </div>)}
            </div>}
         <div>Run: {new Date(selected.createdAt).toLocaleString()} · ID {selected.id}</div>
         <div>Input DEM: {selected.source.name}</div>
         <div>Source ID: {selected.source.id}</div>
         {selected.referenceSource&&<>
           <div>Reference DEM: {selected.referenceSource.name}</div>
           <div>Reference ID: {selected.referenceSource.id}</div>
           <div>Reference CRS: {selected.referenceSource.crs}</div>
           <div>Reference acquisition: {selected.referenceSource.acquired_at??'Not recorded'}</div>
           <div>Reference provenance: {selected.referenceSource.provenance}</div>
         </>}
         <div>Acquired: {selected.source.acquired_at??'Not recorded'}</div>
         <div>Source SHA-256: {selected.source.sha256??'Not recorded'}</div>
         <div>Declared vertical datum: {selected.source.vertical_datum??'Not declared'}</div>
         <div>Vertical unit: {selected.source.vertical_unit??'Unverified'}</div>
         <div>Grid: {selected.source.width} × {selected.source.height} · {selected.source.crs}</div>
         <div>Geographic footprint: {selected.source.bbox.map(n=>n.toFixed(5)).join(', ')}</div>
         <div>Provenance: {selected.source.provenance}</div>
         <small>Requested output spacing or pixel size does not establish native DEM accuracy.</small>
       </div>
     </details>}
     {selected&&comparableRuns.length>0&&<details className="terrain-run-comparison" aria-label="Compare terrain runs"><summary>Compare</summary>
       <label>Compare historical result
         <select aria-label="Compare terrain run" value={comparison?.id??''}
           onChange={e=>setCompareRecordId(e.target.value)}>
           <option value="">Choose prior run</option>
           {comparableRuns.map(r=><option key={r.id} value={r.id}>
             {r.source.name} · {new Date(r.createdAt).toLocaleTimeString()} · {r.id.slice(0,8)}
           </option>)}
         </select>
       </label>
       {comparison&&<>
         {!matchingStudy&&
           <small role="status">Different study geometry: numerical deltas are disabled because the sampling regions do not match.</small>}
         {(selected.source.id!==comparison.source.id||selected.source.crs!==comparison.source.crs||
           selected.source.width!==comparison.source.width||selected.source.height!==comparison.source.height)&&
           <small role="status">Different DEM source/grid: compare regional statistics only, not individual pixels or native resolution.</small>}
         <div className="terrain-metrics">
           {comparisons.map(m=><div key={m.key}><span>{names[m.key]??m.key.replaceAll('_',' ')}</span>
             <strong>{m.delta>0?'+':''}{fmt(m.delta)}</strong></div>)}
         </div>
         {!comparisons.length&&<small>No comparable metrics</small>}
       </>}
     </details>}
     </>}
     {slope&&<>
       {resultTab==='overview'&&<div className="terrain-metrics terrain-key-metrics">
       <div><span>Elevation range</span><strong>{fmt(slope.elevation_min_m)}–{fmt(slope.elevation_max_m)} m</strong></div>
       <div><span>Mean elevation</span><strong>{fmt(slope.elevation_mean_m)} m</strong></div>
       <div><span>Relief</span><strong>{fmt(slope.elevation_relief_m)} m</strong></div>
       <div><span>Mean slope</span><strong>{fmt(slope.mean_slope_deg)}°</strong></div>
       <div><span>Aspect</span><strong>{slope.mean_aspect_deg===null?'Flat':fmt(slope.mean_aspect_deg)+'°'}</strong></div>
     </div>}
       {resultTab==='visual'&&figureView==='analysis'&&<MetricBars label="Slope (degrees)" max={90} values={[{name:'Mean',value:slope.mean_slope_deg,color:'#3977aa'},{name:'Maximum',value:slope.maximum_slope_deg,color:'#d18b31'}]}/>}
       {resultTab==='details'&&<small className="compact-notice" title={slope.warning}>{slope.valid_pixels} valid cells · {slope.engine}</small>}
     </>}
     {resultTab==='visual'&&figureView==='analysis'&&profile&&<ProfilePlot samples={profile.samples} length={profile.length_m} onHover={p.onHover} mapIndex={p.profileMapIndex??null}/>}
     {resultTab==='overview'&&selected&&<div className="terrain-overview-context">
       <span>{selected.source.name}</span>
       <span>{new Date(selected.createdAt).toLocaleString()}</span>
     </div>}
     {resultTab==='overview'&&!result&&profile&&<div className="terrain-key-metrics">
       <div><span>Length</span><strong>{fmt(profile.length_m)} m</strong></div>
       <div><span>Samples</span><strong>{profile.samples.length}</strong></div>
     </div>}
     {result&&<>
       {resultTab==='overview'&&result.selection&&<small className="compact-notice">Selected candidate positions: {result.selection.selected_candidate_indices.map(i=>i+1).join(', ')} · marginal visible cells: {result.selection.marginal_visible_cells.join(', ')}{result.selection.optimizer&&` · exact optimum within candidates · ${result.selection.optimizer.combinations_checked} combinations checked` }</small>}
       {resultTab==='overview'&&<div className="terrain-metrics terrain-key-metrics">{featuredMetrics.map(([k,v])=><div key={k}><span>{names[k]??k.replaceAll('_',' ')}</span><strong>{fmt(v)} {units[k]??(['product_min','product_max','product_mean','product_std','product_p10','product_p50','product_p90'].includes(k)?(
          ['elevation','tpi','tri','cutfill_map','dem_difference'].includes(result.operation)?'m':
          ['slope_map','aspect_map'].includes(result.operation)?'°':
          result.operation==='flow_accumulation'?'cells':
           ['curvature','plan_curvature','profile_curvature'].includes(result.operation)?'m⁻¹':''):'')}</strong></div>)}</div>}
       {resultTab==='details'&&!!additionalMetrics.length&&<details className="terrain-metric-details" aria-label="Additional terrain metrics">
         <summary>More metrics · {additionalMetrics.length}</summary>
       <div className="terrain-metrics">{additionalMetrics.map(([k,v])=><div key={k}><span>{names[k]??k.replaceAll('_',' ')}</span><strong>{fmt(v)} {units[k]??(['product_min','product_max','product_mean','product_std','product_p10','product_p50','product_p90'].includes(k)?(
          ['elevation','tpi','tri','cutfill_map','dem_difference'].includes(result.operation)?'m':
          ['slope_map','aspect_map'].includes(result.operation)?'°':
          result.operation==='flow_accumulation'?'cells':
           ['curvature','plan_curvature','profile_curvature'].includes(result.operation)?'m⁻¹':''):'')}</strong></div>)}</div>
       </details>}
       {resultTab==='visual'&&figureView==='analysis'&&result.operation==='volume'&&<MetricBars label="Earthwork volume (m³)" values={[{name:'Cut',value:result.metrics.cut_m3,color:'#b87848'},{name:'Fill',value:result.metrics.fill_m3,color:'#3b82ab'}]}/>}
       {resultTab==='visual'&&figureView==='analysis'&&(result.operation==='visibility'||result.operation==='viewshed_multi')&&<MetricBars label="Visibility (cells)" values={[{name:'Visible',value:result.metrics.visible_cells,color:'#34885c'},{name:'Unknown',value:result.metrics.unknown_cells,color:'#9099a2'},{name:'Hidden',value:Math.max(0,result.valid_cells-result.metrics.visible_cells-result.metrics.unknown_cells),color:'#c17d55'}]}/>}
       {resultTab==='visual'&&figureView==='analysis'&&result.operation==='watershed'&&<MetricBars label="Catchment (cells)" values={[{name:'Upstream',value:result.metrics.upstream_cells,color:'#3687b9'},{name:'Other',value:Math.max(0,result.valid_cells-result.metrics.upstream_cells),color:'#9ba7ad'}]}/>}
       {resultTab==='visual'&&figureView==='analysis'&&result.distribution&&<ElevationDistribution bins={result.distribution}/>}
       {resultTab==='overview'&&result.raster&&<div className="terrain-quality-summary">
          <span>Classified {result.raster.valid_cells.toLocaleString()} / {result.valid_cells.toLocaleString()} valid DEM cells</span>
          <span>{(100*result.raster.valid_cells/Math.max(1,result.valid_cells)).toFixed(1)}% analysis coverage</span>
          <span>{(result.raster.valid_cells*result.cell_area_m2/1e6).toFixed(3)} km² classified</span>
        </div>}
       {resultTab==='overview'&&result.raster&&<img className="terrain-overview-preview" src={result.raster.png} alt="Terrain overview preview"/>}
       {resultTab==='visual'&&figureView==='analysis'&&result.raster&&<div className="terrain-profile-chart">
         <label className="terrain-opacity-control">Result opacity · {Math.round((selected?.opacity??.5)*100)}%
           <input aria-label="Terrain raster opacity" type="range" min="0" max="100" step="5"
             value={Math.round((selected?.opacity??.5)*100)}
             onChange={e=>{const opacity=Number(e.target.value)/100;setRecords(old=>old.map(r=>r.id===selectedRecord?{...r,opacity}:r));}}/>
         </label>
         <label className="terrain-opacity-control">Map display
           <select aria-label="Terrain raster resampling" value={selected?.resampling??'nearest'}
             onChange={e=>setRecords(old=>old.map(r=>r.id===selectedRecord?
               {...r,resampling:e.target.value as 'nearest'|'linear'}:r))}>
             <option value="linear">Smoothed preview</option>
             <option value="nearest">Exact class boundaries</option>
           </select>
         </label>

         <img src={result.raster.png} alt="Derived terrain raster" style={{width:'100%',maxHeight:180,objectFit:'contain'}}/>
         <label className="terrain-opacity-control">Class distribution measure
           <select aria-label="Terrain chart measure" value={classMeasure}
             onChange={e=>setClassMeasure(e.target.value as 'cells'|'percent'|'area')}>
             <option value="cells">Valid pixel count</option>
             <option value="percent">Share of classified area (%)</option>
             <option value="area">Projected grid area (km²)</option>
           </select>
         </label>
         <MetricBars label={classMeasure==='cells'?'Terrain class distribution (cells)':
           classMeasure==='percent'?'Terrain class distribution (valid %)':
           'Terrain class distribution (projected km²)'} values={result.raster.legend.map(b=>({
             name:b.label,color:b.color,value:classMeasure==='cells'?b.cells:
               classMeasure==='area'?b.cells*result.cell_area_m2/1e6:
               100*b.cells/Math.max(1,result.raster!.valid_cells),
           }))}/>
</div>}
       {resultTab==='visual'&&figureView==='analysis'&&result.operation==='aspect_map'&&result.raster&&<AspectRose bins={result.raster.legend}/>}
       {resultTab==='visual'&&figureView==='analysis'&&result.sections&&<SectionPlot sections={result.sections} onHover={p.onHover}/>}
       {resultTab==='visual'&&figureView==='analysis'&&result.mesh&&<GPUView mesh={result.mesh} fallback={<MeshView mesh={result.mesh}/>}
           tileSource={selected?{image_id:selected.source.id,geometry:selected.geometry}:undefined}/>}
       {resultTab==='details'&&result.raster&&<details className="terrain-metric-details" aria-label="Terrain class statistics">
         <summary>Class statistics · {result.raster.legend.length} classes</summary>
         <TerrainClassTable bins={result.raster.legend} cellAreaM2={result.cell_area_m2}/>
       </details>}
       {resultTab==='details'&&result.operation==='slope_map'&&result.raster&&result.valid_cells>result.raster.valid_cells&&
         <small className="compact-notice" aria-label="Slope edge cells explanation">
           {fmt(result.valid_cells-result.raster.valid_cells)} boundary cells excluded by the 3 × 3 slope calculation.
           Source DEM coverage and calculated-slope coverage are different measures.
         </small>}
       {resultTab==='details'&&result.quality&&
          <details className="terrain-result-quality" aria-label="Scientific validation status">
            <summary>Scientific validation · {result.quality.status.replaceAll('_',' ')}</summary>
            <div className="terrain-validation-grid">
              <div>Reference comparison: {result.quality.reference_validation.replaceAll('_',' ')}</div>
              <div>Uncertainty: {result.quality.uncertainty.replaceAll('_',' ')}</div>
              <div>Source overlap: {result.quality.source_overlap_pct.toFixed(2)}%</div>
              <div>Valid study cells: {result.quality.valid_study_cell_pct.toFixed(2)}%</div>
              {result.quality.derivative_coverage_pct!==null&&
                <div>Derived product coverage: {result.quality.derivative_coverage_pct.toFixed(2)}%</div>}
              <div>Area measurement: {result.quality.area_basis.replaceAll('_',' ')}</div>
              {typeof result.quality.projection_max_scale_error_pct==='number'&&Number.isFinite(result.quality.projection_max_scale_error_pct)&&
                <div>Max sampled map-distance distortion:
                  {' '}{result.quality.projection_max_scale_error_pct!.toFixed(3)}%</div>}
              {result.quality.flags.map(flag=><small key={flag} className="compact-notice">
                {flag.replaceAll('_',' ')}</small>)}
            </div>
          </details>}
        {resultTab==='details'&&<details className="terrain-result-quality" aria-label="Terrain method and quality">
         <summary>Quality · {result.valid_cells} DEM cells
           {Number.isFinite(result.metrics.dataset_overlap_pct)
             ?' · '+fmt(result.metrics.dataset_overlap_pct)+'% study-area overlap':''}
           {Number.isFinite(result.metrics.valid_grid_pct)
             ?' · '+fmt(result.metrics.valid_grid_pct)+'% valid selected cells':''}
         </summary>
         <p>{result.warning}</p>
         <small>Output units: {result.raster?.unit??'See metric labels'}
           · Declared vertical datum: {selected?.source.vertical_datum??'Unknown'}</small>
       </details>}
       {resultTab==='details'&&<div className="terrain-output-downloads">
         {result.raster&&<button onClick={()=>{const a=document.createElement('a');const data=Uint8Array.from(atob(result.raster!.geotiff),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([data],{type:'image/tiff'}));a.href=url;a.download=result.operation+'.tif';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}}>GeoTIFF</button>}
         {result.raster&&<button aria-label="Export terrain class CSV" onClick={()=>{
           const csv=terrainClassesCsv(result.raster!.legend,result.cell_area_m2);
           const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
           const a=document.createElement('a');a.href=url;a.download=result.operation+'-classes.csv';a.click();
           setTimeout(()=>URL.revokeObjectURL(url),1000);
         }}>Class CSV</button>}
         {result.features.length>0&&<small>{result.features.length} vector features</small>}
       </div>}
     </>}
     </div>
   </ResultPane>}
   {resultTab==='details'&&<div className="terrain-research-history">{runHistory.length>0&&<details className="terrain-run-provenance terrain-history" aria-label="Local terrain run history">
     <summary>History · {runHistory.length}</summary>
     {historyStorageError&&<small role="alert">History storage unavailable</small>}
     <div className="terrain-history-actions">
       <select aria-label="Select terrain run metadata" value={historyFocus} onChange={e=>setHistoryFocus(e.target.value)}>
         <option value="">Choose history</option>
         {runHistory.map(item=><option key={item.id} value={item.id}>
           {item.operation} · {new Date(item.createdAt).toLocaleTimeString()} · {item.id.slice(0,8)}
         </option>)}
       </select>
       <button disabled={!historyFocus} aria-label="Remove selected history receipt"
         title="Remove metadata receipt only" onClick={()=>{
           setRunHistory(old=>old.filter(item=>item.id!==historyFocus));setHistoryFocus('');
         }}>Remove</button>

     </div>
   </details>}
</div>}

 </div>;
 return <>
 <div className="terrain-workbench professional-panel">
   <div className="terrain-linked-controls" aria-label="Terrain analysis inputs">
     <div className="terrain-linked-row">
       <label className="terrain-linked-select">DEM
         <select aria-label="DEM elevation layer" value={dem?.id??''} disabled={fetching||importing}
           onChange={e=>{
             sourceIntent.current++;
             if(!e.target.value){p.onSelectRaster(null);setSourceInfo('');return;}
             const found=assets.find(item=>item.id===e.target.value)??(dem?.id===e.target.value?dem:null);
             if(found)p.onSelectRaster(found);
           }}>
           <option value="">Select elevation source</option>
           {[...assets,...(dem&&!assets.some(a=>a.id===dem.id)?[dem]:[])].map(asset=>
             <option key={asset.id} value={asset.id}>{asset.name}</option>)}
         </select>
       </label>
       <button className={leftTab==='source'?'terrain-linked-active':''} type="button"
         aria-label="Get DEM" aria-pressed={leftTab==='source'} onClick={()=>setLeftTab('source')}>Get DEM</button>
     </div>
     <div className="terrain-linked-row">
       <label className="terrain-linked-select">Analysis
         <select aria-label="Choose terrain analysis" value={operation??''}
           onChange={e=>{
             const value=e.target.value as Operation|'';
             setOperation(value||null);setLive(false);setPickEnd(false);
             setLeftTab(value?'setup':'tools');
           }}>
           <option value="">Choose an analysis</option>
           {modes.map(item=><option key={item.id} value={item.id}>{item.title}</option>)}
         </select>
       </label>
       <button className={leftTab==='tools'?'terrain-linked-active':''} type="button"
         aria-label="Browse terrain tools" aria-pressed={leftTab==='tools'}
         onClick={()=>setLeftTab('tools')}>Browse</button>
       <button type="button" disabled={!dem}
         aria-label="Process DEM" aria-pressed={leftTab==='process'}
         onClick={()=>setLeftTab('process')}>Prepare</button>
     </div>
   </div>
   <section id="terrain-panel-source" className="terrain-source terrain-step terrain-control-page"
     role="region" aria-label="Source settings" hidden={leftTab!=='source'}>
     {!p.localImport&&<details className="access-settings"><summary>Import access</summary><input type="password" aria-label="DEM import token" value={token} onChange={e=>setToken(e.target.value)}/></details>}
     <label className="raster-upload" title="Single-band DEM GeoTIFF, projected in meters, with meter elevations"><Mountain size={14}/> {importing?'Importing…':'Import DEM'}
       <input type="file" aria-label="Import DEM" accept=".tif,.tiff" disabled={importing||fetching||!p.connected} onChange={e=>void importDEM(e)}/></label>
     <label>Download area <select aria-label="DEM fetch area" value={fetchScope} onChange={e=>{setFetchChoice(e.target.value as FetchScope);setInfo('');}}>
       <option value="viewport">Current map view</option><option value="selection" disabled={!selectedGeometry}>Selected geometry</option>
     </select></label>
     {selectedGeometry&&<div className="survey-action-bar">
       <button onClick={()=>{setFetchChoice('selection');setInfo('DEM will use the selected geometry bounds, not the previous map view.');}}>Use selected area</button>
       {p.onFitSelectedArea&&<button onClick={()=>{setFetchChoice('selection');p.onFitSelectedArea?.();}}>Fit selected area</button>}
     </div>}
     <small className="compact-notice" aria-label="DEM download target" title={fetchArea?describeTerrainBounds(fetchArea):'No valid download area'}>
       {fetchArea?(fetchScope==='viewport'?'Current map · ':'Selected geometry · ')+describeTerrainBounds(fetchArea):'No valid download area'}
       {budget?' · ~'+budget.approximateCells.toLocaleString()+' grid cells':''}
     </small>
     {budget?.warning&&<small role="alert" className="discovery-error">{budget.warning}</small>}
     {fetchArea&&<div className="survey-action-bar">
       <button aria-label="Auto-fit DEM resolution" disabled={!recommendedResolution||fetching}
         onClick={()=>{if(!recommendedResolution)return;setResolution(recommendedResolution);
           setInfo('Finest supported output grid fitting this study area: '+recommendedResolution+
             ' m. This does not guarantee native source accuracy.');}}>
         Auto resolution{recommendedResolution?' · '+recommendedResolution+' m':''}
       </button>
       <small className="compact-notice" aria-label="DEM source coverage">
         Up to 8M cells, 4096 px/side · {supportsUSGS?'USGS 3DEP / Copernicus':'Copernicus global'}
       </small>
     </div>}
     <div className="area-fields">
       <select aria-label="Public DEM resolution" value={resolution}
          onChange={e=>setResolution(Number(e.target.value) as 1|3|10|30|90)}>
          <option value={30}>GLO-30 · 30 m</option>
          <option value={90}>GLO-90 · 90 m</option>
          <option value={10} disabled={!supportedResolutions.includes(10)}>USGS 3DEP · 10 m grid</option>
          <option value={3} disabled={!supportedResolutions.includes(3)}>USGS 3DEP · 3 m grid</option>
          <option value={1} disabled={!supportedResolutions.includes(1)}>USGS 3DEP · 1 m grid</option>
        </select>
       <button disabled={!p.connected||!fetchArea||!!budget?.warning||fetching||importing} title="Download the explicitly displayed area, not a previous selection" onClick={()=>void fetchDEM()}>{fetching?'Fetching…':'Fetch DEM'}</button>
       {fetching&&<button aria-label="Cancel DEM download" onClick={()=>{sourceIntent.current++;fetchAbort.current?.abort();setInfo('Cancelling the previous download…');}}>Cancel</button>}
     </div>
     {(sourceInfo||dem||!supportsUSGS&&fetchArea)&&<details className="terrain-source-metadata">
       <summary>Source info</summary>
       {sourceInfo&&<small className="compact-notice" title="Copernicus DSM / USGS bare-earth DEM">{sourceInfo}</small>}
       {!supportsUSGS&&fetchArea&&<small className="compact-notice">Global coverage: Copernicus. Regional DEMs may offer finer native resolution.</small>}
       {dem&&<small className="compact-notice" title={dem.provenance}>{dem.width} × {dem.height} · {dem.crs} · elevation m · {describeTerrainBounds(dem.bbox)}</small>}
     </details>}
     {mapMismatch&&<small className="discovery-error" role="status">Selected DEM is outside the current map. Choose a local source or use Fit explicitly.</small>}
     {sourceMismatch&&<small className="discovery-error" role="status">Selected analysis shape is not completely covered by this DEM. Select a matching source.</small>}
     {dem&&!/Copernicus DEM GLO-|USGS 3DEP Bare Earth DEM/.test(dem.provenance)&&<label className="gis-check"><input aria-label="Confirm DEM meter elevations" type="checkbox" checked={verticalConfirmed} onChange={e=>setVerticalConfirmed(e.target.checked)}/> Confirm single-band meter elevations</label>}
   </section>
   <section id="terrain-panel-tools" className="terrain-step terrain-analysis-step terrain-control-page"
     role="region" aria-label="Terrain tools page" hidden={leftTab!=='tools'}>
   <WorkspaceToolShelf category={category} categories={categories} tools={modes}
    selected={operation} onCategory={name=>{
      setCategory(name);setOperation(null);setLive(false);setPickEnd(false);
    }} onSelect={value=>{
      setOperation(value);
      if(value)setLeftTab('setup');
      else setLive(false);
    }}/>
   </section>
   <section id="terrain-panel-setup" className="terrain-step terrain-setup-page terrain-control-page"
     role="region" aria-label="Terrain parameters page" hidden={leftTab!=='setup'}>
     <div className="terrain-setup-heading"><strong>{modes.find(m=>m.id===operation)?.title??'Analysis settings'}</strong>
       <button type="button" onClick={()=>setLeftTab('tools')}>Browse tools</button>
     </div>
   {operation&&<div className="professional-form">
     <div className="survey-action-bar">
       <button onClick={()=>p.onDraw(lineOperation)}>{lineOperation?'Draw profile line':'Draw study area'}</button>
       {lineOperation&&p.profileGeometry&&<button onClick={p.onClearProfile}>Remove profile line</button>}
       {!lineOperation&&<button disabled={!dem} aria-pressed={p.extentMode} onClick={p.onUseExtent}>DEM extent</button>}
       {p.extentMode&&<button onClick={p.onUseSelection}>Use selection</button>}
     </div>
     <small className="compact-notice">{correctShape?(lineOperation?'✓ Independent profile line':p.extentMode?'✓ DEM footprint':'✓ Geometry selected'):lineOperation?'Draw a profile line; the selected area stays on the map':'Select or draw a polygon'}</small>
     {operation==='contours'&&<label>Interval (m)<input aria-label="Contour interval" type="number" min=".01" step="any" value={interval} onChange={e=>setInterval(e.target.value)}/></label>}
     {operation==='dem_difference'&&<label>Reference DEM<select aria-label="Reference comparison DEM" value={comparisonId} onChange={e=>setComparisonId(e.target.value)}><option value="">Select second DEM</option>{assets.filter(a=>a.bands===1&&a.id!==dem?.id).map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>}
     {(operation==='volume'||operation==='cutfill_map')&&<label>Reference elevation (m)<input aria-label="Reference elevation" type="number" step="any" value={reference} onChange={e=>setReference(e.target.value)}/></label>}
     {['volume','cutfill_map'].includes(operation)&&<details className="terrain-method-settings">
       <summary>Design surface and uncertainty</summary>
       <div className="area-fields">
         <label>East grade (m/m)<input aria-label="Design east grade" type="number" step="0.01" min="-1" max="1" value={designEastGrade} onChange={e=>setDesignEastGrade(e.target.value)}/></label>
         <label>North grade (m/m)<input aria-label="Design north grade" type="number" step="0.01" min="-1" max="1" value={designNorthGrade} onChange={e=>setDesignNorthGrade(e.target.value)}/></label>
       </div>
       <div className="area-fields">
         <label>Maximum grade (m/m)<input aria-label="Design maximum grade" type="number" step="0.01" min="0.001" max="1" value={designMaxGrade} onChange={e=>setDesignMaxGrade(e.target.value)}/></label>
         <label>Assumed vertical error σ (m)<input aria-label="Assumed elevation sigma" type="number" step="0.1" min="0" max="10000" value={elevationSigma} onChange={e=>setElevationSigma(e.target.value)}/></label>
       </div>
       <div className="area-fields">
         <label>East quadratic (1/m)<input aria-label="Design east quadratic curvature" type="number" step="0.00001" min="-1" max="1" value={designCurvatureEast} onChange={e=>setDesignCurvatureEast(e.target.value)}/></label>
         <label>Cross quadratic (1/m)<input aria-label="Design cross quadratic curvature" type="number" step="0.00001" min="-1" max="1" value={designCurvatureCross} onChange={e=>setDesignCurvatureCross(e.target.value)}/></label>
         <label>North quadratic (1/m)<input aria-label="Design north quadratic curvature" type="number" step="0.00001" min="-1" max="1" value={designCurvatureNorth} onChange={e=>setDesignCurvatureNorth(e.target.value)}/></label>
       </div>
       <small className="compact-notice">Design uses a quadratic surface with a conservative maximum-grade check across the grid rectangle. Vertical uncertainty is assumed, not measured.</small>
     </details>}
     {operation==='cross_sections'&&<div className="area-fields"><label>Station spacing (m)<input type="number" value={sectionSpacing} onChange={e=>setSectionSpacing(e.target.value)}/></label><label>Half-width (m)<input type="number" value={sectionWidth} onChange={e=>setSectionWidth(e.target.value)}/></label></div>}
     {operation==='mesh'&&<label>3D mesh detail
        <select aria-label="3D mesh sampling budget" value={meshSamples} onChange={e=>setMeshSamples(e.target.value)}>
          <option value="64">Preview · 64 samples/axis</option>
          <option value="128">Balanced · 128 samples/axis</option>
          <option value="256">Detailed · 256 samples/axis</option>
          <option value="512">High detail · 512 samples/axis</option>
        </select>
      </label>}
      {operation==='mesh'&&<label className="gis-check"><input aria-label="Generate 3D LOD tiles" type="checkbox" checked={meshLod} onChange={e=>setMeshLod(e.target.checked)}/> Generate mesh LOD pyramid (transport-ready)</label>}
      {operation==='mesh'&&meshLod&&<small className="compact-notice">Aligned tile levels are calculated for export; camera-triggered streaming is not implemented.</small>}
      {operation==='mesh'&&p.imageRaster&&p.imageRaster.bands>=3&&<label className="gis-check"><input type="checkbox" checked={drape} onChange={e=>setDrape(e.target.checked)}/> Drape selected RGB imagery</label>}
     {['slope','slope_map','aspect_map','hillshade','suitability','plan_curvature','profile_curvature'].includes(operation)&&
        <label>Gradient algorithm
          <select aria-label="Terrain gradient algorithm" value={gradientMethod}
            onChange={e=>setGradientMethod(e.target.value as 'horn'|'zevenbergen_thorne')}>
            <option value="horn">Horn · weighted 3×3</option>
            <option value="zevenbergen_thorne">Zevenbergen–Thorne · cardinal neighbors</option>
          </select>
        </label>}
      {['curvature','plan_curvature','profile_curvature'].includes(operation)&&<label>Curvature method
        <select aria-label="Terrain curvature method" value={curvatureMethod} onChange={e=>setCurvatureMethod(e.target.value as 'finite_difference'|'quadratic')}>
          <option value="finite_difference">Central 3 × 3 finite differences</option>
          <option value="quadratic">Least-squares quadratic surface</option>
        </select>
      </label>}
      {['curvature','plan_curvature','profile_curvature'].includes(operation)&&curvatureMethod==='quadratic'&&<label>Fitting window
        <select aria-label="Curvature fitting radius" value={curvatureRadius} onChange={e=>setCurvatureRadius(e.target.value)}>
          <option value="1">3 × 3</option><option value="2">5 × 5</option>
          <option value="3">7 × 7</option><option value="4">9 × 9</option>
        </select>
      </label>}
      {operation==='slope_map'&&<label>Slope classification
        <select aria-label="Slope classification preset" value={slopeClasses}
          onChange={e=>setSlopeClasses(e.target.value as 'standard'|'detailed'|'broad')}>
          <option value="standard">Standard · 6 classes</option>
          <option value="detailed">Detailed · 8 classes</option>
          <option value="broad">Broad · 4 classes</option>
        </select>
      </label>}
      {['tri','tpi'].includes(operation)&&<label>Terrain neighborhood
        <select aria-label="Terrain neighborhood radius" value={neighborhoodRadius}
          onChange={e=>setNeighborhoodRadius(e.target.value)}>
          <option value="1">3 × 3 · local</option>
          <option value="2">5 × 5 · intermediate</option>
          <option value="3">7 × 7 · regional</option>
          <option value="4">9 × 9 · broad</option>
        </select>
      </label>}
      {operation==='hillshade'&&<label>Illumination model
        <select aria-label="Hillshade illumination model" value={hillshadeMode}
          onChange={e=>setHillshadeMode(e.target.value as 'single'|'four_direction')}>
          <option value="single">Single solar direction</option>
          <option value="four_direction">Four-direction averaged illumination</option>
        </select>
      </label>}
      {operation==='hillshade'&&<div className="area-fields"><label>Sun azimuth (°)<input type="number" value={azimuth} onChange={e=>setAzimuth(e.target.value)}/></label><label>Sun altitude (°)<input type="number" value={altitude} onChange={e=>setAltitude(e.target.value)}/></label></div>}
     {operation==='flow_accumulation'&&<label>Contributing area routing
       <select aria-label="Flow routing method" value={flowRoutingMethod} onChange={e=>setFlowRoutingMethod(e.target.value as 'd8'|'dinf')}>
         <option value="d8">D8 · one downslope receiver</option>
         <option value="dinf">D∞ · triangular-facet split</option>
       </select>
     </label>}
     {operation==='flow_accumulation'&&flowRoutingMethod==='dinf'&&<label>External upstream inflow (optional)
       <select aria-label="External contributing area raster" value={externalInflowImageId} onChange={e=>setExternalInflowImageId(e.target.value)}>
         <option value="">None · unknown off-grid catchments excluded</option>
         {assets.filter(a=>a.bands===1&&a.id!==dem?.id).map(a=><option key={a.id} value={a.id}>{a.name}</option>)}
       </select>
       <small className="compact-notice">Requires a grid-aligned GeoTIFF explicitly tagged TERRAIN_UNIT=cells or cell_equivalents, with zeros outside known inlet cells.</small>
     </label>}
     {operation==='flow_accumulation_mfd'&&<label>MFD convergence exponent
       <input aria-label="MFD routing exponent" type="number" min="0.5" max="8" step="0.1"
         value={mfdExponent} onChange={e=>setMfdExponent(e.target.value)}/>
       <small className="compact-notice">Larger values concentrate flow toward steeper downslope neighbors.</small>
     </label>}
     {operation==='stream_order'&&<label>Stream hierarchy model
        <select aria-label="Stream hierarchy algorithm" value={streamOrderScheme}
          onChange={e=>setStreamOrderScheme(e.target.value as 'strahler'|'shreve')}>
          <option value="strahler">Strahler · confluence order</option>
          <option value="shreve">Shreve · additive magnitude</option>
        </select>
      </label>}
      {(operation==='streams'||operation==='stream_order')&&<label>Minimum upstream cells<input type="number" min="1" step="1" value={streamCells} onChange={e=>setStreamCells(e.target.value)}/></label>}
     {['flow_direction','flow_accumulation','flow_accumulation_mfd','streams','stream_order','watershed'].includes(operation)&&<label className="gis-check"><input aria-label="Condition drainage DEM" type="checkbox" checked={fillSinks} onChange={e=>setFillSinks(e.target.checked)}/> Fill depressions and route flat cells</label>}
     {['flow_direction','flow_accumulation','flow_accumulation_mfd','streams','stream_order','watershed'].includes(operation)&&fillSinks&&<label>Depression conditioning
       <select aria-label="Depression conditioning method" value={depressionMethod} onChange={e=>setDepressionMethod(e.target.value as 'fill'|'breach')}>
         <option value="fill">Priority-flood fill and flat routing</option>
         <option value="breach">Bounded least-cut drainage breach</option>
       </select>
     </label>}
     {['visibility','viewshed_multi'].includes(operation)&&<label>Obstruction surface (optional DSM)
       <select aria-label="Terrain obstruction DSM" value={dsmImageId} onChange={e=>setDsmImageId(e.target.value)}>
         <option value="">Bare DEM · no building blockage</option>
         {assets.filter(a=>a.bands===1&&a.id!==dem?.id).map(a=><option key={a.id} value={a.id}>{a.name}</option>)}
       </select>
       <small className="compact-notice">DSM must align with the DEM grid; unknown DSM cells remain unclassified.</small>
     </label>}
     {operation==='viewshed_multi'&&<label>Optimize observation sites
       <select aria-label="Optimize observer count" value={optimizeObservers} onChange={e=>setOptimizeObservers(e.target.value)}>
         <option value="0">Use all sites (up to 4)</option>
         <option value="1">Best 1 of candidate sites</option><option value="2">Best 2</option>
         <option value="3">Best 3</option><option value="4">Best 4</option>
       </select>
     </label>}
     {['visibility','viewshed_multi'].includes(operation)&&<details className="terrain-method-settings">
        <summary>Viewing sector and range</summary>
        <label>Maximum distance (m, 0 = all)
          <input aria-label="Viewshed maximum distance" type="number" min="0" max="10000"
            value={viewshedDistance} onChange={e=>setViewshedDistance(e.target.value)}/>
        </label>
        <div className="area-fields">
          <label>Facing azimuth (°)
            <input aria-label="Viewshed facing azimuth" type="number" min="0" max="360"
              value={viewshedAzimuth} onChange={e=>setViewshedAzimuth(e.target.value)}/>
          </label>
          <label>Field of view (°)
            <input aria-label="Viewshed horizontal field of view" type="number" min="0.01" max="360"
              value={viewshedWidth} onChange={e=>setViewshedWidth(e.target.value)}/>
          </label>
        </div>
      </details>}
      {(operation==='visibility'||operation==='viewshed_multi')&&<><label className="gis-check"><input aria-label="Consider Earth curvature" type="checkbox" checked={considerCurvature} onChange={e=>setConsiderCurvature(e.target.checked)}/> Earth curvature and atmospheric refraction</label>{considerCurvature&&<label>Refraction coefficient<input aria-label="Terrain refraction coefficient" type="number" min="0" max="0.5" step="0.01" value={refractionCoeff} onChange={e=>setRefractionCoeff(e.target.value)}/></label>}</>}
     {operation==='least_cost'&&<label>Routing cost model
        <select aria-label="Terrain routing cost model" value={routeModel}
          onChange={e=>setRouteModel(e.target.value as 'surface'|'distance'|'gentle')}>
          <option value="surface">3D surface length + slope penalty</option>
          <option value="distance">Shortest planar distance</option>
          <option value="gentle">Stronger gradient avoidance</option>
        </select>
      </label>}
      {(operation==='suitability'||operation==='least_cost')&&<label>Maximum slope (°)<input type="number" value={maxSlope} onChange={e=>setMaxSlope(e.target.value)}/></label>}
     {operation==='suitability'&&<label>Site suitability model
       <select aria-label="Suitability scoring method" value={suitabilityModel} onChange={e=>setSuitabilityModel(e.target.value as 'binary'|'weighted')}>
         <option value="binary">Hard constraints (pass/fail)</option>
         <option value="weighted">Weighted multi-criteria score 0–1</option>
       </select>
     </label>}
     {operation==='suitability'&&suitabilityModel==='weighted'&&<details open className="terrain-method-settings">
       <summary>Criterion weights</summary>
       <div className="area-fields">
         <label>Slope<input aria-label="Slope criterion weight" type="number" min="0" max="100" step="0.05" value={suitabilitySlopeWeight} onChange={e=>setSuitabilitySlopeWeight(e.target.value)}/></label>
         <label>Ruggedness<input aria-label="Ruggedness criterion weight" type="number" min="0" max="100" step="0.05" value={suitabilityTriWeight} onChange={e=>setSuitabilityTriWeight(e.target.value)}/></label>
         <label>Elevation<input aria-label="Elevation criterion weight" type="number" min="0" max="100" step="0.05" value={suitabilityElevationWeight} onChange={e=>setSuitabilityElevationWeight(e.target.value)}/></label>
       </div>
       <small className="compact-notice">Weights are normalized to sum to one. Constraints remain mandatory; scores are not predicted probabilities.</small>
     </details>}
     {operation==='suitability'&&<><div className="area-fields"><label>Min elevation (m)<input type="number" value={minElevation} onChange={e=>setMinElevation(e.target.value)}/></label><label>Max elevation (m)<input type="number" value={maxElevation} onChange={e=>setMaxElevation(e.target.value)}/></label></div><label>Maximum TRI (m)<input type="number" value={maxTri} onChange={e=>setMaxTri(e.target.value)}/></label></>}
     {needsPoint&&<>
       <div className="survey-action-bar"><button className={p.picking?'active':''} disabled={!area} onClick={()=>{setPickEnd(false);p.onPick();}}>{p.picking?'Click map…':operation==='visibility'?'Pick observer':operation==='least_cost'?'Pick route start':'Pick outlet'}</button>
       <button disabled={!area} onClick={()=>{const center=p.geometry&&measurementAnchor(p.geometry);if(center){setLon(String(center[0]));setLat(String(center[1]));}}}>Area center</button></div>
       <div className="area-fields"><input aria-label="Terrain origin longitude" type="number" step="any" placeholder="Longitude" value={lon} onChange={e=>setLon(e.target.value)}/>
       <input aria-label="Terrain origin latitude" type="number" step="any" placeholder="Latitude" value={lat} onChange={e=>setLat(e.target.value)}/></div>
       {operation==='least_cost'&&<button disabled={!area||p.picking} onClick={()=>{setPickEnd(true);p.onPick();}}>Pick route end</button>}
       {operation==='least_cost'&&<div className="area-fields"><input aria-label="Route end longitude" type="number" step="any" placeholder="End longitude" value={endLon} onChange={e=>setEndLon(e.target.value)}/><input aria-label="Route end latitude" type="number" step="any" placeholder="End latitude" value={endLat} onChange={e=>setEndLat(e.target.value)}/></div>}
       {operation==='visibility'&&<div className="area-fields"><label>Observer (m)<input aria-label="Observer height" type="number" min="0" value={height} onChange={e=>setHeight(e.target.value)}/></label>
       <label>Target (m)<input aria-label="Target height" type="number" min="0" value={target} onChange={e=>setTarget(e.target.value)}/></label></div>}
     </>}
     {operation==='viewshed_multi'&&<div className="terrain-multi-observers">
      <div className="section-heading">Observers · {observerPoints.length}</div>
      <small className="compact-notice">Specify {Number(optimizeObservers)>0?'2–12 candidate':'2–4'} WGS84 positions in distinct valid DEM cells. Optimization exhaustively checks all candidate combinations (up to 12 choose 4) for maximum positively observed coverage.</small>
      <div className="terrain-observer-grid">
        {observerPoints.map(([x,y],index)=><div className="terrain-observer-row" key={index}>
          <label>Observer {index+1} longitude
            <input type="number" step="any" aria-label={`Observer ${index+1} longitude`}
              value={x} onChange={e=>setObserverPoints(old=>old.map((p,i)=>i===index?[e.target.value,p[1]]:p))}/></label>
          <label>Latitude
            <input type="number" step="any" aria-label={`Observer ${index+1} latitude`}
              value={y} onChange={e=>setObserverPoints(old=>old.map((p,i)=>i===index?[p[0],e.target.value]:p))}/></label>
          <button type="button" aria-label={`Clear observer ${index+1}`}
            onClick={()=>setObserverPoints(old=>old.map((p,i)=>i===index?['','']:p))}>Clear</button>
        </div>)}
      </div>
      <div className="survey-action-bar">
        <button disabled={!area||p.picking} onClick={()=>p.onPick()}>Pick next observer on map</button>
        <button disabled={observerPoints.length>=(Number(optimizeObservers)>0?12:4)}
          onClick={()=>setObserverPoints(old=>old.length<(Number(optimizeObservers)>0?12:4)?[...old,['','']]:old)}>Add observer</button>
        <button disabled={observerPoints.length<=2}
          onClick={()=>setObserverPoints(old=>old.length>2?old.slice(0,-1):old)}>Remove last</button>
      </div>
      <div className="area-fields">
        <label>Observer height (m)<input aria-label="Multi observer height" type="number" min="0" max="1000"
          value={height} onChange={e=>setHeight(e.target.value)}/></label>
        <label>Target height (m)<input aria-label="Multi target height" type="number" min="0" max="1000"
          value={target} onChange={e=>setTarget(e.target.value)}/></label>
      </div>
      {!multiObserversValid&&<small className="discovery-error">
        Enter {Number(optimizeObservers)>0?'2–12':'2–4'} different valid longitude/latitude pairs.
      </small>}
    </div>}
    {!p.operationsFooterTarget&&runActions}
     {!p.connected&&<small className="compact-notice">API offline</small>}
     {!dem&&<small className="compact-notice">DEM required</small>}
     {sourceMismatch&&<small className="discovery-error">Selected analysis area is not fully covered by the DEM</small>}
     {mapMismatch&&<small className="discovery-error">Run blocked: the selected DEM is outside the visible map. Use the raster Fit control or fetch new data.</small>}
     {dem&&!verified&&<small className="compact-notice">Confirm elevation units before analysis</small>}
     {!parametersValid&&<small className="discovery-error">Check numeric parameters</small>}
   </div>}
   </section>
   <section id="terrain-panel-process" className="terrain-step terrain-process-page terrain-control-page"
     role="region" aria-label="DEM processing page" hidden={leftTab!=='process'}>
     {dem?<><div className="terrain-setup-heading"><strong>DEM processing</strong></div>
     {dem&&<div className="terrain-dem-process-form">
       <div className="professional-form">
         <label>Operation<select aria-label="DEM processing operation" value={demProcessMode} onChange={e=>setDemProcessMode(e.target.value as DEMProcessMode)}>
           <option value="clip">Clip selected polygon</option><option value="resample">Resample source</option><option value="mosaic">Mosaic two DEMs</option>
         </select></label>
         {demProcessMode==='mosaic'&&<label>Second DEM<select aria-label="DEM mosaic second source" value={processSecond} onChange={e=>setProcessSecond(e.target.value)}>
           <option value="">Choose second DEM</option>{assets.filter(a=>a.bands===1&&a.id!==dem.id).map(a=><option key={a.id} value={a.id}>{a.name}</option>)}
         </select></label>}
         <label>Output grid (m)<input aria-label="DEM processing resolution" type="number" min="1" max="1000" step="any" value={processResolution} onChange={e=>setProcessResolution(e.target.value)}/></label>
         <label>Sampling<select aria-label="DEM processing sampling" value={processSampling} onChange={e=>setProcessSampling(e.target.value as 'nearest'|'bilinear'|'average')}>
           <option value="bilinear">Bilinear</option><option value="nearest">Nearest</option><option value="average">Area-weighted average (coarsen)</option>
         </select></label>
         <button disabled={!p.connected||fetching||importing||demProcessMode==='clip'&&!['Polygon','MultiPolygon'].includes(p.geometry?.type??'')||demProcessMode==='mosaic'&&(!processSecond||processSecond===dem.id)}
           onClick={()=>void processDEM()}>{importing?'Processing…':'Create processed DEM'}</button>
         <small className="compact-notice">Processing changes the output grid, not the native input resolution or vertical datum.</small>
       </div>
     </div>}

     </>:<span>No DEM selected</span>}
   </section>
   {info&&<p className="project-info">{info}</p>}{error&&<p className="discovery-error" role="alert">{error}</p>}
 </div>
 {p.resultsTarget?(p.active?createPortal(monitor,p.resultsTarget):null):monitor}
 {p.operationsFooterTarget?(p.active&&runActions?createPortal(runActions,p.operationsFooterTarget):null):null}
 {p.resultsFooterTarget?(p.active&&resultActions?createPortal(resultActions,p.resultsFooterTarget):null):resultActions}
 {/* Export owns a separate module; its actions must survive leaving Terrain. */}
 {p.exportTarget?createPortal(terrainFileActions,p.exportTarget):null}
 </>;
}
