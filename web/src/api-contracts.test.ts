/** Assert the route, HTTP verb, wire payload and auth for each transport wrapper. */
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import * as api from './api';

const point:GeoJSON.Point={type:'Point',coordinates:[-83,40]};
const box:[number,number,number,number]=[-83,40,-82,41];
const positions:[number,number][]=[[-83,40],[-82,41]];
const project='p/a',feature='f?x',layer='l#1';
const P='/projects/p%2Fa',F=P+'/features/f%3Fx',L=P+'/layers/l%231';
const query='west=-83&south=40&east=-82&north=41';
const model:api.ModelDraft={id:'my/model',name:'Local model',provider:'ollama',model:'local',
  base_url:'http://localhost:11434',credential_env:'',enabled:true};
const source:api.NewOGCSource={service:'wfs',title:'Test',base_url:'https://example.test/wfs',
  layer_name:'layer',attribution:'test',tile_matrix_set:''};
const fetchMock=vi.fn<typeof fetch>();
beforeEach(()=>{
  fetchMock.mockReset();
  vi.stubGlobal('fetch',fetchMock);
  vi.stubGlobal('window',{sessionStorage:{getItem:()=> 'session-key'},setTimeout:(fn:()=>void)=>{fn();return 0;}});
  fetchMock.mockImplementation(async()=>Response.json({results:[],images:[],jobs:[]}));
});
afterEach(()=>vi.unstubAllGlobals());

type Case={name:string;call:()=>Promise<unknown>;path:string;method?:string;body?:unknown;admin?:string};
const cases:Case[]=[
  {name:'interpret defaults',call:()=>api.interpret('find park'),path:'/assistant',method:'POST',body:{message:'find park',bbox:null,model_id:'local-saluki'}},
  {name:'interpret bounded',call:()=>api.interpret('find park',box,'chosen'),path:'/assistant',method:'POST',body:{message:'find park',bbox:box,model_id:'chosen'}},
  {name:'measure',call:()=>api.measureGeometry(point),path:'/measure',method:'POST',body:{geometry:point}},
  {name:'discover',call:()=>api.discoverFeatures({bbox:box,category:'building',minimum_area_m2:0,maximum_area_m2:null}),path:'/discover',method:'POST',body:{bbox:box,category:'building',minimum_area_m2:0,maximum_area_m2:null}},
  {name:'projects',call:()=>api.getProjects(),path:'/projects'},
  {name:'new project',call:()=>api.newProject('name'),path:'/projects',method:'POST',body:{name:'name'}},
  {name:'project features',call:()=>api.getProjectFeatures(project),path:P+'/features'},
  {name:'feature without layer',call:()=>api.saveProjectFeature(project,'name',point,'manual'),path:P+'/features',method:'POST',body:{name:'name',geometry:point,source:'manual',properties:{},layer_id:null}},
  {name:'project export',call:()=>api.exportProject(project),path:P+'/export'},
  {name:'model probe',call:()=>api.probeModel('model'),path:'/models/probe',method:'POST',body:{model_id:'model'}},
  {name:'model catalog',call:()=>api.getModelCatalog(),path:'/models/catalog'},
  {name:'model save',call:()=>api.saveModel(model,'admin'),path:'/models/catalog/my%2Fmodel',method:'PUT',body:model,admin:'admin'},
  {name:'model delete',call:()=>api.deleteModel('my/model','admin'),path:'/models/catalog/my%2Fmodel',method:'DELETE',admin:'admin'},
  {name:'model selection',call:()=>api.selectDefaultModel('model','admin'),path:'/models/selection',method:'PUT',body:{model_id:'model'},admin:'admin'},
  {name:'imagery list',call:()=>api.listImagery(),path:'/imagery'},
  {name:'trace',call:()=>api.traceImagery({image_id:'scene',longitude:-83,latitude:40,method:'color',tolerance:20,window_size:512}),path:'/vision/trace',method:'POST',body:{image_id:'scene',longitude:-83,latitude:40,method:'color',tolerance:20,window_size:512}},
  {name:'catalog',call:()=>api.searchPublicImagery(box),path:'/imagery/catalog/search',method:'POST',body:{bbox:box,collection:'sentinel-2-l2a',limit:8}},
  {name:'construct',call:()=>api.constructGeometry({mode:'rectangle',vertices:positions}),path:'/edit/construct',method:'POST',body:{mode:'rectangle',vertices:positions}},
  {name:'validate',call:()=>api.validateGeometry(point),path:'/edit/validate',method:'POST',body:{geometry:point}},
  {name:'edit pair',call:()=>api.editPair('split',point,point),path:'/edit/split',method:'POST',body:{polygon:point,other:point}},
  {name:'overlay',call:()=>api.applyOverlay('intersection',point,point),path:'/analysis/overlay',method:'POST',body:{operation:'intersection',left:point,right:point}},
  {name:'move',call:()=>api.moveMeasured(point,75,100),path:'/edit/move',method:'POST',body:{geometry:point,bearing_deg:75,distance_m:100}},
  {name:'simplify',call:()=>api.simplifyVertices(positions,5),path:'/edit/simplify',method:'POST',body:{vertices:positions,tolerance_m:5}},
  {name:'workspace',call:()=>api.getWorkspace(project),path:P+'/workspace'},
  {name:'layer create',call:()=>api.createLayer(project,'Layer','#123456'),path:P+'/layers',method:'POST',body:{name:'Layer',color:'#123456'}},
  {name:'layer patch',call:()=>api.patchLayer(project,layer,{visible:false,locked:true}),path:L,method:'PATCH',body:{visible:false,locked:true}},
  {name:'feature patch',call:()=>api.updateProjectFeature(project,feature,{geometry:point,expected_revision:9}),path:F,method:'PATCH',body:{geometry:point,expected_revision:9}},
  {name:'history',call:()=>api.getFeatureHistory(project,feature),path:F+'/history'},
  {name:'restore',call:()=>api.restoreFeature(project,feature,7),path:F+'/restore/7',method:'POST'},
  {name:'copy',call:()=>api.copyProjectFeature(project,feature),path:F+'/copy',method:'POST'},
  {name:'batch',call:()=>api.saveFeatureBatch(project,[],'layer'),path:P+'/features/batch',method:'POST',body:{features:[],layer_id:'layer'}},
  {name:'batch default',call:()=>api.saveFeatureBatch(project,[]),path:P+'/features/batch',method:'POST',body:{features:[],layer_id:null}},
  {name:'attributes',call:()=>api.queryAttributes(project,{field:'height',operator:'gte',value:12}),path:P+'/attributes/query',method:'POST',body:{field:'height',operator:'gte',value:12}},
  {name:'attributes atomic',call:()=>api.saveAttributes(project,[{id:feature,expected_revision:3,properties:{height:20}}]),path:P+'/attributes/batch',method:'PATCH',body:{updates:[{id:feature,expected_revision:3,properties:{height:20}}]}},
  {name:'shared topology preview',call:()=>api.previewTopology(project,positions[0],positions[1]),path:P+'/topology/preview',method:'POST',body:{old:positions[0],new:positions[1],tolerance_m:.05}},
  {name:'shared topology commit',call:()=>api.applyTopology(project,positions[0],positions[1],{f:7}),path:P+'/topology/move',method:'POST',body:{old:positions[0],new:positions[1],expected_revisions:{f:7},tolerance_m:.05}},
  {name:'trace network',call:()=>api.traceExisting(positions[0],positions[1],[positions]),path:'/edit/trace',method:'POST',body:{start:positions[0],end:positions[1],paths:[positions],tolerance_m:30}},
  {name:'terrain',call:()=>api.analyzeTerrain('dem',point),path:'/terrain/analyze',method:'POST',body:{image_id:'dem',geometry:point,vertical_unit:'meter'}},
  {name:'terrain profile',call:()=>api.terrainProfile('dem',point),path:'/terrain/profile',method:'POST',body:{image_id:'dem',geometry:point,samples:80}},
  {name:'mask refinement',call:()=>api.refineRaster({image_id:'scene',positive_points:positions,negative_points:[],box:null,window_size:512}),path:'/vision/refine',method:'POST',body:{image_id:'scene',positive_points:positions,negative_points:[],box:null,window_size:512}},
  {name:'layer style revision',call:()=>api.patchLayerStyle(project,layer,{labels:{enabled:true},expected_revision:2}),path:L+'/style',method:'PATCH',body:{labels:{enabled:true},expected_revision:2}},
  {name:'annotation',call:()=>api.addMapAnnotation(project,'note',positions[0],layer),path:P+'/annotations',method:'POST',body:{text:'note',position:positions[0],layer_id:layer}},
  {name:'annotation default',call:()=>api.addMapAnnotation(project,'note',positions[0]),path:P+'/annotations',method:'POST',body:{text:'note',position:positions[0],layer_id:null}},
  {name:'spatial defaults',call:()=>api.selectSpatialFeatures(project,point),path:P+'/spatial/select',method:'POST',body:{geometry:point,relation:'intersects',layer_ids:null,visible_only:true,limit:500,offset:0}},
  {name:'spatial custom',call:()=>api.selectSpatialFeatures(project,point,'touches',[layer],false,10,20),path:P+'/spatial/select',method:'POST',body:{geometry:point,relation:'touches',layer_ids:[layer],visible_only:false,limit:10,offset:20}},
  {name:'QA',call:()=>api.reviewTopology(project,{minimum_area_m2:.5,check_dangles:true}),path:P+'/quality/topology',method:'POST',body:{minimum_area_m2:.5,check_dangles:true}},
  {name:'CRS',call:()=>api.getProjectCRS(project),path:P+'/crs'},
  {name:'transform',call:()=>api.transformProjectCoordinates(project,positions,'EPSG:26917'),path:P+'/crs/transform',method:'POST',body:{points:positions,target:'EPSG:26917',source:'EPSG:4326'}},
  {name:'grid',call:()=>api.getProjectGrid(project,box),path:P+'/crs/grid?'+query+'&divisions=5'},
  {name:'classify',call:()=>api.classifyValues([1,2,3],'quantile',2),path:'/analysis/classify',method:'POST',body:{values:[1,2,3],method:'quantile',classes:2}},
  {name:'graduated',call:()=>api.saveGraduatedStyle(project,{layer_id:layer,field:'height',classes:3,method:'jenks',expected_revision:4}),path:P+'/symbology/graduated',method:'POST',body:{layer_id:layer,field:'height',classes:3,method:'jenks',expected_revision:4}},
  {name:'OGC sources',call:()=>api.getOGCSources(project),path:P+'/ogc'},
  {name:'OGC register',call:()=>api.registerOGCSource(project,source,'admin'),path:P+'/ogc',method:'POST',body:source,admin:'admin'},
  {name:'OGC inspect',call:()=>api.inspectOGCSource(project,'source/x'),path:P+'/ogc/source%2Fx/capabilities'},
  {name:'OGC query',call:()=>api.remoteOGCFeatures(project,'source/x',box),path:P+'/ogc/source%2Fx/features?'+query+'&limit=100'},
  {name:'postgis status',call:()=>api.getPostGISStatus(),path:'/postgis/status'},
  {name:'postgis sync',call:()=>api.syncPostGIS(project,'admin'),path:P+'/postgis/sync',method:'POST',body:{max_features:100000},admin:'admin'},
  {name:'postgis query',call:()=>api.queryPostGIS(project,box,100,200),path:P+'/postgis/features?'+query+'&limit=100&offset=200'},
  {name:'vision models',call:()=>api.getVisionModels(),path:'/vision/models/segmentation'},
  {name:'jobs',call:()=>api.getGISJobs(project),path:P+'/jobs'},
  {name:'job result',call:()=>api.getGISJob(project,'id'),path:P+'/jobs/id?include_result=true'},
  {name:'job no admin credential',call:()=>api.queueGISJob(project,'topology_qa',{}),path:P+'/jobs',method:'POST',body:{kind:'topology_qa',payload:{}},admin:''},
];
it.each(cases)('$name transport contract',async row=>{
  await row.call();
  expect(fetchMock).toHaveBeenCalledOnce();
  const [url,init]=fetchMock.mock.calls[0];
  const target=new URL(String(url));
  expect(target.pathname+target.search).toBe(row.path);
  expect(init?.method??'GET').toBe(row.method??'GET');
  const headers=new Headers(init?.headers);
  expect(headers.get('X-GeoFathom-API-Key')).toBe('session-key');
  expect(headers.get('X-GeoFathom-Admin-Token')).toBe(row.admin??null);
  if(row.body!==undefined){
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(JSON.parse(String(init?.body))).toEqual(row.body);
  }else expect(init?.body).toBeUndefined();
});

it('multipart uploads keep administrator key and leave the boundary to fetch',async()=>{
  const file=new File(['data'],'image.tif');
  await api.uploadImagery(file,'admin');
  let [url,init]=fetchMock.mock.calls.at(-1)!;
  expect(new URL(String(url)).pathname).toBe('/imagery/upload');
  expect(new Headers(init?.headers).get('X-GeoFathom-Admin-Token')).toBe('admin');
  expect(new Headers(init?.headers).has('Content-Type')).toBe(false);
  expect((init?.body as FormData).get('file')).toBeInstanceOf(File);
  await api.importVectorFile(project,file,layer);
  [url,init]=fetchMock.mock.calls.at(-1)!;
  expect(new URL(String(url)).searchParams.get('layer_id')).toBe(layer);
  expect(init?.method).toBe('POST');
  await api.importVectorFile(project,file);
  expect(new URL(String(fetchMock.mock.calls.at(-1)![0])).search).toBe('');
});

it('binary preview, PDF and job download authenticate and dispose URLs',async()=>{
  const asset={preview_url:'/imagery/scene/preview'} as api.RasterAsset;
  expect(new URL(api.rasterPreviewUrl(asset)).pathname).toBe(asset.preview_url);
  expect(api.ogcTileTemplate(project,'id')).toContain(P+'/ogc/id/tiles/{z}/{x}/{y}');
  const link={href:'',download:'',click:vi.fn(),remove:vi.fn()};
  vi.stubGlobal('document',{createElement:()=>link,body:{appendChild:vi.fn()}});
  const create=vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:xyz');
  const revoke=vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>{});
  try{
    fetchMock.mockResolvedValueOnce(new Response('image'));
    expect(await api.protectedRasterPreview(asset)).toBe('blob:xyz');
    const settings={title:'Map',paper:'a4',orientation:'portrait',extent:null,show_grid:true,show_legend:false,layer_ids:null} as const;
    fetchMock.mockResolvedValueOnce(new Response('%PDF'));
    await api.downloadMapPDF(project,settings);
    expect(link.download).toBe('geofathom-map.pdf');
    expect(JSON.parse(String(fetchMock.mock.calls.at(-1)![1]?.body))).toEqual(settings);
    fetchMock.mockResolvedValueOnce(new Response('{}'));
    await api.downloadGISJob(project,'task');
    expect(link.download).toBe('geofathom-export.geojson');
    expect(link.remove).toHaveBeenCalledTimes(2);
    expect(revoke).toHaveBeenCalledTimes(2);
    fetchMock.mockResolvedValueOnce(new Response('no',{status:403}));
    await expect(api.protectedRasterPreview(asset)).rejects.toThrow('requires server access');
    fetchMock.mockResolvedValueOnce(Response.json({detail:'bad layout'},{status:422}));
    await expect(api.downloadMapPDF(project,settings)).rejects.toThrow('bad layout');
    fetchMock.mockResolvedValueOnce(new Response('no',{status:409}));
    await expect(api.downloadGISJob(project,'task')).rejects.toThrow('Completed GeoJSON');
    fetchMock.mockResolvedValueOnce(new Response('no',{status:403}));
    await expect(api.removeOGCSource(project,'task','admin')).rejects.toThrow('Could not remove');
    for(const [,init] of fetchMock.mock.calls)
      expect(new Headers(init?.headers).get('X-GeoFathom-API-Key')).toBe('session-key');
  }finally{create.mockRestore();revoke.mockRestore();}
});
