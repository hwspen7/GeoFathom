import {useEffect,useRef,useState} from 'react';
import {BrainCircuit,Database,Layers3} from 'lucide-react';
import {
  getGISJobs,getVisionModels,listImagery,queueGISJob,saveFeatureBatch,
  type GISJob,type GISJobKind,type GeoAIResult,type RasterAsset,
  type VisionModels,
} from './api';

interface Props {
  projectId:string|null;
  image:RasterAsset|null;
  onPreview:(geometries:GeoJSON.Geometry[])=>void;
  onSaved:()=>void;
}
type Operation=Extract<GISJobKind,
  'spectral_index'|'spectral_change'|'semantic_segmentation'>;

function resultOf(job:GISJob|null):GeoAIResult|null{
  if(job?.status!=='completed'||!job.result||typeof job.result!=='object')return null;
  const item=job.result as Partial<GeoAIResult>;
  return item.type==='FeatureCollection'&&Array.isArray(item.features)?
    item as GeoAIResult:null;
}

export default function GeoAIAnalysisPanel(p:Props){
  const [operation,setOperation]=useState<Operation>('spectral_index');
  const [images,setImages]=useState<RasterAsset[]>([]);
  const [models,setModels]=useState<VisionModels|null>(null);
  const [modelId,setModelId]=useState('');
  const [index,setIndex]=useState<'ndvi'|'ndwi'>('ndvi');
  const [firstBand,setFirstBand]=useState(4);
  const [secondBand,setSecondBand]=useState(1);
  const [threshold,setThreshold]=useState(.2);
  const [confidence,setConfidence]=useState(.55);
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
  const currentProject=useRef(p.projectId);
  currentProject.current=p.projectId;

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
    setJob(null);setMessage('');setError('');
    p.onPreview([]);
  },[p.projectId,p.image?.id]);
  useEffect(()=>{
    if(!p.projectId||!job||['completed','failed','cancelled','interrupted'].includes(job.status))return;
    const projectId=p.projectId;
    let active=true;
    const timer=window.setInterval(()=>{
      getGISJobs(projectId).then(response=>{
        if(active&&currentProject.current===projectId){
          const latest=response.jobs.find(item=>item.id===job.id);
          if(latest)setJob(latest);
        }
      }).catch(()=>{});
    },1250);
    return ()=>{active=false;window.clearInterval(timer);};
  },[p.projectId,job?.id,job?.status]);
  const result=resultOf(job);
  const processing=busy||job?.status==='queued'||job?.status==='running';

  async function submit(){
    const projectId=p.projectId;
    if(!projectId||!p.image)throw new Error('Select a project and georeferenced image.');
    const payload:Record<string,unknown>={
      image_id:p.image.id,max_side:maxSide,
    };
    if(operation==='semantic_segmentation'){
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
         firstBand>p.image.bands||secondBand>p.image.bands)
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
        if(!afterImageId||afterImageId===p.image.id)
          throw new Error('Choose a different second date image.');
        payload.after_image_id=afterImageId;
      }
    }
    const created=await queueGISJob(projectId,operation,payload,token);
    if(currentProject.current!==projectId)return;
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
        quality:'requires_user_review',
      },
    }));
    const saved=await saveFeatureBatch(projectId,rows);
    if(currentProject.current!==projectId)return;
    p.onSaved();
    setMessage('Saved '+saved.created+' reviewed candidates to project. You can edit their boundaries.');
  }
  async function run(fn:()=>Promise<void>){
    setBusy(true);setError('');
    try{await fn();}
    catch(cause){setError(cause instanceof Error?cause.message:'GeoAI operation failed.');}
    finally{setBusy(false);}
  }

  return <div className="professional-panel">
    <details>
      <summary><BrainCircuit size={14}/> GeoAI raster analysis & change detection</summary>
      <div className="professional-form">
        <p className="project-hint">
          Choose an explicit analysis operation. Spectral indices and change
          detection are deterministic; semantic classes require an installed ONNX model.
        </p>
        <select aria-label="GeoAI analysis operation" value={operation}
          onChange={event=>setOperation(event.target.value as Operation)}>
          <option value="spectral_index">Spectral index regions (NDVI / NDWI)</option>
          <option value="spectral_change">Two-date spectral change</option>
          <option value="semantic_segmentation">ONNX semantic segmentation</option>
        </select>
        <p className="project-hint">Current image: {p.image?.name||'None selected'} ·
          {p.image?.bands??0} bands. Select an image and project first.</p>
        {operation!=='semantic_segmentation'?<>
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
            {(models?.models||[]).map(item=>
              <option key={item.id} value={item.id}>
                {item.id} · {item.classes.length} classes
              </option>)}
          </select>
          <label>Minimum model confidence
            <input aria-label="Minimum model confidence" type="number" step=".05"
              min={0} max={1} value={confidence}
              onChange={e=>setConfidence(Number(e.target.value))}/>
          </label>
          <p className="project-hint">ONNX runtime: {models?.runtime_available?'installed':'not installed'};
            model weights and class/band metadata must be provisioned on the server.
            No model is silently downloaded.</p>
        </>}
        {<label><input type="checkbox"
            aria-label="Process full image at native pixel resolution"
            checked={fullResolution} onChange={e=>setFullResolution(e.target.checked)}/>
            Full-resolution streamed analysis
          </label>}
        {fullResolution?<>
          <p className="project-hint">Process every source pixel using bounded
            raster windows, a temporary disk-backed mask and seamless
            polygonization. Large images are limited by the configured pixel
            budget and source image size.</p>
          {operation==='semantic_segmentation'?
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
              <option value={64000000}>64 million</option>
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
        <button disabled={!p.projectId||!p.image||!token||processing||
          (operation==='semantic_segmentation'&&!modelId)}
          onClick={()=>void run(submit)}>Run georeferenced analysis</button>
        {job&&<div className="raster-details" aria-label="GeoAI task status">
          Task {job.id.slice(0,8)} · {job.status} · {job.progress}%
        </div>}
        {job?.status==='failed'&&<p className="discovery-error">{job.error}</p>}
        {result&&<>
          <div className="raster-details">
            <Layers3 size={14}/> {result.features.length} candidate regions ·
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
        </>}
        {message&&<p className="project-info">{message}</p>}
        {error&&<p className="discovery-error">{error}</p>}
      </div>
    </details>
  </div>;
}
