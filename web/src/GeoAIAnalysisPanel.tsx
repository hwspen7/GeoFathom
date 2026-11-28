import {SectionIcon} from './SectionIcon';
import {useEffect,useRef,useState} from 'react';
import {Database} from 'lucide-react';
import ScientificFigureStudio from './ScientificFigureStudio';
import BuildingResearchPanel from './BuildingResearchPanel';
import {
  getGISJob,getVisionModels,listImagery,queueGISJob,saveFeatureBatch,
  cancelGISJob,downloadBuildingArtifact,
  type GISJob,type GISJobKind,type GeoAIResult,type RasterAsset,
  type VisionModels,
} from './api';

interface Props {
  projectId:string|null;
  image:RasterAsset|null;
  studyArea?:GeoJSON.Geometry|null;
  onPreview:(geometries:GeoJSON.Geometry[])=>void;
  onSaved:()=>void;
}
type Operation=Extract<GISJobKind,
  'spectral_index'|'spectral_change'|'semantic_segmentation'|'building_extraction'|'stac_ndvi'>;

function resultOf(job:GISJob|null):GeoAIResult|null{
  if(job?.status!=='completed'||!job.result||typeof job.result!=='object')return null;
  const item=job.result as Partial<GeoAIResult>;
  return item.type==='FeatureCollection'&&Array.isArray(item.features)?
    item as GeoAIResult:null;
}

export default function GeoAIAnalysisPanel(p:Props){
  const [operation,setOperation]=useState<Operation>('spectral_index');
  const [stacCollection,setStacCollection]=useState('sentinel-2-c1-l2a');
  const [stacItemId,setStacItemId]=useState('');
  const [stacSide,setStacSide]=useState(4096);
  const [images,setImages]=useState<RasterAsset[]>([]);
  const [models,setModels]=useState<VisionModels|null>(null);
  const [modelId,setModelId]=useState('');
  const [secondaryModelId,setSecondaryModelId]=useState('');
  const [secondaryWeight,setSecondaryWeight]=useState(.5);
  const [index,setIndex]=useState<'ndvi'|'ndwi'>('ndvi');
  const [firstBand,setFirstBand]=useState(4);
  const [secondBand,setSecondBand]=useState(1);
  const [threshold,setThreshold]=useState(.2);
  const [confidence,setConfidence]=useState(.55);
  const [buildingThreshold,setBuildingThreshold]=useState(.5);
  const [buildingAugmentation,setBuildingAugmentation]=useState<'none'|'flips'|'multiscale'>('none');
  const [minimumArea,setMinimumArea]=useState(4);
  const [useStudyArea,setUseStudyArea]=useState(false);
  const [instanceMode,setInstanceMode]=useState<'connected'|'watershed'>('connected');
  const [seedDistance,setSeedDistance]=useState(6);
  const [researchOpen,setResearchOpen]=useState(false);
  const [afterImageId,setAfterImageId]=useState('');
  const [maxSide,setMaxSide]=useState(512);
  const [fullResolution,setFullResolution]=useState(false);
  const [tileSize,setTileSize]=useState(256);
  const [memoryBudget,setMemoryBudget]=useState(32);
  const [maxPixels,setMaxPixels]=useState(16777216);
  const [token,setToken]=useState('');
  const [job,setJob]=useState<GISJob|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [message,setMessage]=useState('');
  const [figuresOpen,setFiguresOpen]=useState(false);
  const currentProject=useRef(p.projectId);
  currentProject.current=p.projectId;
  // Image switches invalidate outstanding requests just as project switches do.
  const currentScope=useRef('');
  currentScope.current=String(p.projectId)+':'+String(p.image?.id);

  useEffect(()=>{
    let active=true;
    void Promise.all([listImagery(),getVisionModels()]).then(([assets,catalog])=>{
      if(!active)return;
      setImages(assets);
      setModels(catalog);
      setModelId(previous=>previous||catalog.models[0]?.id||'');
    }).catch(cause=>{
      if(active)setError(cause instanceof Error?cause.message:'Cannot load GeoAI models.');
    });
    return ()=>{active=false;};
  },[p.image?.id]);
  useEffect(()=>{
    setJob(null);setMessage('');setError('');setFiguresOpen(false);
    p.onPreview([]);
  },[p.projectId,p.image?.id]);
  useEffect(()=>{
    if(!p.projectId||!job||['completed','failed','cancelled','interrupted'].includes(job.status))return;
    const projectId=p.projectId;
    const scope=currentScope.current;
    let active=true;
    const timer=window.setInterval(()=>{
      getGISJob(projectId,job.id,false).then(async latest=>{
        if(!active||currentScope.current!==scope)return;
        if(latest.status==='completed'&&latest.has_result){
          const result=await getGISJob(projectId,job.id,true);
          if(active&&currentScope.current===scope)setJob(result);
        }else if(active&&currentScope.current===scope){
          setJob(latest);
        }
      }).catch(()=>{});
    },1250);
    return ()=>{active=false;window.clearInterval(timer);};
  },[p.projectId,p.image?.id,job?.id,job?.status]);
  const result=resultOf(job);
  const processing=busy||job?.status==='queued'||job?.status==='running';
  const buildingMode=operation==='building_extraction';
  const selectedModel=models?.models.find(item=>item.id===modelId);
  const polygonArea=p.studyArea&&['Polygon','MultiPolygon'].includes(p.studyArea.type)?p.studyArea:null;
  const visibleModels=(models?.models||[]).filter(item=>!buildingMode||item.task==='building_extraction');

  async function submit(){
    const projectId=p.projectId;
    const scope=currentScope.current;
    if(!projectId)throw new Error('Select a project.');
    if(operation!=='stac_ndvi'&&!p.image)
      throw new Error('Select a georeferenced image.');
    const payload:Record<string,unknown>=buildingMode?{
      image_id:p.image!.id,model_id:modelId,probability_threshold:buildingThreshold,
      ...(secondaryModelId&&secondaryModelId!==modelId?{secondary_model_id:secondaryModelId,secondary_weight:secondaryWeight}:{}),
      minimum_area_m2:minimumArea,full_resolution:true,memory_mb:memoryBudget,
      instance_mode:instanceMode,seed_distance:seedDistance,
      ...(buildingAugmentation!=='none'?{augmentation:buildingAugmentation}:{}),
      max_pixels:maxPixels,...(useStudyArea&&polygonArea?{aoi:polygonArea}:{}),
    }:operation==='stac_ndvi'?
      {collection:stacCollection,item_id:stacItemId,
       threshold,max_side:stacSide,tile_size:tileSize,
       max_pixels:maxPixels,memory_mb:memoryBudget,full_resolution:true}:
      {image_id:p.image!.id,max_side:maxSide};
    if(buildingMode){
      if(selectedModel?.task!=='building_extraction')throw new Error('Choose an installed building extraction model.');
      if(secondaryModelId&&(secondaryModelId===modelId||!visibleModels.some(m=>m.id===secondaryModelId)
          ||!Number.isFinite(secondaryWeight)||secondaryWeight<.05||secondaryWeight>.95))
        throw new Error('Choose a distinct secondary building model and weight from 0.05 to 0.95.');
      if(!(buildingThreshold>0&&buildingThreshold<1)||!Number.isFinite(minimumArea)||minimumArea<0)
        throw new Error('Check the building probability threshold and minimum area.');
      if(useStudyArea&&!polygonArea)throw new Error('Select a polygon study area on the map.');
    }else if(operation==='stac_ndvi'){
      if(!/^[A-Za-z0-9_-]{8,140}$/.test(stacItemId))
        throw new Error('Provide a valid Earth Search STAC scene identifier.');
    }else if(operation==='semantic_segmentation'){
      if(!modelId)throw new Error('Install and select a configured ONNX model.');
      payload.model_id=modelId;
      payload.minimum_confidence=confidence;
      if(fullResolution){
        payload.full_resolution=true;
        payload.memory_mb=memoryBudget;
        payload.max_pixels=maxPixels;
      }
    }else{
      if(!Number.isInteger(firstBand)||!Number.isInteger(secondBand)||
         firstBand===secondBand||firstBand<1||secondBand<1||
         firstBand>p.image!.bands||secondBand>p.image!.bands)
        throw new Error('Choose two different bands that exist in the source image.');
      payload.first_band=firstBand;
      payload.second_band=secondBand;
      payload.threshold=threshold;
      if(fullResolution){
        payload.full_resolution=true;
        payload.tile_size=tileSize;
        payload.memory_mb=memoryBudget;
        payload.max_pixels=maxPixels;
      }
      if(operation==='spectral_index')payload.index=index;
      else{
        if(!afterImageId||afterImageId===p.image!.id)
          throw new Error('Choose a different second date image.');
        payload.after_image_id=afterImageId;
      }
    }
    const created=await queueGISJob(projectId,operation,payload,token);
    if(currentScope.current!==scope)return;
    setJob(created);
    setMessage('Analysis queued. Results remain estimates until reviewed.');
    p.onPreview([]);
  }

  function preview(){
    if(!result)return;
    p.onPreview(result.features
      .map(item=>item.geometry)
      .filter((value):value is GeoJSON.Geometry=>Boolean(value)));
    setMessage('Previewing '+result.features.length+' candidate regions. Review before saving.');
  }

  async function save(){
    const projectId=p.projectId;
    if(!projectId||!result||!result.features.length)return;
    const rows=result.features
      .filter((feature):feature is GeoJSON.Feature<GeoJSON.Geometry>=>Boolean(feature.geometry))
      .slice(0,100).map((feature,i)=>({
      name:(String(feature.properties?.class_name||'Mapped region')+' '+(i+1)).slice(0,150),
      source:'GeoFathom '+result.analysis+' · '+result.provider,
      geometry:feature.geometry,
      properties:{
        ...(feature.properties||{}),
        source_type:'image_derived',
        source_images:result.source_images,
        analysis_engine:result.engine,
        model_id:result.model_id,
        provenance:result.provenance,
        quality:'requires_user_review',
      },
    }));
    const saved=await saveFeatureBatch(projectId,rows);
    if(currentProject.current!==projectId)return;
    p.onSaved();
    setMessage('Saved '+saved.created+' candidates to project for review. You can edit their boundaries.');
  }
  async function run(fn:()=>Promise<void>){
    setBusy(true);setError('');
    try{await fn();}
    catch(cause){setError(cause instanceof Error?cause.message:'GeoAI operation failed.');}
    finally{setBusy(false);}
  }

  return <div className="professional-panel">
    <details>
      <summary><SectionIcon role="geoai" size={14}/> GeoAI raster analysis & change detection</summary>
      <div className="professional-form">
        <p className="project-hint">
          Choose an explicit analysis operation. Spectral indices and change
          detection are deterministic; semantic classes require an installed ONNX model.
        </p>
        <select aria-label="GeoAI analysis operation" value={operation} disabled={processing}
          onChange={event=>{
            const next=event.target.value as Operation;setOperation(next);
            if(next==='building_extraction'){
              setModelId(models?.models.find(item=>item.task==='building_extraction')?.id||'');
              setMemoryBudget(value=>Math.max(value,64));
            }
          }}>
          <option value="building_extraction">AI building footprint extraction</option>
          <option value="spectral_index">Spectral index regions (NDVI / NDWI)</option>
          <option value="spectral_change">Two-date spectral change</option>
          <option value="semantic_segmentation">ONNX semantic segmentation</option>
          <option value="stac_ndvi">Remote STAC/COG NDVI with SCL cloud masking</option>
        </select>
        <p className="project-hint">Current image: {p.image?.name||'None selected'} ·
          {p.image?.bands??0} bands. Select an image and project first.</p>
        {operation==='stac_ndvi'?<>
          <label>Earth Search collection
            <select aria-label="Remote STAC collection"
              value={stacCollection} onChange={e=>setStacCollection(e.target.value)}>
              <option value="sentinel-2-c1-l2a">Sentinel-2 C1 L2A</option>
              <option value="sentinel-2-l2a">Sentinel-2 L2A</option>
            </select>
          </label>
          <label>STAC scene identifier
            <input aria-label="Remote STAC item identifier"
              value={stacItemId} onChange={e=>setStacItemId(e.target.value)}
              placeholder="Scene ID from public STAC search"/>
          </label>
          <label>Maximum remote processing dimension
            <select aria-label="Remote STAC processing resolution"
              value={stacSide} onChange={e=>setStacSide(Number(e.target.value))}>
              <option value={2048}>2048 px</option>
              <option value={4096}>4096 px</option>
              <option value={8192}>8192 px</option>
            </select>
          </label>
          <label>NDVI threshold
            <input aria-label="Remote NDVI threshold" type="number" step=".05"
              min={-0.99} max={0.99} value={threshold}
              onChange={e=>setThreshold(Number(e.target.value))}/>
          </label>
          <p className="compact-notice">Public COG range requests and Sentinel-2
            scene-classification masking; source resolution may be reduced
            to satisfy the configured pixel budget.</p>
        </>:operation!=='semantic_segmentation'&&!buildingMode?<>
          {operation==='spectral_index'&&
            <select aria-label="Spectral index" value={index} onChange={event=>{
              const next=event.target.value as 'ndvi'|'ndwi';
              setIndex(next);setFirstBand(next==='ndvi'?4:2);
              setSecondBand(next==='ndvi'?1:4);
            }}>
              <option value="ndvi">NDVI · NIR vs Red</option>
              <option value="ndwi">NDWI · Green vs NIR</option>
            </select>}
          <div className="area-fields">
            <label>Numerator band
              <input aria-label="Spectral first band" type="number" min={1} max={20}
                value={firstBand} onChange={e=>setFirstBand(Number(e.target.value))}/>
            </label>
            <label>Denominator band
              <input aria-label="Spectral second band" type="number" min={1} max={20}
                value={secondBand} onChange={e=>setSecondBand(Number(e.target.value))}/>
            </label>
          </div>
          <label>Normalized difference threshold
            <input aria-label="Spectral difference threshold" type="number" step=".05"
              min={operation==='spectral_change' ? 0.01 : -0.99} max=".99"
              value={threshold} onChange={e=>setThreshold(Number(e.target.value))}/>
          </label>
          {operation==='spectral_change'&&
            <select aria-label="Second date georeferenced image" value={afterImageId}
              onChange={e=>setAfterImageId(e.target.value)}>
              <option value="">Choose second date image</option>
              {images.filter(item=>item.id!==p.image?.id).map(item=>
                <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>}
          <p className="project-hint">Band numbers are 1-based GeoTIFF indexes.
            Confirm the satellite sensor band mapping before interpreting results.</p>
        </>:<>
          <select aria-label="Local ONNX vision model" value={modelId}
            onChange={e=>setModelId(e.target.value)}>
            <option value="">Choose a configured segmentation model</option>
            {visibleModels.map(item=>
              <option key={item.id} value={item.id}>
                {item.id} · {item.classes.length} classes
              </option>)}
          </select>
          {buildingMode?<>
            {visibleModels.length>1&&<><label>Secondary model<select aria-label="Secondary building model" value={secondaryModelId}
              onChange={e=>setSecondaryModelId(e.target.value)}>
              <option value="">None (single model)</option>
              {visibleModels.filter(m=>m.id!==modelId).map(m=><option key={m.id} value={m.id}>{m.id}</option>)}
            </select></label>
            {secondaryModelId&&<label>Secondary probability weight<input aria-label="Secondary building weight" type="number"
              min={.05} max={.95} step={.05} value={secondaryWeight} onChange={e=>setSecondaryWeight(Number(e.target.value))}/></label>}
            </>}
            <label>Building probability threshold
              <input aria-label="Building probability threshold" type="number" min={.01} max={.99}
                step={.05} value={buildingThreshold} onChange={e=>setBuildingThreshold(Number(e.target.value))}/>
            </label>
            <label>Minimum footprint area (m²)
              <input aria-label="Minimum building footprint area" type="number" min={0} max={100000}
                value={minimumArea} onChange={e=>setMinimumArea(Number(e.target.value))}/>
            </label>
            <label>Inference mode<select aria-label="Building inference augmentation" value={buildingAugmentation}
              onChange={e=>setBuildingAugmentation(e.target.value as typeof buildingAugmentation)}>
              <option value="none">Standard</option>
              <option value="flips">Four-view fusion (experimental)</option>
              <option value="multiscale">Multi-scale fusion (experimental)</option>
            </select></label>
            <label>Building separation<select aria-label="Building instance separation" value={instanceMode}
              onChange={e=>setInstanceMode(e.target.value as typeof instanceMode)}>
              <option value="watershed">Experimental instances · boundary / distance watershed</option>
              <option value="connected">Connected foreground regions</option>
            </select></label>
            {instanceMode==='watershed'&&<label>Minimum seed spacing (pixels)
              <input aria-label="Building instance seed spacing" type="number" min={1} max={64} value={seedDistance}
                onChange={e=>setSeedDistance(Number(e.target.value))}/></label>}
            <label><input aria-label="Limit buildings to selected study area" type="checkbox"
              disabled={!polygonArea} checked={useStudyArea}
              onChange={e=>setUseStudyArea(e.target.checked)}/> Use selected polygon as study area</label>
            <p className="project-hint">Use high-resolution RGB aerial or satellite imagery.
              Footprints retain native pixels, holes and geographic coordinates.
              Review instance boundaries for merged or over-separated roofs.</p>
            {!visibleModels.length&&<p className="compact-notice">No building model is installed. Install the supported public model using the setup command in the building extraction guide.</p>}
          </>:<label>Minimum model confidence
            <input aria-label="Minimum model confidence" type="number" step=".05"
              min={0} max={1} value={confidence}
              onChange={e=>setConfidence(Number(e.target.value))}/>
          </label>}
          <p className="compact-notice">ONNX runtime: {models?.runtime_available?'installed':'not installed'};
            model weights and class/band metadata must be provisioned on the server.
            No model is silently downloaded.</p>
        </>}
        {operation!=='stac_ndvi'&&!buildingMode&&<label><input type="checkbox"
            aria-label="Process full image at native pixel resolution"
            checked={fullResolution} onChange={e=>setFullResolution(e.target.checked)}/>
            Full-resolution streamed analysis
          </label>}
        {(fullResolution||operation==='stac_ndvi'||buildingMode)?<>
          <p className="project-hint">Process selected pixels using bounded
            raster windows, a temporary disk-backed mask and seamless
            polygonization. Large images are limited by the configured pixel
            budget and source image size.</p>
          {operation==='semantic_segmentation'||buildingMode?
            <p className="project-hint">Semantic tile size comes from the
              installed ONNX model manifest. Tiles are stitched into a single
              disk mask for geographic vectorization; model-edge predictions
              may still show seams.</p>:
          <label>Tile edge length
            <select aria-label="GeoAI tile size" value={tileSize}
              onChange={e=>setTileSize(Number(e.target.value))}>
              <option value={128}>128 px</option>
              <option value={256}>256 px</option>
              <option value={512}>512 px</option>
            </select>
          </label>}
          <label>Per-tile memory allowance
            <select aria-label="GeoAI tile memory budget" value={memoryBudget}
              onChange={e=>setMemoryBudget(Number(e.target.value))}>
              <option value={16}>16 MB</option><option value={32}>32 MB</option>
              <option value={64}>64 MB</option><option value={128}>128 MB</option>
            </select>
          </label>
          <label>Maximum source pixels
            <select aria-label="GeoAI pixel processing limit" value={maxPixels}
              onChange={e=>setMaxPixels(Number(e.target.value))}>
              <option value={16777216}>16.8 million</option>
              <option value={67108864}>67.1 million (8K²)</option>
            </select>
          </label>
        </>:<label>Maximum processing dimension
          <select aria-label="GeoAI processing resolution" value={maxSide}
            onChange={e=>setMaxSide(Number(e.target.value))}>
            <option value={256}>256 px</option><option value={512}>512 px</option>
            <option value={768}>768 px</option>
          </select>
        </label>}
        <input aria-label="GeoAI administration token" type="password"
          autoComplete="off" placeholder="Server administration token"
          value={token} onChange={e=>setToken(e.target.value)}/>
        <button disabled={!p.projectId||
          (operation!=='stac_ndvi'&&!p.image)||
          (operation==='stac_ndvi'&&!stacItemId)||!token||processing||
          ((operation==='semantic_segmentation'||buildingMode)&&!modelId)||
          (buildingMode&&(selectedModel?.task!=='building_extraction'||!models?.runtime_available))}
          onClick={()=>void run(submit)}>Run georeferenced analysis</button>
        {job&&<div className="raster-details" aria-label="GeoAI task status">
          Task {job.id.slice(0,8)} · {job.status} · {job.progress}%
        </div>}
        {job&&p.projectId&&['queued','running'].includes(job.status)&&
          <button onClick={()=>void run(async()=>setJob(await cancelGISJob(p.projectId!,job.id)))}>Cancel analysis</button>}
        {job?.status==='failed'&&<p className="discovery-error">{job.error}</p>}
        {result&&<>
          <div className="raster-details">
            <SectionIcon role="candidates" size={14}/> {result.features.length} candidate regions ·
            {result.valid_pixels} valid pixels
          </div>
          <p className="project-hint">{result.warning}
            {result.truncated?' Output limited to the largest candidate regions.':''}</p>
          <div className="survey-action-bar">
            <button onClick={preview} disabled={!result.features.length}>Preview on map</button>
            <button disabled={busy||!result.features.length}
              onClick={()=>void run(save)}><Database size={14}/> Save candidates</button>
            <button onClick={()=>p.onPreview([])}>Clear preview</button>
          </div>
          {result.ensemble&&<p className="raster-details" aria-label="Building ensemble summary">
            {result.ensemble.primary} · {((1-result.ensemble.secondary_weight)*100).toFixed(0)}% / {result.ensemble.secondary} · {(result.ensemble.secondary_weight*100).toFixed(0)}%
          </p>}
          {result.summary&&<p className="raster-details" aria-label="Building extraction summary">
            {result.summary.candidate_count} building candidates · {result.summary.total_area_m2.toFixed(1)} m² retained area
          </p>}
          {result.analysis==='building_extraction'&&p.projectId&&job&&
            <div className="survey-action-bar" aria-label="Building extraction downloads">
              <button disabled={!result.features.length} onClick={()=>setFiguresOpen(true)}>Open scientific figures</button>
              {Object.keys(result.artifacts||{}).map(asset=><button key={asset} disabled={busy}
                onClick={()=>void run(()=>downloadBuildingArtifact(p.projectId!,job.id,asset))}>
                Download {asset}</button>)}
            </div>}
        </>}
        {message&&<p className="project-info">{message}</p>}
        {error&&<p className="discovery-error">{error}</p>}
        {buildingMode&&<><button aria-expanded={researchOpen} onClick={()=>setResearchOpen(old=>!old)}>Model training and validation</button>
          {researchOpen&&<BuildingResearchPanel projectId={p.projectId} token={token} models={visibleModels}
            onInstalled={()=>{void getVisionModels().then(setModels).catch(cause=>setError(String(cause.message??cause)));}}/>}</>}
        {figuresOpen&&result&&<ScientificFigureStudio onClose={()=>setFiguresOpen(false)}
          source={{name:'Building footprint candidates',vectors:result,
            csv:['building_id,area_m2,perimeter_m,mean_building_probability,compactness,pixel_count',
              ...result.features.map((f,i)=>[i+1,f.properties?.area_m2,f.properties?.perimeter_m,
                f.properties?.mean_building_probability,f.properties?.compactness,f.properties?.pixel_count].join(','))].join('\n'),
            provenance:result,initialRecipe:'research_vector_map'}}/>}
      </div>
    </details>
  </div>;
}
