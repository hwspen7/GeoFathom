import {useEffect,useRef,useState} from 'react';
import {Database,Globe2,Layers3,RefreshCcw} from 'lucide-react';
import {cancelGISJob,downloadGISJob,getGISJobs,getOGCSources,getPostGISStatus,
  inspectOGCSource,ogcTileTemplate,queueGISJob,registerOGCSource,
  remoteOGCFeatures,removeOGCSource,saveFeatureBatch,queryPostGIS,
  viewportFeatures,type GISJob,type GISJobKind,type OGCSource,
  type PostGISStatus,type WorkspaceFeature} from './api';

type BBox=[number,number,number,number];
export interface ExternalTile {
  id:string;template:string;title:string;attribution:string;
}
interface Props{
  projectId:string|null;
  viewport:BBox|null;
  drawnGeometry:GeoJSON.Geometry|null;
  onTiles:(tiles:ExternalTile[])=>void;
  onPreview:(geometry:GeoJSON.Geometry[])=>void;
  onPage:(features:WorkspaceFeature[])=>void;
  onRefresh:()=>void;
  view?:'sources'|'database'|'jobs';
}
export default function DataServicesPanel(p:Props){
  const [sources,setSources]=useState<OGCSource[]>([]);
  const [sourcePage,setSourcePage]=useState(0);
  const [jobPage,setJobPage]=useState(0);
  const [sourceView,setSourceView]=useState<'connect'|'browse'>('browse');
  const [visibleTiles,setVisibleTiles]=useState<string[]>([]);
  const [service,setService]=useState<OGCSource['service']>('wms');
  const [title,setTitle]=useState('New geospatial service');
  const [url,setURL]=useState('');
  const [layer,setLayer]=useState('');
  const [matrixSet,setMatrixSet]=useState('GoogleMapsCompatible');
  const [attribution,setAttribution]=useState('');
  const [adminToken,setAdminToken]=useState('');
  const [remote,setRemote]=useState<GeoJSON.FeatureCollection|null>(null);
  const [status,setStatus]=useState<PostGISStatus|null>(null);
  const [jobs,setJobs]=useState<GISJob[]>([]);
  const [jobKind,setJobKind]=useState<GISJobKind>('topology_qa');
  const [featuresLoaded,setFeaturesLoaded]=useState(0);
  const [pageOffset,setPageOffset]=useState(0);
  const [info,setInfo]=useState('');
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const activeProject=useRef(p.projectId);
  activeProject.current=p.projectId;
  async function load(){
    const projectId=p.projectId;
    if(!projectId)return;
    try{
      const [ogc,tasks,pg]=await Promise.all([
        getOGCSources(projectId),getGISJobs(projectId),getPostGISStatus(),
      ]);
      // Ignore late responses for a project that is no longer active.
      if(activeProject.current!==projectId)return;
      setSources(ogc.sources);setJobs(tasks.jobs);setStatus(pg);
    }catch(cause){
      if(activeProject.current===projectId)
        setError(cause instanceof Error?cause.message:'Cannot load GIS services.');
    }
  }
  useEffect(()=>{
    setSources([]);setVisibleTiles([]);setRemote(null);
    setJobs([]);setInfo('');setError('');setPageOffset(0);
    setSourcePage(0);setJobPage(0);
    void load();
  },[p.projectId]);
  useEffect(()=>{
    setSourcePage(page=>Math.min(page,Math.max(0,Math.ceil(sources.length/2)-1)));
  },[sources.length]);
  useEffect(()=>{
    setJobPage(page=>Math.min(page,Math.max(0,Math.ceil(jobs.length/3)-1)));
  },[jobs.length]);
  useEffect(()=>{
    const projectId=p.projectId;
    if(!projectId)return;
    const timer=window.setInterval(()=>{
      getGISJobs(projectId).then(data=>{
        if(activeProject.current===projectId)setJobs(data.jobs);
      }).catch(()=>{});
    },2000);
    return ()=>window.clearInterval(timer);
  },[p.projectId]);
  useEffect(()=>{
    const active=sources.filter(item=>
      (item.service==='wms'||item.service==='wmts')&&visibleTiles.includes(item.id));
    p.onTiles(active.map(item=>({id:item.id,title:item.title,
      attribution:item.attribution,
      template:ogcTileTemplate(item.project_id,item.id)})));
  },[sources,visibleTiles,p.projectId]);
  async function run(task:()=>Promise<void>){
    setBusy(true);setError('');setInfo('');
    try{await task();}
    catch(cause){setError(cause instanceof Error?cause.message:'Data service operation failed.');}
    finally{setBusy(false);}
  }
  async function add(){
    if(!p.projectId)return;
    const saved=await registerOGCSource(p.projectId,{
      service,title,base_url:url,layer_name:layer,attribution,tile_matrix_set:matrixSet,
    },adminToken);
    setSources(old=>[...old,saved]);
    setInfo('OGC source registered. Add its hostname to the server allowlist first.');
  }
  async function inspect(source:OGCSource){
    if(!p.projectId)return;
    const meta=await inspectOGCSource(p.projectId,source.id);
    setInfo('Capabilities: '+JSON.stringify(meta).slice(0,500));
  }
  async function preview(source:OGCSource){
    const projectId=p.projectId;
    if(!projectId||!p.viewport)return;
    const collection=await remoteOGCFeatures(projectId,source.id,p.viewport);
    if(activeProject.current!==projectId)return;
    setRemote(collection);
    p.onPreview(collection.features.map(item=>item.geometry).filter(
      (value):value is GeoJSON.Geometry=>Boolean(value)));
    setInfo('Fetched '+collection.features.length+' georeferenced remote objects for review.');
  }
  async function importRemote(){
    if(!remote||!p.projectId||!remote.features.length)return;
    const rows=remote.features.slice(0,100).map((feature,index)=>({
      name:String(feature.properties?.name||'Imported OGC feature '+(index+1)).slice(0,150),
      source:'OGC service import',geometry:feature.geometry as GeoJSON.Geometry,
      properties:feature.properties||{},
    }));
    const saved=await saveFeatureBatch(p.projectId,rows);
    setInfo('Imported '+saved.created+' remote features to the active project.');
    setRemote(null);p.onPreview([]);p.onRefresh();
  }
  async function submit(){
    if(!p.projectId)return;
    if(jobKind==='spatial_select'&&!p.drawnGeometry)
      throw Error('Draw/select an area before queuing spatial selection.');
    const payload:Record<string,unknown>=jobKind==='spatial_select'?
      {geometry:p.drawnGeometry,relation:'intersects'}:{};
    const result=await queueGISJob(p.projectId,jobKind,payload,adminToken);
    setJobs(list=>[result,...list.filter(job=>job.id!==result.id)]);
    setInfo('Queued '+result.kind+' as '+result.id.slice(0,8)+'.');
  }
  async function readViewport(usePostgis:boolean){
    const projectId=p.projectId;
    if(!projectId||!p.viewport)throw Error('Map viewport unavailable.');
    const page=usePostgis
      ?await queryPostGIS(projectId,p.viewport,500,pageOffset)
      :await viewportFeatures(projectId,p.viewport,500,pageOffset);
    // Never paint a previous project's page into the newly selected project.
    if(activeProject.current!==projectId)return;
    p.onPage(page.results);setFeaturesLoaded(page.total);
    setInfo((usePostgis?'PostGIS GiST: ':'SQLite R-tree: ')+
      page.results.length+' of '+page.total+' region features.');
  }

  return <div className="professional-panel">
    <details open={p.view==='sources'?true:undefined} hidden={Boolean(p.view&&p.view!=='sources')}>
      <summary><Globe2 size={14}/> OGC map & feature services</summary>
      <div className="professional-form">
        <div className="data-choice-buttons">
          <button type="button" aria-pressed={sourceView==='browse'}
            onClick={()=>setSourceView('browse')}>Registered · {sources.length}</button>
          <button type="button" aria-pressed={sourceView==='connect'}
            onClick={()=>setSourceView('connect')}>Add source</button>
        </div>
        <div className="data-service-connect" hidden={sourceView!=='connect'}>
        <p className="project-hint">Connect WMS/WMTS imagery tiles and
          WFS/OGC API Features vectors. Remote HTTPS hostnames must be
          explicitly approved in the server environment.</p>
        <div className="area-fields">
          <select aria-label="New OGC service type" value={service}
            onChange={event=>setService(event.target.value as OGCSource['service'])}>
            <option value="wms">WMS raster map</option>
            <option value="wmts">WMTS map tiles</option>
            <option value="wfs">WFS GeoJSON features</option>
            <option value="ogc_features">OGC API Features</option>
          </select>
          <input aria-label="OGC layer or collection" maxLength={100}
            value={layer} placeholder="Layer / collection"
            onChange={event=>setLayer(event.target.value)}/>
        </div>
        <input aria-label="OGC display title" maxLength={100}
          value={title} onChange={event=>setTitle(event.target.value)}/>
        <input aria-label="OGC HTTPS endpoint" type="url"
          value={url} placeholder="https://maps.example.org/ows"
          onChange={event=>setURL(event.target.value)}/>
        {service==='wmts'&&<input aria-label="WMTS tile matrix set"
          value={matrixSet} onChange={event=>setMatrixSet(event.target.value)}/>}
        <input aria-label="OGC attribution" value={attribution}
          maxLength={240} placeholder="Data provider and license"
          onChange={event=>setAttribution(event.target.value)}/>
        <input aria-label="GIS administrator token" type="password"
          value={adminToken} placeholder="Administrator token (server configuration)"
          onChange={event=>setAdminToken(event.target.value)}/>
        <button disabled={!p.projectId||!url||!layer||busy}
          onClick={()=>void run(add)}>Register OGC source</button>
        </div>
        <div className="data-service-browse" hidden={sourceView!=='browse'}>
        <div className="gis-result-list">
          <strong>{sources.length} configured services</strong>
          {sources.slice(sourcePage*2,(sourcePage+1)*2).map(source=><div key={source.id} className="service-entry">
            <strong>{source.title} · {source.service.toUpperCase()}</strong>
            <small>{source.layer_name} · {source.base_url}</small>
            <div className="survey-action-bar">
              {(source.service==='wms'||source.service==='wmts')&&
                <button aria-label={'Toggle OGC raster '+source.title}
                  onClick={()=>setVisibleTiles(old=>old.includes(source.id)?
                    old.filter(id=>id!==source.id):[...old,source.id])}>
                  {visibleTiles.includes(source.id)?'Hide':'Show'} tiles
                </button>}
              {(source.service==='wfs'||source.service==='ogc_features')&&
                <button disabled={!p.viewport||busy} onClick={()=>void run(()=>preview(source))}>
                  Preview features
                </button>}
              <button disabled={busy} onClick={()=>void run(()=>inspect(source))}>
                Capabilities
              </button>
              <button disabled={busy} onClick={()=>void run(async()=>{
                await removeOGCSource(p.projectId!,source.id,adminToken);
                setSources(old=>old.filter(item=>item.id!==source.id));
                setVisibleTiles(old=>old.filter(id=>id!==source.id));
              })}>Remove</button>
            </div>
          </div>)}
        </div>
        {sources.length>2&&<div className="gis-record-pager">
          <button type="button" disabled={sourcePage===0} onClick={()=>setSourcePage(v=>v-1)}>Previous</button>
          <span>{sourcePage+1}/{Math.ceil(sources.length/2)}</span>
          <button type="button" disabled={(sourcePage+1)*2>=sources.length}
            onClick={()=>setSourcePage(v=>v+1)}>Next</button>
        </div>}
        {remote&&<button disabled={busy||!remote.features.length}
          onClick={()=>void run(importRemote)}>
          Import {remote.features.length} previewed objects into project
        </button>}
        </div>
      </div>
    </details>
    <details open={p.view==='database'?true:undefined} hidden={Boolean(p.view&&p.view!=='database')}>
      <summary><Database size={14}/> Spatial database & indexed viewport</summary>
      <div className="professional-form">
        <p className="project-hint">SQLite R-tree is available without extra
          setup. PostGIS is an optional external indexed mirror, not the
          authoritative editor database.</p>
        {status&&<p aria-label="PostGIS status" className="project-hint">
          PostGIS: {status.connected?'Connected':status.configured?'Configured, offline':
            'Not configured'} · {status.note}
        </p>}
        <label>Page offset
          <input aria-label="Viewport page offset" type="number" min={0}
            max={1000000} value={pageOffset}
            onChange={event=>setPageOffset(Number(event.target.value))}/>
        </label>
        <div className="survey-action-bar">
          <button disabled={busy||!p.projectId||!p.viewport}
            onClick={()=>void run(()=>readViewport(false))}>Load SQLite R-tree page</button>
          <button disabled={busy||!p.projectId||!p.viewport||!status?.connected}
            onClick={()=>void run(()=>readViewport(true))}>Load PostGIS page</button>
        </div>
        <p className="project-hint">Last regional query: {featuresLoaded} matching
          features. 500 features are loaded per page.</p>
        <button disabled={busy} onClick={()=>void load()}>
          <RefreshCcw size={14}/> Refresh service status
        </button>
      </div>
    </details>
    <details open={p.view==='jobs'?true:undefined} hidden={Boolean(p.view&&p.view!=='jobs')}>
      <summary><Layers3 size={14}/> Persistent background GIS jobs</summary>
      <div className="professional-form">
        <select aria-label="Background GIS job type" value={jobKind}
          onChange={event=>setJobKind(event.target.value as GISJobKind)}>
          <option value="topology_qa">Topology QA</option>
          <option value="spatial_select">Select from current geometry</option>
          <option value="export_geojson">Export project GeoJSON</option>
          <option value="postgis_sync">Sync project to PostGIS</option>
          <option value="rebuild_index">Rebuild SQLite spatial index</option>
        </select>
        <button disabled={busy||!p.projectId} onClick={()=>void run(submit)}>
          Queue background operation
        </button>
        <div className="gis-result-list" aria-label="GIS background tasks">
          {jobs.slice(jobPage*3,(jobPage+1)*3).map(job=><div key={job.id} className="service-entry">
            <strong>{job.kind} · {job.status}</strong>
            <small>{job.progress}% · {job.id.slice(0,8)}</small>
            {job.error&&<small>{job.error}</small>}
            <div className="survey-action-bar">
              {job.kind==='export_geojson'&&job.status==='completed'&&
                <button onClick={()=>void run(()=>downloadGISJob(p.projectId!,job.id))}>
                  Download GeoJSON
                </button>}
              {(job.status==='queued'||job.status==='running')&&
                <button onClick={()=>void run(async()=>{
                  await cancelGISJob(p.projectId!,job.id);
                  const updated=await getGISJobs(p.projectId!);
                  setJobs(updated.jobs);
                })}>Cancel job</button>}
            </div>
          </div>)}
          {!jobs.length&&<small>No background tasks.</small>}
          {jobs.length>3&&<div className="gis-record-pager">
            <button type="button" disabled={jobPage===0} onClick={()=>setJobPage(v=>v-1)}>Previous</button>
            <span>{jobPage+1}/{Math.ceil(jobs.length/3)}</span>
            <button type="button" disabled={(jobPage+1)*3>=jobs.length}
              onClick={()=>setJobPage(v=>v+1)}>Next</button>
          </div>}
        </div>
      </div>
    </details>
    {info&&<p className="project-info">{info}</p>}
    {error&&<p className="discovery-error">{error}</p>}
  </div>;
}
