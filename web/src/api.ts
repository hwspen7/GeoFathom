// A same-origin local proxy avoids localhost/IPv4 and CORS mismatches.
const API_URL = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');
export class ApiError extends Error {
  constructor(message:string,public readonly status:number|null){
    super(message);this.name='ApiError';
  }
}
export function backendUnavailable(error:unknown):boolean{
  return error instanceof ApiError&&(error.status===null||[500,502,503,504].includes(error.status));
}

export interface Place {
  id: string;
  name: string;
  display_name: string;
  longitude: number;
  latitude: number;
  bbox: [number, number, number, number] | null;
  geometry: GeoJSON.Geometry | null;
  boundary_status: 'mapped' | 'location_only';
  source: string;
  osm_type: string | null;
  osm_id: number | null;
}

export interface Measurement {
  geometry_type: string;
  edge_lengths_m?: number[];
  area_m2: number | null;
  area_km2: number | null;
  perimeter_m: number | null;
  length_m: number | null;
  bounds: number[];
  coordinate_count: number;
  method: string;
  note: string;
}

export interface AssistantResult {
  status: string;
  message: string;
  intent: { action: string; query: string; explanation: string };
  model_used: boolean;
  results: Place[];
  measurement: Measurement | null;
  steps?: Array<{ tool: string; status: string; details: string }>;
}

export interface Capabilities {
  geocoding: string;
  geodesic_measurement: boolean;
  geojson_export: boolean;
  llm_provider: string | null;
  llm_model?: string | null;
  llm_configured?: boolean;
  analysis_configured?: boolean;
  analysis_model?: string | null;
  persistent_projects?: boolean;
  spatial_analysis?: string[];
  vision_segmentation: boolean;
  spatial_discovery: string;
  imagery: string;
  local_raster_import?:boolean;
}

export function setApiAccessToken(token: string): void {
  if (token) window.sessionStorage.setItem('geofathom-api-token', token);
  else window.sessionStorage.removeItem('geofathom-api-token');
}

// Every protected API operation, including binary downloads and DELETEs,
 // uses the same session-scoped credential. Never put credentials into URLs.
function sessionHeaders(initial?: HeadersInit): Headers {
  const headers = new Headers(initial);
  const key = typeof window !== 'undefined'
    ? window.sessionStorage.getItem('geofathom-api-token') : null;
  if (key) headers.set('X-GeoFathom-API-Key', key);
  return headers;
}
async function rawRequest(path: string, init?: RequestInit): Promise<Response> {
  // Local geometry and project requests must not strand the editor indefinitely.
  const exchange=/\/(vector|package)(?:\/|$)/.test(path);
  const fast=!exchange&&/^\/(measure|edit\/|health|capabilities|projects(?:\/|$))/.test(path);
  const timeout=/^\/terrain\/(analyze|advanced)$/.test(path)?1_800_000:fast?12000:120000;
  try{
    return await fetch(API_URL+path,{...init,headers:sessionHeaders(init?.headers),
      signal:init?.signal?AbortSignal.any([init.signal,AbortSignal.timeout(timeout)]):AbortSignal.timeout(timeout)});
  }catch(error){
    if(init?.signal?.aborted)throw new DOMException('Request cancelled','AbortError');
    const detail=error instanceof Error?error.message:String(error);
    throw new ApiError('API connection failed. Start GeoFathom backend and reconnect. ('+detail+')',null);
  }
}
async function responseError(response: Response, fallback = 'Request failed'): Promise<Error> {
  let detail = fallback;
  try {
    const error = (await response.json()) as { detail?: unknown };
    if (typeof error?.detail === 'string') detail = error.detail;
  } catch {
    detail = response.statusText || detail;
  }
  return new ApiError(detail||fallback,response.status);
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await rawRequest(path, init);
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as T;
}

export async function searchPlaces(query: string): Promise<Place[]> {
  const payload = await request<{ results: Place[] }>('/search?q=' + encodeURIComponent(query));
  return payload.results;
}

export function interpret(message: string, bbox?: [number, number, number, number] | null, modelId: string = 'local-saluki'): Promise<AssistantResult> {
  return request<AssistantResult>('/assistant', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, bbox: bbox || null, model_id: modelId }),
  });
}

export function measureGeometry(geometry: GeoJSON.Geometry): Promise<Measurement> {
  return request<Measurement>('/measure', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ geometry }),
  });
}

export function checkReady():Promise<{status:string;checks:Record<string,boolean>}>{
  return request('/health/ready');
}

export function getCapabilities(): Promise<Capabilities> {
  return request<Capabilities>('/capabilities');
}


export interface DiscoveryRequest {
  bbox: [number, number, number, number];
  category: 'building' | 'landuse' | 'water';
  minimum_area_m2: number;
  maximum_area_m2: number | null;
}

export interface DiscoveryResponse {
  results: Place[];
  checked: number;
  truncated: boolean;
  warning: string;
  category: string;
  source: string;
}

export function discoverFeatures(body: DiscoveryRequest): Promise<DiscoveryResponse> {
  return request<DiscoveryResponse>('/discover', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}


export interface Project {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface StoredFeature {
  id: string;
  project_id: string;
  name: string;
  geometry: GeoJSON.Geometry;
  properties: Record<string, unknown>;
  source: string;
  created_at: string;
  measurement: Measurement;
}

export async function getProjects(): Promise<Project[]> {
  const page = await request<{ results: Project[]; total: number }>('/projects');
  return page.results;
}

export function newProject(name: string): Promise<Project> {
  return request<Project>('/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}

export async function getProjectFeatures(projectId: string): Promise<StoredFeature[]> {
  const response = await request<{ results: StoredFeature[]; total: number }>(
    '/projects/' + encodeURIComponent(projectId) + '/features',
  );
  return response.results;
}

export function saveProjectFeature(projectId: string, name: string, geometry: GeoJSON.Geometry, source: string, properties: Record<string, unknown> = {}, layerId?: string): Promise<StoredFeature> {
  return request<StoredFeature>('/projects/' + encodeURIComponent(projectId) + '/features', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, geometry, source, properties, layer_id: layerId || null }),
  });
}

export function exportProject(projectId: string): Promise<GeoJSON.FeatureCollection> {
  return request<GeoJSON.FeatureCollection>('/projects/' + encodeURIComponent(projectId) + '/export');
}

export interface ModelProbe {
  status: 'ready';
  profile: 'default' | 'analysis';
  model_id?: string | null;
  provider: string;
  model: string;
  live_call: boolean;
  intent: { action: string; query: string; explanation: string };
}

export function probeModel(modelId: string): Promise<ModelProbe> {
  return request<ModelProbe>('/models/probe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_id: modelId }),
  });
}


export type ModelProvider = 'ollama' | 'openai-compatible' | 'groq' | 'gemini';

export interface ModelDefinition {
  id: string;
  name: string;
  provider: ModelProvider;
  model: string;
  base_url: string;
  credential_env: string;
  enabled: boolean;
  configured: boolean;
  preset: boolean;
}

export type ModelDraft = Omit<ModelDefinition, 'configured' | 'preset'>;

export interface ModelCatalog {
  default_id: string;
  models: ModelDefinition[];
  note: string;
}

export function getModelCatalog(): Promise<ModelCatalog> {
  return request<ModelCatalog>('/models/catalog');
}

export function saveModel(model: ModelDraft, token: string): Promise<ModelCatalog> {
  return request<ModelCatalog>('/models/catalog/' + encodeURIComponent(model.id), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'X-GeoFathom-Admin-Token': token },
    body: JSON.stringify(model),
  });
}

export function deleteModel(modelId: string, token: string): Promise<ModelCatalog> {
  return request<ModelCatalog>('/models/catalog/' + encodeURIComponent(modelId), {
    method: 'DELETE',
    headers: { 'X-GeoFathom-Admin-Token': token },
  });
}

export function selectDefaultModel(modelId: string, token: string): Promise<ModelCatalog> {
  return request<ModelCatalog>('/models/selection', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'X-GeoFathom-Admin-Token': token },
    body: JSON.stringify({ model_id: modelId }),
  });
}


export interface RasterAsset {
  id: string;
  name: string;
  width: number;
  height: number;
  bands: number;
  crs: string;
  bbox: [number, number, number, number];
  corners: [[number, number], [number, number], [number, number], [number, number]];
  preview_url: string;
  acquired_at: string | null;
  // These values are declared by the source file, never inferred from the
  // requested output grid and never treated as verified geodetic control.
  resolution_unit?: string;
  sha256?: string;
  vertical_unit?: string | null;
  vertical_datum?: string | null;
  provenance: string;
}

export interface RasterTrace {
  image_id: string;
  geometry: GeoJSON.Geometry;
  measurement: Measurement;
  provider: 'color' | 'sam2';
  engine: string;
  pixel_count: number;
  confidence: number | null;
  model_id: string | null;
  boundary_status: string;
  warning: string;
  window_truncated: boolean;
  source: string;
}

export async function listImagery(): Promise<RasterAsset[]> {
  const response = await request<{ images: RasterAsset[] }>('/imagery');
  return response.images;
}

export async function uploadImagery(file: File, adminToken: string): Promise<RasterAsset> {
  const data = new FormData();
  data.append('file', file);
  return request<RasterAsset>('/imagery/upload', {
    method: 'POST',
    headers: adminToken ? { 'X-GeoFathom-Admin-Token': adminToken } : { 'X-GeoFathom-Local-Import': '1' },
    body: data,
  });
}

export function traceImagery(body: {
  image_id: string; longitude: number; latitude: number;
  method: 'color' | 'sam2'; tolerance: number; window_size: number;
}): Promise<RasterTrace> {
  return request<RasterTrace>('/vision/trace', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function rasterPreviewUrl(asset: RasterAsset): string {
  return API_URL + asset.preview_url;
}

/** Fetch protected imagery with the session credential; caller revokes blob URL. */
export async function protectedRasterPreview(asset: RasterAsset): Promise<string> {
  const response = await rawRequest(asset.preview_url);
  if (!response.ok) throw new Error('The image preview requires server access.');
  return URL.createObjectURL(await response.blob());
}


export interface StacItem {
  id: string;
  collection: string;
  datetime: string | null;
  cloud_cover: number | null;
  bbox: number[] | null;
  catalog_url: string | null;
  source: string;
}

export interface StacSearchResult {
  items: StacItem[];
  count: number;
  warning: string;
}

export function searchPublicImagery(
  bbox: [number, number, number, number],
  collection = 'sentinel-2-l2a',
  dates?:{start_date?:string;end_date?:string},
): Promise<StacSearchResult> {
  return request<StacSearchResult>('/imagery/catalog/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bbox, collection, limit: 8, ...dates }),
  });
}


export type ShapeConstruction = 'polygon' | 'rectangle' | 'circle' | 'bearing';
export type EditResponse = { geometry: GeoJSON.Geometry; measurement: Measurement };

export function constructGeometry(body: {
  mode: ShapeConstruction; vertices: [number, number][];
  radius_m?: number; bearing_deg?: number; length_m?: number; segments?: number;
}): Promise<EditResponse> {
  return request<EditResponse>('/edit/construct', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function validateGeometry(geometry: GeoJSON.Geometry): Promise<{
  valid: boolean; message: string; measurement: Measurement | null;
}> {
  return request('/edit/validate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ geometry }),
  });
}

export function editPair(
  operation: 'hole' | 'split', polygon: GeoJSON.Geometry, other: GeoJSON.Geometry,
): Promise<EditResponse & { features: EditResponse[] }> {
  return request('/edit/' + operation, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ polygon, other }),
  });
}

export function applyOverlay(
  operation: 'union' | 'difference' | 'intersection',
  left: GeoJSON.Geometry, right: GeoJSON.Geometry,
): Promise<{ geometry: GeoJSON.Geometry | null; measurement: Measurement | null }> {
  return request('/analysis/overlay', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operation, left, right }),
  });
}

export function moveMeasured(
  geometry: GeoJSON.Geometry, bearing_deg: number, distance_m: number,
): Promise<EditResponse> {
  return request('/edit/move', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ geometry, bearing_deg, distance_m }),
  });
}

export function simplifyVertices(
  vertices: [number, number][], tolerance_m: number,
): Promise<{ vertices: [number, number][]; retained: number; engine: string }> {
  return request('/edit/simplify', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ vertices, tolerance_m }),
  });
}

export interface GeoLayer {
  id: string;
  project_id: string;
  name: string;
  color: string;
  visible: number;
  locked: number;
  z_index: number;
  style: LayerStyle;
  style_revision: number;
}

export interface WorkspaceFeature extends StoredFeature {
  layer_id: string;
  revision: number;
}

export interface GeoWorkspace {
  layers: GeoLayer[];
  features: WorkspaceFeature[];
  total: number;
}

export interface FeatureRevision {
  revision: number;
  name: string;
  geometry: GeoJSON.Geometry;
  properties: Record<string, unknown>;
  created_at: string;
  measurement?: Measurement;
}
export interface FeatureHistory {
  feature_id: string;
  current_revision: number;
  versions: FeatureRevision[];
}

export function getWorkspace(projectId: string): Promise<GeoWorkspace> {
  return request('/projects/' + encodeURIComponent(projectId) + '/workspace');
}

export function createLayer(projectId: string, name: string, color: string): Promise<GeoLayer> {
  return request('/projects/' + encodeURIComponent(projectId) + '/layers', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, color }),
  });
}

export function patchLayer(projectId: string, layerId: string, updates: Partial<{
  name: string; color: string; visible: boolean; locked: boolean; z_index: number;
}>): Promise<GeoLayer> {
  return request('/projects/' + encodeURIComponent(projectId) + '/layers/' + encodeURIComponent(layerId), {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
}

export function updateProjectFeature(
  projectId: string, featureId: string,
  updates: { geometry?: GeoJSON.Geometry; name?: string; layer_id?: string;
             properties?: Record<string, unknown>; expected_revision?: number },
): Promise<WorkspaceFeature> {
  return request('/projects/' + encodeURIComponent(projectId) + '/features/' + encodeURIComponent(featureId), {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
}

export function getFeatureHistory(projectId: string, featureId: string): Promise<FeatureHistory> {
  return request('/projects/' + encodeURIComponent(projectId) + '/features/' + encodeURIComponent(featureId) + '/history');
}

export function restoreFeature(projectId: string, featureId: string, revision: number): Promise<WorkspaceFeature> {
  return request('/projects/' + encodeURIComponent(projectId) + '/features/' + encodeURIComponent(featureId) + '/restore/' + revision, {
    method: 'POST',
  });
}

export function copyProjectFeature(projectId: string, featureId: string): Promise<StoredFeature> {
  return request('/projects/' + encodeURIComponent(projectId) + '/features/' + encodeURIComponent(featureId) + '/copy', {
    method: 'POST',
  });
}


export function saveFeatureBatch(projectId: string, features: Array<{
  name: string; geometry: GeoJSON.Geometry; source: string;
  properties: Record<string,unknown>;
}>, layerId?: string): Promise<{results: WorkspaceFeature[];created: number}> {
  return request('/projects/' + encodeURIComponent(projectId) + '/features/batch', {
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({features,layer_id:layerId || null}),
  });
}


export interface AttributeQuery {
  field?: string | null;
  operator?: 'contains' | 'equals' | 'gte' | 'lte' | 'exists';
  value?: unknown;
  limit?: number;
  offset?: number;
}
export interface AttributeResult {
  results: Array<{ id:string; name:string; source:string; properties:Record<string,unknown> }>;
  total:number; fields:string[];
}
export function queryAttributes(projectId:string,filter:AttributeQuery):Promise<AttributeResult> {
  return request('/projects/'+encodeURIComponent(projectId)+'/attributes/query',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(filter),
  });
}
export function saveAttributes(projectId:string,updates:Array<{
  id:string;expected_revision:number;properties:Record<string,unknown>;
}>):Promise<{count:number;atomic:boolean}> {
  return request('/projects/'+encodeURIComponent(projectId)+'/attributes/batch',{
    method:'PATCH',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({updates}),
  });
}
export interface SharedTopologyPreview {
  affected:Array<{id:string;name:string;revision:number;locked:boolean;valid:boolean;warning:string|null;geometry:GeoJSON.Geometry}>;
  count:number;method:string;
}
export function previewTopology(projectId:string,oldPoint:[number,number],newPoint:[number,number]):Promise<SharedTopologyPreview> {
  return request('/projects/'+encodeURIComponent(projectId)+'/topology/preview',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({old:oldPoint,new:newPoint,tolerance_m:0.05}),
  });
}
export function applyTopology(projectId:string,oldPoint:[number,number],newPoint:[number,number],
  expected:Record<string,number>):Promise<{count:number;atomic:boolean}> {
  return request('/projects/'+encodeURIComponent(projectId)+'/topology/move',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({old:oldPoint,new:newPoint,expected_revisions:expected,tolerance_m:0.05}),
  });
}
export function traceExisting(start:[number,number],end:[number,number],paths:[number,number][][]):Promise<EditResponse> {
  return request('/edit/trace',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({start,end,paths,tolerance_m:30}),
  });
}
export type TerrainComputePolicy = {
  mode:'automatic'|'manual';backend?:'auto'|'cpu';gpu_memory_percent?:number;hard_memory?:boolean;memory_percent:number;concurrent_tasks:number;tile_size:128|256|512|1024;
  slope_cells:number;surface_cells:number;global_cells:number;visibility_cells:number;least_cost_cells:number;
  viewshed_distance_m:number;ray_samples:number;
};
export type TerrainComputeLimits = Omit<TerrainComputePolicy,'mode'|'memory_percent'|'backend'|'gpu_memory_percent'> & {memory_bytes:number;native_slope_cells:number;gpu_memory_bytes?:number};
export interface TerrainComputeStatus {
  policy:TerrainComputePolicy;hardware:{total_bytes:number;available_bytes:number;logical_cpus:number;scratch_free_bytes:number;gpu_free_bytes?:number;gpu_total_bytes?:number};
  effective:TerrainComputeLimits;active_tasks:number;queued_tasks:number;reserved_bytes?:number;scope:string;hard_memory_available?:boolean;terrain_gpu:string;memory_protection:string;
}
export function getTerrainComputeResources(signal?:AbortSignal):Promise<TerrainComputeStatus>{
  return request('/terrain/resources',{signal});
}
export function setTerrainComputeResources(policy:TerrainComputePolicy):Promise<TerrainComputeStatus>{
  return request('/terrain/resources',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(policy)});
}

export interface TerrainResult {
  compute_resources?:TerrainComputeLimits;
  elevation_min_m:number;elevation_max_m:number;elevation_mean_m:number;
  elevation_relief_m:number;mean_slope_deg:number;mean_aspect_deg:number|null;
  maximum_slope_deg:number;valid_pixels:number;engine:string;warning:string;
}
export function analyzeTerrain(imageId:string,geometry:GeoJSON.Geometry,signal?:AbortSignal,
 gradientMethod:'horn'|'zevenbergen_thorne'='horn'):Promise<TerrainResult> {
  return request('/terrain/analyze',{
    signal,method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({image_id:imageId,geometry,vertical_unit:'meter',gradient_method:gradientMethod}),
  });
}
export function terrainProfile(imageId:string,geometry:GeoJSON.Geometry,signal?:AbortSignal):Promise<{
  samples:Array<{distance_m:number;elevation_m:number|null;coordinate?:[number,number]}>;length_m:number;warning:string;
}> {
  return request('/terrain/profile',{
    signal,method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({image_id:imageId,geometry,samples:80}),
  });
}
export async function importVectorFile(projectId:string,file:File,layerId?:string):Promise<{created:number}> {
  const payload=new FormData();payload.append('file',file);
  const url='/projects/'+encodeURIComponent(projectId)+'/vector/import'+
    (layerId?'?layer_id='+encodeURIComponent(layerId):'');
  return request(url,{method:'POST',body:payload});
}
export async function exportVectorFile(
  projectId:string,format:'geojson'|'gpkg'|'kml'|'gpx'|'shapefile',
):Promise<void> {
  const response=await rawRequest('/projects/'+encodeURIComponent(projectId)+'/vector/export/'+format);
  if(!response.ok) throw await responseError(response, 'GIS export failed.');
  const blob=await response.blob();
  const filename=response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1]
    ?? 'geofathom-'+format;
  const url=URL.createObjectURL(blob);
  const link=document.createElement('a');
  link.href=url;link.download=filename;document.body.appendChild(link);
  link.click();link.remove();
  window.setTimeout(()=>URL.revokeObjectURL(url),1500);
}


export interface RefineResult extends RasterTrace {
  positive_count:number;negative_count:number;box_used:boolean;
}
export function refineRaster(body:{
  image_id:string;positive_points:[number,number][];
  negative_points:[number,number][];box:[number,number][]|null;
  window_size:number;
}):Promise<RefineResult> {
  return request('/vision/refine',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body),
  });
}


export interface LabelStyle {
  enabled:boolean;
  field:string;
  font_size:number;
  text_color:string;
  halo_color:string;
  halo_width:number;
  min_zoom:number;
  max_zoom:number;
  allow_overlap:boolean;
  priority:number;offset_x:number;offset_y:number;
  prefix:string;suffix:string;
  placement:'auto'|'point'|'line';callout:boolean;
  rule_field:string;
  rule_operator:'equals'|'contains'|'gte'|'lte'|'exists';
  rule_value:string;
}
export interface SymbolStyle {
  fill_opacity:number;
  line_width:number;
  point_radius:number;
  stroke_color:string;
  category_field:string;
  category_colors:Record<string,string>;
  graduated_field:string;
  graduated_method:'equal_interval'|'quantile'|'jenks';
  graduated_breaks:number[];
  graduated_colors:string[];
}
export interface LayerStyle {
  labels:LabelStyle;
  symbol:SymbolStyle;
}
export function patchLayerStyle(
  projectId:string,layerId:string,changes:{
    labels?:Partial<LabelStyle>;
    symbol?:Partial<SymbolStyle>;
    expected_revision?:number;
  },
):Promise<GeoLayer> {
  return request('/projects/'+encodeURIComponent(projectId)+
    '/layers/'+encodeURIComponent(layerId)+'/style',{
      method:'PATCH',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(changes),
    });
}
export function addMapAnnotation(
  projectId:string,text:string,position:[number,number],layerId?:string,
):Promise<WorkspaceFeature>{
  return request('/projects/'+encodeURIComponent(projectId)+'/annotations',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text,position,layer_id:layerId||null}),
  });
}


export async function deleteProjectFeature(projectId:string,featureId:string,expectedRevision?:number):Promise<void> {
  const response=await rawRequest('/projects/'+encodeURIComponent(projectId)+
    '/features/'+encodeURIComponent(featureId)+(expectedRevision===undefined?'':'?expected_revision='+expectedRevision),{method:'DELETE'});
  if(!response.ok) throw await responseError(response, 'Could not delete the selected map feature.');
}


// Professional map analysis and document layout workflows.
export type SpatialRelation='intersects'|'within'|'contains'|'touches'|'crosses';
export interface SpatialSelection {
  ids:string[];
  results:Array<{id:string;name:string;geometry:GeoJSON.Geometry;
    revision:number;layer_id:string;properties:Record<string,unknown>}>;
  total:number;limit:number;offset:number;method:string;
}
export interface QualityIssue {
  type:'overlap'|'gap'|'duplicate'|'invalid'|'dangle';
  feature_ids:string[];
  geometry:GeoJSON.Geometry;
  message:string;
  area_m2:number;
}
export interface QualityReport{
  issues:QualityIssue[];
  counts:Record<string,number>;
  issue_count:number;
  checked_features:number;
  truncated:boolean;
  warning:string;
  method:string;
}
export function selectSpatialFeatures(projectId:string,geometry:GeoJSON.Geometry,
  relation:SpatialRelation='intersects',
  layerIds:string[]|null=null,visibleOnly=true,limit=500,offset=0):Promise<SpatialSelection>{
  return request('/projects/'+encodeURIComponent(projectId)+'/spatial/select',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({geometry,relation,layer_ids:layerIds,visible_only:visibleOnly,limit,offset}),
  });
}
export function reviewTopology(projectId:string,body:{
  layer_ids?:string[]|null;study_area?:GeoJSON.Geometry|null;
  minimum_area_m2?:number;check_dangles?:boolean;max_issues?:number;
}):Promise<QualityReport>{
  return request('/projects/'+encodeURIComponent(projectId)+'/quality/topology',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),
  });
}
export async function downloadMapPDF(projectId:string,settings:{
  title:string;paper:'a4'|'a3'|'letter';
  orientation:'landscape'|'portrait';
  extent:[number,number,number,number]|null;
  show_grid:boolean;show_legend:boolean;
  layer_ids:string[]|null;
}):Promise<void>{
  const response=await rawRequest('/projects/'+encodeURIComponent(projectId)+'/print/pdf',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings),
  });
  if(!response.ok) throw await responseError(response, 'Map layout could not be rendered');
  const blob=await response.blob();
  const url=URL.createObjectURL(blob);
  try{
    const link=document.createElement('a');
    link.href=url;
    link.download='geofathom-map.pdf';
    document.body.appendChild(link);link.click();link.remove();
  }finally{window.setTimeout(()=>URL.revokeObjectURL(url),1500);}
}
export interface SpatialPage {
  results:WorkspaceFeature[];
  total:number;limit:number;offset:number;indexed:boolean;
}
export function viewportFeatures(projectId:string,
  bbox:[number,number,number,number],limit=250,offset=0):Promise<SpatialPage>{
  const params=new URLSearchParams({
    west:String(bbox[0]),south:String(bbox[1]),east:String(bbox[2]),
    north:String(bbox[3]),limit:String(limit),offset:String(offset),
  });
  return request('/projects/'+encodeURIComponent(projectId)+'/features/viewport?'+params);
}


// P1 project coordinate-system metadata and graduated cartography.
export interface ProjectCRS {
  project_id:string;
  epsg:string;grid_visible:number;revision:number;
}
export function getProjectCRS(projectId:string):Promise<ProjectCRS>{
  return request('/projects/'+encodeURIComponent(projectId)+'/crs');
}
export function saveProjectCRS(projectId:string,epsg:string,gridVisible:boolean,
  revision:number):Promise<ProjectCRS>{
  return request('/projects/'+encodeURIComponent(projectId)+'/crs',{
    method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({epsg,grid_visible:gridVisible,expected_revision:revision}),
  });
}
export interface CoordinatesProjection {
  source:string;target:string;coordinates:[number,number][];units:string;
}
export function transformProjectCoordinates(projectId:string,
  positions:[number,number][],target:string,
  source='EPSG:4326'):Promise<CoordinatesProjection>{
  return request('/projects/'+encodeURIComponent(projectId)+'/crs/transform',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({points:positions,target,source}),
  });
}
export function getProjectGrid(projectId:string,
  bbox:[number,number,number,number]):Promise<GeoJSON.FeatureCollection>{
  const query=new URLSearchParams({
    west:String(bbox[0]),south:String(bbox[1]),
    east:String(bbox[2]),north:String(bbox[3]),divisions:'5',
  });
  return request('/projects/'+encodeURIComponent(projectId)+'/crs/grid?'+query);
}
export interface Classification {
  method:'quantile'|'jenks'|'equal_interval';
  classes:number;min:number;max:number;breaks:number[];
  ranges:Array<{min:number;max:number;inclusive_upper:boolean}>;
  samples:number;
}
export function classifyValues(values:number[],method:Classification['method'],
  classes:number):Promise<Classification>{
  return request('/analysis/classify',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({values,method,classes}),
  });
}


export function saveGraduatedStyle(projectId:string,body:{
  layer_id:string;field:string;classes:number;
  method:'equal_interval'|'quantile'|'jenks';
  colors?:string[]|null;expected_revision:number;
}):Promise<{classification:Classification;layer:GeoLayer}>{
  return request('/projects/'+encodeURIComponent(projectId)+'/symbology/graduated',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body),
  });
}


// P2 trusted OGC services, PostGIS indexed mirror and persisted GIS jobs.
export interface OGCSource {
  id:string;project_id:string;
  service:'wms'|'wmts'|'wfs'|'ogc_features';
  title:string;base_url:string;layer_name:string;
  attribution:string;tile_matrix_set:string;created_at:string;
}
export type NewOGCSource=Omit<OGCSource,'id'|'project_id'|'created_at'>;
export function getOGCSources(projectId:string):Promise<{sources:OGCSource[]}>{
  return request('/projects/'+encodeURIComponent(projectId)+'/ogc');
}
export function registerOGCSource(projectId:string,source:NewOGCSource,
  adminToken:string):Promise<OGCSource>{
  return request('/projects/'+encodeURIComponent(projectId)+'/ogc',{
    method:'POST',headers:{'Content-Type':'application/json',
      'X-GeoFathom-Admin-Token':adminToken},body:JSON.stringify(source),
  });
}
export async function removeOGCSource(projectId:string,sourceId:string,token:string):Promise<void>{
  const response=await rawRequest('/projects/'+encodeURIComponent(projectId)+
    '/ogc/'+encodeURIComponent(sourceId),{
    method:'DELETE',headers:{'X-GeoFathom-Admin-Token':token},
  });
  if(!response.ok)throw new Error('Could not remove OGC service.');
}
export function inspectOGCSource(projectId:string,id:string):Promise<{
  service:string;layers?:string[];collections?:Array<{id:string;title:string}>;
}>{
  return request('/projects/'+encodeURIComponent(projectId)+'/ogc/'+
    encodeURIComponent(id)+'/capabilities');
}
export function remoteOGCFeatures(projectId:string,id:string,
  bbox:[number,number,number,number],limit=100):Promise<GeoJSON.FeatureCollection>{
  const params=new URLSearchParams({
    west:String(bbox[0]),south:String(bbox[1]),east:String(bbox[2]),
    north:String(bbox[3]),limit:String(limit),
  });
  return request('/projects/'+encodeURIComponent(projectId)+'/ogc/'+
    encodeURIComponent(id)+'/features?'+params);
}
export function ogcTileTemplate(projectId:string,id:string):string{
  return API_URL+'/projects/'+encodeURIComponent(projectId)+
    '/ogc/'+encodeURIComponent(id)+'/tiles/{z}/{x}/{y}';
}
export interface PostGISStatus {
  configured:boolean;connected:boolean;engine:string;
  postgis_version?:string;spatial_index?:string;note:string;
}
export function getPostGISStatus():Promise<PostGISStatus>{
  return request('/postgis/status');
}
export function syncPostGIS(projectId:string,adminToken:string):Promise<{
  synchronized:number;atomic:boolean;target:string;
}>{
  return request('/projects/'+encodeURIComponent(projectId)+'/postgis/sync',{
    method:'POST',headers:{'Content-Type':'application/json',
      'X-GeoFathom-Admin-Token':adminToken},
    body:JSON.stringify({max_features:100000}),
  });
}
export function queryPostGIS(projectId:string,bbox:[number,number,number,number],
  limit=250,offset=0):Promise<{
    results:WorkspaceFeature[];total:number;indexed:boolean;source:string;
  }>{
  const params=new URLSearchParams({
    west:String(bbox[0]),south:String(bbox[1]),
    east:String(bbox[2]),north:String(bbox[3]),
    limit:String(limit),offset:String(offset),
  });
  return request('/projects/'+encodeURIComponent(projectId)+
    '/postgis/features?'+params);
}
export interface VisionModel {
  id:string; classes:string[]; bands:number[]; tile_size:number;
  input_scale:number; mean:number[]; std:number[]; description:string;
  runtime:string;
  task?:'semantic_segmentation'|'building_extraction';
}
export interface VisionModels {
  models:VisionModel[]; runtime_available:boolean;device:string;note:string;
}
export interface GeoAIResult extends GeoJSON.FeatureCollection {
  analysis:string;engine:string;provider:string;model_id:string|null;
  source_images:string[];source_crs:string;geometry_crs:string;
  valid_pixels:number;classified_pixels?:number;gain_pixels?:number;
  loss_pixels?:number;truncated:boolean;warning:string;
  provenance?:{source_sha256:Record<string,string>;
                model_sha256?:string;model_id?:string;task_kind?:string};
  summary?:{candidate_count:number;total_area_m2:number;foreground_fraction:number};
  artifacts?:Record<string,{sha256:string;size_bytes:number}>;
}
export function getVisionModels():Promise<VisionModels>{
  return request('/vision/models/segmentation');
}

export type GISJobKind='topology_qa'|'spatial_select'|'export_geojson'|
  'postgis_sync'|'rebuild_index'|'spectral_index'|'spectral_change'|
  'semantic_segmentation'|'building_extraction'|'stac_ndvi'|'vector_import'|'vector_export'|'remote_windowed'|'remote_cube'|'remote_model_train'|'remote_model_predict'|'remote_model_evaluate'|'remote_experiment';
export interface GISJob {
  id:string;project_id:string;kind:GISJobKind;
  status:'queued'|'running'|'completed'|'failed'|'cancelled'|'interrupted';
  progress:number;error:string|null;
  payload:Record<string,unknown>;result:unknown;
  cancel_requested:boolean;created_at:string;updated_at:string;
  has_result?:boolean;
}
export function getGISJob(projectId:string,id:string,
  includeResult=true):Promise<GISJob>{
  return request('/projects/'+encodeURIComponent(projectId)+'/jobs/'+
    encodeURIComponent(id)+'?include_result='+String(includeResult));
}
export function getGISJobs(projectId:string):Promise<{jobs:GISJob[]}>{
  return request('/projects/'+encodeURIComponent(projectId)+'/jobs');
}
export function queueGISJob(projectId:string,kind:GISJobKind,
  payload:Record<string,unknown>,token=''):Promise<GISJob>{
  return request('/projects/'+encodeURIComponent(projectId)+'/jobs',{
    method:'POST',headers:{'Content-Type':'application/json',
      'X-GeoFathom-Admin-Token':token},
    body:JSON.stringify({kind,payload}),
  });
}
export function cancelGISJob(projectId:string,id:string):Promise<GISJob>{
  return request('/projects/'+encodeURIComponent(projectId)+'/jobs/'+
    encodeURIComponent(id)+'/cancel',{method:'POST'});
}
export async function downloadBuildingArtifact(projectId:string,id:string,asset:string):Promise<void>{
  const response=await rawRequest('/projects/'+encodeURIComponent(projectId)+
    '/jobs/'+encodeURIComponent(id)+'/download?asset='+encodeURIComponent(asset));
  if(!response.ok)throw new Error('Building output is unavailable or has changed.');
  const url=URL.createObjectURL(await response.blob());
  try{
    const link=document.createElement('a');link.href=url;link.download=asset;
    document.body.appendChild(link);link.click();link.remove();
  }finally{window.setTimeout(()=>URL.revokeObjectURL(url),1000);}
}
export async function downloadGISJob(projectId:string,id:string):Promise<void>{
  const response=await rawRequest('/projects/'+encodeURIComponent(projectId)+
    '/jobs/'+encodeURIComponent(id)+'/download');
  if(!response.ok)throw new Error('Completed GeoJSON export job required.');
  const url=URL.createObjectURL(await response.blob());
  try{
    const element=document.createElement('a');
    element.href=url;element.download='geofathom-export.geojson';
    document.body.appendChild(element);element.click();element.remove();
  }finally{window.setTimeout(()=>URL.revokeObjectURL(url),1000);}
}


export type TerrainOperation='dem_difference'|'contours'|'volume'|'visibility'|'viewshed_multi'|'watershed'|'mesh'|'distribution'|'elevation'|'slope_map'|'aspect_map'|'hillshade'|'tri'|'tpi'|'curvature'|'plan_curvature'|'profile_curvature'|'flow_direction'|'flow_accumulation'|'flow_accumulation_mfd'|'streams'|'stream_order'|'suitability'|'cutfill_map'|'least_cost'|'cross_sections';
export interface TerrainRaster {png:string;geotiff:string;product_id?:string;corners:[[number,number],[number,number],[number,number],[number,number]];legend:{label:string;color:string;cells:number}[];width:number;height:number;valid_cells:number;unit?:string}
export interface TerrainRasterLayer {id:string;title:string;raster:TerrainRaster;opacity:number;resampling:'nearest'|'linear'}
export interface TerrainDistributionBin {lower_m:number;upper_m:number;cells:number;area_m2:number;cumulative_pct:number}
export interface TerrainLOD {tile_cells:number;levels:number[];transport:string;tiles:Array<{lod_step:number;row_start:number;col_start:number;rows:number;cols:number;bounds_cell:number[];row_indices:number[];col_indices:number[];heights:Array<number|null>}>}
export interface TerrainMesh {rows:number;cols:number;dx_m:number;dy_m:number;heights:Array<number|null>;origin_xy?:[number,number];source_crs?:string;texture?:{png:string;coverage_pct:number};lod?:TerrainLOD;source_grid_rows?:number;source_grid_cols?:number;source_sampling_step?:number}
export interface StreamedTerrainTile {
  source_crs:string;grid_rows:number;grid_cols:number;grid_cell_width_m:number;grid_cell_height_m:number;
  grid_origin_xy:[number,number];level:number;tile_row:number;tile_col:number;
  row_indices:number[];col_indices:number[];rows:number;cols:number;
  heights:Array<number|null>;valid_quads:boolean[];nodata_policy:string;source_elevation_unit:string;
  geometric_error_max_m?:number|null;geometric_error_rmse_m?:number|null;
  geometric_error_samples?:number;valid_quad_count?:number;
}
export function fetchTerrainMeshTile(body:{
  image_id:string;geometry:GeoJSON.Geometry;level:1|2|4|8|16|32|64;
  tile_row:number;tile_col:number;tile_cells?:32;
},signal?:AbortSignal):Promise<StreamedTerrainTile>{
  return request('/terrain/mesh/tile',{method:'POST',signal,
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}
export interface AdvancedTerrainResult {
  plot_data?:PlotData;
  compute_resources?:TerrainComputeLimits;
  operation:TerrainOperation;source_crs:string;source_vertical_datum?:string|null;valid_cells:number;missing_cells:number;
  cell_area_m2:number;metrics:Record<string,number>;warning:string;
  algorithm_options?:{gradient_method:string;slope_classes:string;
    neighborhood_radius_cells?:number|null;route_model?:string|null;
    mesh_samples?:number|null;stream_order_scheme?:string|null;hillshade_mode?:string|null;maximum_distance_m?:number|null;
    view_azimuth_deg?:number|null;view_width_deg?:number|null;
    flow_routing_method?:string|null;depression_method?:string|null;external_inflow_supplied?:boolean|null;
    curvature_method?:string|null;curvature_radius_cells?:number|null;
    design_east_grade?:number|null;design_north_grade?:number|null;
    design_curvature_east_per_m?:number|null;design_curvature_cross_per_m?:number|null;design_curvature_north_per_m?:number|null;
    design_max_grade?:number|null;elevation_sigma_m?:number|null;
    optimize_observers?:number|null;dsm_source?:boolean|null;mesh_lod?:boolean|null;
    suitability_model?:string|null;suitability_weights?:number[]|null};
  selection?:{selected_candidate_indices:number[];marginal_visible_cells:number[];total_candidate_sites:number;
    optimizer?:{candidate_count:number;selected_site_count:number;combinations_checked:number;
      combinations_possible:number;positively_visible_cells:number;
      global_optimum_within_supplied_candidates:boolean;objective:string;tie_break:string}};
  quality?:{status:string;reference_validation:string;uncertainty:string;
    source_overlap_pct:number;valid_study_cell_pct:number;
    derivative_coverage_pct:number|null;flags:string[];area_basis:string;
    projection_max_scale_error_pct?:number};
  features:Array<GeoJSON.Feature<GeoJSON.Geometry,Record<string,unknown>>>;mesh?:TerrainMesh;distribution?:TerrainDistributionBin[];raster?:TerrainRaster;sections?:{station_m:number;length_m:number;samples:{distance_m:number;offset_m:number;elevation_m:number|null;coordinate:[number,number]}[]}[];
}
export function advancedTerrain(body:{image_id:string;geometry:GeoJSON.Geometry;operation:TerrainOperation;
  interval:number;reference:number;point:[number,number]|null;observer_height:number;target_height:number;end_point?:[number,number]|null;max_slope?:number;min_elevation?:number;max_elevation?:number;max_tri?:number;stream_cells?:number;azimuth?:number;altitude?:number;section_spacing?:number;section_width?:number;texture_image_id?:string|null;fill_sinks?:boolean;consider_curvature?:boolean;refraction_coeff?:number;comparison_image_id?:string|null;observer_points?:[number,number][]|null;gradient_method?:'horn'|'zevenbergen_thorne';slope_classes?:'standard'|'detailed'|'broad';mfd_exponent?:number;neighborhood_radius?:number;max_distance_m?:number;
  view_azimuth?:number;view_width?:number;route_model?:'surface'|'distance'|'gentle';
  mesh_samples?:number;stream_order_scheme?:'strahler'|'shreve';hillshade_mode?:'single'|'four_direction';
  flow_routing_method?:'d8'|'dinf';depression_method?:'fill'|'breach';
  curvature_method?:'finite_difference'|'quadratic';curvature_radius?:number;
  design_east_grade?:number;design_north_grade?:number;design_max_grade?:number;elevation_sigma_m?:number;
  optimize_observers?:number;dsm_image_id?:string|null;mesh_lod?:boolean;
  suitability_model?:'binary'|'weighted';suitability_weights?:[number,number,number];
  external_inflow_image_id?:string|null;
  design_curvature_east?:number;design_curvature_cross?:number;design_curvature_north?:number},signal?:AbortSignal):Promise<AdvancedTerrainResult>{
  return request('/terrain/advanced',{signal,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}

export type DEMProcessMode='clip'|'mosaic'|'resample';
export async function prepareDEM(body:{
  image_ids:string[];mode:DEMProcessMode;resolution_m:number;
  sampling:'nearest'|'bilinear'|'average';geometry?:GeoJSON.Geometry|null
},token:string,signal?:AbortSignal):Promise<{
  asset:RasterAsset;operation:DEMProcessMode;valid_cells:number;total_cells:number;
  resolution_m:number;warning:string
}>{
  const headers:Record<string,string>={'Content-Type':'application/json'};
  if(token)headers['X-GeoFathom-Admin-Token']=token;
  else headers['X-GeoFathom-Local-Import']='1';
  return request('/terrain/dem/prepare',{method:'POST',headers,signal,body:JSON.stringify(body)});
}

export function bufferGeometry(geometry:GeoJSON.Geometry,distance_m:number):Promise<EditResponse&{warning:string}>{
  return request('/analysis/buffer',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({geometry,distance_m,resolution:16})});
}
export function compareAreas(left:GeoJSON.Geometry,right:GeoJSON.Geometry):Promise<{
  left_area_m2:number;right_area_m2:number;difference_m2:number;ratio:number|null;method:string
}>{
  return request('/analysis/compare',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({left,right})});
}

export function fetchPublicDEM(bbox:[number,number,number,number],resolution_m:1|3|10|30|90,token:string,signal?:AbortSignal):Promise<{
 asset:RasterAsset;resolution_m:number;valid_cells:number;total_cells:number;missing_tiles:string[];warning:string;requested_bbox:[number,number,number,number];valid_coverage_pct:number
}>{
 const headers:Record<string,string>={'Content-Type':'application/json'};
 if(token)headers['X-GeoFathom-Admin-Token']=token;else headers['X-GeoFathom-Local-Import']='1';
 return request('/imagery/dem/fetch',{signal,method:'POST',headers,body:JSON.stringify({bbox,resolution_m})});
}

export interface TrashedFeature{feature_id:string;layer_id:string;name:string;deleted_at:string}
export function getProjectTrash(id:string):Promise<{items:TrashedFeature[];total:number}>{
 return request('/projects/'+encodeURIComponent(id)+'/trash');
}
export function restoreDeletedFeature(projectId:string,featureId:string):Promise<WorkspaceFeature>{
 return request('/projects/'+encodeURIComponent(projectId)+'/trash/'+encodeURIComponent(featureId)+'/restore',{method:'POST'});
}


/** Each detected face is a genuinely closed and independently measured polygon. */
export interface NetworkFace{
 id:string;name:string;geometry:GeoJSON.Polygon;measurement:Measurement;
 label_anchor:[number,number];
 properties:{source_type:'polygonized_network';area_m2:number;perimeter_m:number;snap_tolerance_m:number};
}
export interface NetworkPolygonization{
 faces:NetworkFace[];count:number;area_m2:number;
 dangles:number;cuts:number;invalid_rings:number;source_segments:number;
 tolerance_m:number;method:string;warning:string;
}
export function polygonizeNetwork(
 geometries:GeoJSON.Geometry[],tolerance_m=1,minimum_area_m2=.01,
 signal?:AbortSignal,
):Promise<NetworkPolygonization>{
 return request('/edit/polygonize',{method:'POST',signal,
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({geometries,tolerance_m,minimum_area_m2,max_faces:300}),
 });
}

export interface ExchangeField {name:string;type?:string;types?:string[];nullable?:boolean}
export interface ExchangeLayer {name:string;source_crs:string|null;feature_count:number;geometry_type:string;fields:ExchangeField[]}
export interface ExchangeFile {id:string;name:string;bytes:number;layers:ExchangeLayer[];error?:string;errors?:Array<{row:number;message:string}>}
export interface ExchangeUpload {upload_id:string;files:ExchangeFile[]}
export interface ImportDatasetOptions {
 layers?:string[];source_crs?:string;encoding?:string;error_policy?:'strict'|'skip';
 field_map?:Record<string,string>;field_types?:Record<string,string>;
 longitude_field?:string;latitude_field?:string;geometry_field?:string;delimiter?:string;
}
export interface DatasetExportOptions {
 format:'geojson'|'gpkg'|'shapefile'|'kml'|'gpx'|'csv'|'report';include_measurements?:boolean;target_crs?:string;
 layer_ids?:string[];feature_ids?:string[];viewport?:[number,number,number,number];
 fields?:string[];precision?:number;collection?:GeoJSON.FeatureCollection;
}
export interface ExportPreflight {count:number;schema:ExchangeField[];geometry_types:string[];warnings:string[];target_crs:string}
const exchangePath=(project:string)=>'/projects/'+encodeURIComponent(project);
const jsonPost=(value:unknown,signal?:AbortSignal):RequestInit=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value),signal});
export function inspectDatasetFiles(project:string,files:File[],signal?:AbortSignal):Promise<ExchangeUpload>{
 const body=new FormData();files.forEach(file=>body.append('files',file));
 return request(exchangePath(project)+'/vector/uploads',{method:'POST',body,signal});
}
export function inspectDatasetOptions(project:string,upload:string,file:string,options:ImportDatasetOptions,signal?:AbortSignal):Promise<{layers:ExchangeLayer[];errors?:ExchangeFile['errors']}>{
 return request(exchangePath(project)+'/vector/uploads/'+encodeURIComponent(upload)+'/inspect',jsonPost({file_id:file,options},signal));
}
export async function discardDatasetUpload(project:string,id:string):Promise<void>{
 const response=await rawRequest(exchangePath(project)+'/vector/uploads/'+encodeURIComponent(id),{method:'DELETE'});
 if(!response.ok)throw await responseError(response);
}
export function startDatasetImport(project:string,upload:string,files:Array<{id:string;options:ImportDatasetOptions}>,layer?:string):Promise<GISJob>{
 return request(exchangePath(project)+'/vector/import/jobs',jsonPost({upload_id:upload,files,layer_id:layer||null,separate_layers:!layer}));
}
export function preflightDatasetExport(project:string,options:DatasetExportOptions,signal?:AbortSignal):Promise<ExportPreflight>{
 return request(exchangePath(project)+'/vector/export/preflight',jsonPost(options,signal));
}
export function startDatasetExport(project:string,options:DatasetExportOptions):Promise<GISJob>{
 return request(exchangePath(project)+'/vector/export/jobs',jsonPost(options));
}
async function exchangeDownload(path:string,init?:RequestInit):Promise<void>{
 const response=await rawRequest(path,init);
 if(!response.ok)throw await responseError(response,'Dataset download failed.');
 const blob=await response.blob();if(init?.signal?.aborted)return;
 const filename=response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1]??'geofathom-download';
 const url=URL.createObjectURL(blob);const link=document.createElement('a');
 link.href=url;link.download=filename;document.body.appendChild(link);link.click();link.remove();
 window.setTimeout(()=>URL.revokeObjectURL(url),1500);
}
export function downloadDatasetExport(project:string,options:DatasetExportOptions,signal?:AbortSignal):Promise<void>{
 return exchangeDownload(exchangePath(project)+'/vector/export',jsonPost(options,signal));
}
export function downloadExchangeJob(project:string,id:string):Promise<void>{
 return exchangeDownload(exchangePath(project)+'/vector/jobs/'+encodeURIComponent(id)+'/download');
}
export function downloadProjectPackage(project:string,rasters:Array<{id:string;kind:'image'|'dem'}>,signal?:AbortSignal):Promise<void>{
 return exchangeDownload(exchangePath(project)+'/package/export',jsonPost({rasters},signal));
}
export function restoreProjectPackage(project:string,file:File,token:string,signal?:AbortSignal):Promise<{created:number;layers:number;rasters:Array<{asset:RasterAsset;kind:'image'|'dem'}>}>{
 const body=new FormData();body.append('file',file);
 return request(exchangePath(project)+'/package/import',{method:'POST',body,signal,headers:{'X-GeoFathom-Local-Import':'1','X-GeoFathom-Admin-Token':token}});
}

/** Authenticated binary transfer without embedding large rasters in JSON. */
export async function downloadTerrainRaster(raster:TerrainRaster,filename:string):Promise<void>{
 let blob:Blob;
 if(raster.product_id){
  const response=await rawRequest('/terrain/products/'+encodeURIComponent(raster.product_id));
  if(!response.ok)throw await responseError(response);
  blob=await response.blob();
 }else{
  const data=Uint8Array.from(atob(raster.geotiff),c=>c.charCodeAt(0));
  blob=new Blob([data],{type:'image/tiff'});
 }
 const url=URL.createObjectURL(blob);
 const link=document.createElement('a');link.href=url;link.download=filename;link.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
}

export interface TerrainProductList {products:{id:string;bytes:number;modified:number}[];total_bytes:number;limit_bytes:number;limit_files:number}
export function listTerrainProducts():Promise<TerrainProductList>{return request('/terrain/products');}
export function deleteTerrainProduct(id:string):Promise<{deleted:boolean}>{return request('/terrain/products/'+encodeURIComponent(id),{method:'DELETE'});}

export interface ResearchExperiment {
 title:string;baseline_name:string;mode:'comparison'|'sensitivity'|'uncertainty';
 base:Record<string,unknown> & {image_id:string;geometry:GeoJSON.Geometry;operation:string};
 scenarios:Array<{name:string;parameters:Record<string,unknown>}>;
 parameter?:string;values?:number[];secondary_parameter?:string;secondary_values?:number[];sigma_m?:number;samples?:number;seed?:number;
 error_model?:'independent'|'common_offset'|'gaussian_spatial';correlation_length_m?:number;coverage?:number;expected_source_sha256?:string;
}
export interface ResearchProduct {name:string;role?:string;kind?:string;raster:TerrainRaster;
 statistics?:Record<string,unknown>;plot_data?:PlotData|null}
export interface ResearchResult {
 title:string;mode:ResearchExperiment['mode'];comparison_warning?:string;
 runs:Array<{label:string;input:Record<string,unknown>;metrics:Record<string,number>;warning:string;quality?:unknown}>;
 products:ResearchProduct[];differences:ResearchProduct[];
 metric_table:Array<{metric:string;values:number[];deltas:Array<number|null>;relative_pct:Array<number|null>}>;
 factorial?:null|{x_parameter:string;y_parameter:string;x_values:number[];y_values:number[];cells:Array<{x:number;y:number;metrics:Record<string,number>;matched_population:boolean}>};
 sensitivity:Array<{parameter:string;value:number;baseline_value:number;metrics:Record<string,number>;derivatives:Record<string,number>}>;
 uncertainty:null|{model:string;sigma_m:number;seed:number;generator:string;samples:number;coverage:number;
  warning:string;interval_type:string;common_cells?:number;realizations?:Record<string,number[]>;
  metrics:Record<string,{baseline:number;mean:number;std:number;low:number;high:number;mean_standard_error:number;split_half_endpoint_difference:number}>};
 manifest:Record<string,unknown>;archive_base64:string;
}
export interface ResearchCatalog {sweep_parameters:Record<string,string[]>;uncertainty_operations:string[];
 scenario_parameters:Record<string,string[]>;parameter_specs:Record<string,{choices:Array<string|number|boolean>;default:unknown}>}
export function getResearchCatalog():Promise<ResearchCatalog>{return request('/terrain/research/catalog');}
export function analyzeResearch(body:ResearchExperiment,signal?:AbortSignal):Promise<ResearchResult>{
 return request('/terrain/research/analyze',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}


export interface PlotBin {lower:number;upper:number;midpoint:number;cells:number;area_m2:number;percent:number;density:number|null;cumulative_pct:number}
export interface PlotData {
 schema:string;operation?:string;kind:'continuous'|'categorical'|'directional'|'binned'|'summary'|'profile';
 quantity:string;unit:string;valid_cells:number;cell_area_m2:number;population?:string;source_crs?:string;source_sha256?:string;
 metrics?:Record<string,number>;notes:string[];warning?:string;quality?:unknown;flat_cells?:number;directional_cells?:number;
 classes:Array<{label:string;color:string;cells:number;area_m2:number;percent:number}>;
 histograms?:Record<string,PlotBin[]>;
 cdf?:Array<{value:number;cells_le:number;percent_le:number}>;
 quantiles?:Array<{probability:number;value:number}>;
 normal_qq?:Array<{probability:number;normal_quantile:number;observed_quantile:number}>;
 summary?:{minimum:number;maximum:number;mean:number;population_std:number;q1:number;median:number;q3:number;iqr:number};
 box?:{q1:number;median:number;q3:number;whisker_low:number;whisker_high:number;lower_outliers:number;upper_outliers:number;fliers?:number[];displayed_outliers?:number};
 thresholds?:Array<{threshold_deg:number;cells_le:number;percent_le:number}>;
 roses?:Record<string,Array<{bearing_deg:number;cells:number;area_m2:number;percent:number}>>;
 profiles?:Array<{name:string;points:Array<{x:number;y:number|null}>}>;
 parameter_grid?:{x_label:string;y_label:string;x_values:number[];y_values:number[];cells:Array<{x:number;y:number;value:number|null}>};
 distribution_comparison?:{series:Array<{label:string;valid_cells:number;box:NonNullable<PlotData['box']>;cdf:NonNullable<PlotData['cdf']>}>};
 experiment_series?:{x_label:string;numeric:boolean;interval_label?:string;points:Array<{label:string;x:number;value:number|null;low?:number;high?:number;baseline?:number|null}>};
 joint?:{x_quantity:string;x_unit:string;y_quantity:string;y_unit:string;population_cells:number;sample_cells:number;sampling:string;pearson_r:number|null;identity_line?:boolean;regression?:{slope:number;intercept:number;r_squared:number|null}|null;agreement?:{bias:number;sample_std:number;lower:number;upper:number};samples:Array<{x:number;y:number}>;density_cells:Array<{x_lower:number;x_upper:number;y_lower:number;y_upper:number;cells:number;area_m2:number}>;notes:string[]}|null;
}
export function getTerrainPlotData(base:ResearchExperiment['base'],expectedSourceSha256?:string,signal?:AbortSignal):Promise<PlotData>{
 return request('/terrain/figures/data',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({base,expected_source_sha256:expectedSourceSha256})});
}
export async function exportFigurePDF(scene:unknown):Promise<Blob>{
 const response=await rawRequest('/terrain/figures/pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(scene)});
 if(!response.ok)throw await responseError(response);return response.blob();
}

export interface StudioRecipe {id:string;title:string;family:string;source:'table'|'raster'|'vector';fields:string[];note:string;option:[string,number,number,number]|null;minimum_rasters:number;tier?:'basic'|'professional'}
export interface StudioRaster {name:string;data:string;unit:string;band?:number}
export interface StudioInput {vector_geojson?:GeoJSON.FeatureCollection|null;vector_attribute?:string;vector_epsg?:number;recipe:string;csv:string;rasters:StudioRaster[];x:string;y:string;z:string;group:string;low:string;high:string;columns:string[];
 title:string;x_label:string;y_label:string;parameter:number|null;maximize_x:boolean;maximize_y:boolean;palette:'mono'|'color'|'earth';font:'sans'|'serif';font_size:number;grid:boolean;width_mm:number;height_mm:number;dpi:120|300|600;format:'png'|'pdf'|'svg'|'tiff';
 variogram_model?:'none'|'exponential'|'gaussian'|'spherical';variogram_view?:'fit'|'kriging_validation'|'kriging_prediction'|'kriging_sd';kriging_max_distance_m?:number;kriging_neighbors?:number;spectral_mode?:'angle'|'abundance'|'reconstruction_error';endmember_csv?:string;endmember_index?:number;hydrology_mode?:'observed'|'calibrated_reservoir';training_fraction?:number;model_validation?:'recorded'|'spatial_blocks';block_size_m?:number;validation_buffer_m?:number;validation_folds?:number;ridge_penalty?:number;point_mode?:'planar'|'voxel';voxel_size?:number;export_grid?:boolean;spatial_inference?:'statistic'|'p'|'q'|'cluster';permutations?:number;random_seed?:number;alpha?:number;response_style?:'heatmap'|'filled'|'contour'|'surface';contour_levels?:number;show_values?:boolean;show_points?:boolean;optimum?:'none'|'min'|'max';profile_style?:'series'|'overlay'|'delta'|'bands';map_style?:'continuous'|'diverging'|'categorical';map_columns?:number|null;map_common_mask?:boolean;map_min?:number|null;map_max?:number|null;class_breaks?:number[];sequential_cmap?:'default'|'viridis'|'cividis'|'magma'|'plasma'|'Greys'|'terrain';map_decoration?:'grid'|'minimal';line_width?:number;legend_position?:'best'|'upper left'|'upper right'|'lower left'|'lower right'|'center left'|'center right'}
export interface StudioOutput {figure:string;media_type:string;metadata:Record<string,unknown>;table:Array<Array<string|number|null>>;derived_rasters?:Array<StudioRaster&{sha256:string}>}
export function getStudioCatalog(signal?:AbortSignal):Promise<{legacy_recipe_count:number;additional_recipe_count:number;basic_recipe_count?:number;professional_recipe_count?:number;recipes:StudioRecipe[]}>{return request('/terrain/studio/catalog',{signal});}
export function renderStudio(body:StudioInput,signal?:AbortSignal):Promise<StudioOutput>{return request('/terrain/studio/render',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}

export function getStudioRasterTable(rasters:StudioRaster[],signal?:AbortSignal):Promise<{csv:string;metadata:Record<string,unknown>}>{return request('/terrain/studio/raster-table',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({rasters})});}

export interface StudioLegacyPanel {scene:Omit<import('./figureLibrary').FigureScene,'note'|'error'>;table:Array<Array<string|number|null>>;provenance:Record<string,unknown>}
export interface StudioPanelSlot {row:number;column:number;row_span:number;column_span:number}
export interface StudioComposition {slots?:StudioPanelSlot[];row_weights?:number[];column_weights?:number[];panels:Array<StudioInput|StudioLegacyPanel>;title:string;caption:string;columns:number;width_mm:number;height_mm:number;dpi:120|300|600;format:StudioInput['format'];spacing:number}
export function composeStudio(body:StudioComposition,signal?:AbortSignal):Promise<StudioOutput>{return request('/terrain/studio/compose',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}

export interface GlobalSensitivityInput {base:ResearchExperiment['base'];method:'sobol'|'morris'|'pareto';factors:Array<{name:string;minimum:number;maximum:number}>;metric:string;second_metric?:string;samples:number;seed:number;expected_source_sha256?:string}
export interface GlobalSensitivityOutput {method:'sobol'|'morris'|'pareto';metric:string;evaluations:number;indices:Array<{factor:string;[key:string]:string|number|null}>;plot_csv:string;design_csv:string;bindings:{x:string;y:string;columns:string[]};method_note:string;manifest:Record<string,unknown>}
export function analyzeGlobalSensitivity(body:GlobalSensitivityInput,signal?:AbortSignal):Promise<GlobalSensitivityOutput>{return request('/terrain/research/global-sensitivity',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}

export interface StudioSourceInspection {table:null|{rows:number;columns:Array<{name:string;kind:string;missing:number;nonmissing:number;distinct?:number;minimum?:number;maximum?:number;mean?:number}>};rasters:Array<{name:string;band:number;band_count:number;unit:string;crs:string;shape:number[];valid_cells:number;missing_cells:number;minimum:number;maximum:number;scale:number;offset:number;sha256:string}>;aligned:boolean|null;same_unit?:boolean;common_valid_cells?:number}
export function inspectStudioSources(csv:string,rasters:StudioRaster[],signal?:AbortSignal):Promise<StudioSourceInspection>{return request('/terrain/studio/inspect',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({csv,rasters})});}


export interface SpatialScienceMethod {id:string;group:string;title:string;source:'vector'|'raster'|'integrated';minimum:number;maximum:number;parameters:Array<{name:string;label:string;default:number;minimum:number;maximum:number;integer:boolean}>;result:'vector'|'raster'|'table';assumption:string;requires_weights:boolean;requires_pairwise:boolean;requires_directions:boolean;requires_breaks:boolean;requires_resampling:boolean;requires_local_view:boolean;requires_robust_view:boolean;requires_regression_view:boolean;requires_neighborhood?:boolean}
export interface SpatialScienceInput {operation:string;vectors:GeoJSON.FeatureCollection[];rasters:StudioRaster[];epsg:number;parameters:Record<string,number>;weights:number[];directions:string[];pairwise:number[][];breaks:number[];resampling:'nearest'|'bilinear';local_view:'statistic'|'p'|'q'|'cluster';robust_view?:'mean'|'sd'|'probability'|'mc_se'|'mc_lower'|'mc_upper';neighborhood?:'rook'|'queen';regression_view?:'prediction'|'residual'}
export interface SpatialRasterPreview {png:string;corners:TerrainRaster['corners'];width:number;height:number;valid_cells:number;minimum:number;maximum:number;unit:string;method:string}
export interface SpatialFigureSource {title:string;recipe:string;bindings:Partial<Pick<StudioInput,'x'|'y'|'z'|'group'|'columns'|'low'|'high'>>;csv:string|null;raster:boolean;bands?:number[]}
export interface SpatialScienceResult {operation:string;receipt:Record<string,unknown>&{metrics:Record<string,unknown>;crs:string};features:GeoJSON.FeatureCollection|null;raster:(StudioRaster&{sha256:string;band_count?:number})|null;preview:SpatialRasterPreview|null;figures?:SpatialFigureSource[];columns:string[];rows:Array<Array<string|number|null>>;csv:string}
export function getSpatialScienceCatalog(signal?:AbortSignal):Promise<{operations:SpatialScienceMethod[];operation_count:number}>{return request('/analysis/science/catalog',{signal});}
export function runSpatialScience(body:SpatialScienceInput,signal?:AbortSignal):Promise<SpatialScienceResult>{return request('/analysis/science/run',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}

export function getSpatialLayerSource(projectId:string,layerId:string):Promise<GeoJSON.FeatureCollection>{return request('/projects/'+encodeURIComponent(projectId)+'/spatial-science/source/'+encodeURIComponent(layerId));}
export function getSpatialRasterSource(imageId:string):Promise<StudioRaster>{return request('/imagery/'+encodeURIComponent(imageId)+'/spatial-science/source');}


export type RemoteEncoding='metadata'|'raw'|'landsat_sr'|'landsat_st'|'custom';
export type RemoteQualityScheme='binary'|'sentinel_clear'|'landsat_clear'|'landsat_unsaturated';
export interface RemoteSource {name:string;data:string;assetId?:string}
export interface RemoteBinding {source:number;band:number;encoding:RemoteEncoding;scale:number;offset:number;unit:string}
export interface RemoteQuality {source:number;band:number;scheme:RemoteQualityScheme;roles:string[]}
export interface RemoteMethod {id:string;group:string;title:string;roles:Array<{id:string;quantity:string}>;parameters:SpatialScienceMethod['parameters'];unit:string;assumption:string;variable_series?:boolean;axis?:'time'|'wavelength';windowed?:boolean;library?:boolean;joint_library?:boolean}
export interface RemoteTimeContext {time_unit:'second'|'hour'|'day'|'year';time_origin:string;acquisition_datetimes:string[]}
export interface RemoteInput {operation:string;sources:RemoteSource[];bindings:Record<string,RemoteBinding>;quality:RemoteQuality[];parameters:Record<string,number>;times?:number[];time_context?:RemoteTimeContext|null;library?:number[][]}
export function getRemoteCatalog(signal?:AbortSignal):Promise<{operations:RemoteMethod[];operation_count:number}>{return request('/analysis/remote-sensing/catalog',{signal});}
export function runRemoteScience(body:RemoteInput,signal?:AbortSignal):Promise<SpatialScienceResult>{return request('/analysis/remote-sensing/run',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}

export interface PreparedRemoteBands {bands:Array<StudioRaster&{role:string;sha256:string}>;common_mask:StudioRaster;receipt:Record<string,unknown>}
export function prepareRemoteBands(body:{sources:RemoteSource[];bindings:Record<string,RemoteBinding>;quantities:Record<string,string>;quality:RemoteQuality[];target:RemoteBinding;target_quantity:string;resampling:'nearest'|'bilinear'},signal?:AbortSignal):Promise<PreparedRemoteBands>{
 return request('/analysis/remote-sensing/prepare',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}

export function queueRemoteDiskJob(projectId:string,payload:Record<string,unknown>):Promise<GISJob>{
 return request('/projects/'+encodeURIComponent(projectId)+'/jobs',{method:'POST',headers:{'Content-Type':'application/json','X-GeoFathom-Local-Import':'1'},body:JSON.stringify({kind:'remote_windowed',payload})});
}
export function queueRemoteCubeJob(projectId:string,payload:Record<string,unknown>):Promise<GISJob>{
 return request('/projects/'+encodeURIComponent(projectId)+'/jobs',{method:'POST',headers:{'Content-Type':'application/json','X-GeoFathom-Local-Import':'1'},body:JSON.stringify({kind:'remote_cube',payload})});
}
export function queueRemoteModelJob(projectId:string,payload:Record<string,unknown>,training:boolean):Promise<GISJob>{
 return request('/projects/'+encodeURIComponent(projectId)+'/jobs',{method:'POST',headers:{'Content-Type':'application/json','X-GeoFathom-Local-Import':'1'},body:JSON.stringify({kind:training?'remote_model_train':'remote_model_predict',payload})});
}
export function queueRemoteEvaluationJob(projectId:string,payload:Record<string,unknown>):Promise<GISJob>{
 return request('/projects/'+encodeURIComponent(projectId)+'/jobs',{method:'POST',headers:{'Content-Type':'application/json','X-GeoFathom-Local-Import':'1'},body:JSON.stringify({kind:'remote_model_evaluate',payload})});
}
export function getScientificJobRecipe(projectId:string,id:string):Promise<Record<string,unknown>>{
 return request('/projects/'+encodeURIComponent(projectId)+'/jobs/'+encodeURIComponent(id)+'/recipe');
}
export function repeatScientificJob(projectId:string,id:string,allow_software_change=false):Promise<GISJob>{
 return request('/projects/'+encodeURIComponent(projectId)+'/jobs/'+encodeURIComponent(id)+'/repeat',{method:'POST',headers:{'Content-Type':'application/json','X-GeoFathom-Local-Import':'1'},body:JSON.stringify({allow_software_change})});
}
export function registerRemoteJobImagery(projectId:string,id:string):Promise<RasterAsset>{
 return request('/projects/'+encodeURIComponent(projectId)+'/jobs/'+encodeURIComponent(id)+'/imagery',{method:'POST',headers:{'X-GeoFathom-Local-Import':'1'}});
}
export async function downloadRemoteDiskJob(projectId:string,id:string,filename='remote-sensing.tif'):Promise<void>{
 const response=await rawRequest('/projects/'+encodeURIComponent(projectId)+'/jobs/'+encodeURIComponent(id)+'/download');
 if(!response.ok)throw Error('Completed remote raster required.');
 const url=URL.createObjectURL(await response.blob());
 try{const a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();}finally{window.setTimeout(()=>URL.revokeObjectURL(url),1000);}
}

export function readRemoteSceneCrop(body:{collection:'sentinel-2-l2a'|'sentinel-2-c1-l2a';item_id:string;bbox:[number,number,number,number];roles:string[]}):Promise<{bands:Array<RemoteSource&{role:string;unit:string;shape:number[];transform:number[];crs:string}>;warning:string}>{
 return request('/analysis/remote-sensing/scene-crop',{method:'POST',headers:{'Content-Type':'application/json','X-GeoFathom-Local-Import':'1'},body:JSON.stringify(body)});
}

export interface NetworkMethod {id:string;title:string;assumption:string}
export interface NetworkScienceInput {operation:string;network:GeoJSON.FeatureCollection;cost_field:string;cost_unit:string;origins:string[];destinations:string[];demand:Record<string,number>;supply:Record<string,number>;threshold:number;beta:number;closed_edges:string[];multipliers:Record<string,number>;test_edges:string[];failure_probability:Record<string,number>;trials:number;seed:number;facility_count:number;secondary_cost_field:string;secondary_cost_unit:string;spatial_range_m:number;exposure_reference:number;exposure_scale:number;exposure_alpha:number;raster?:{data:string;band:number};spacing_m:number;minimum_coverage:number;hazard_threshold:number}
export interface NetworkScienceResult {operation:string;columns:string[];rows:Array<Array<string|number|null>>;csv:string;features:GeoJSON.FeatureCollection;figures:SpatialFigureSource[];receipt:Record<string,unknown>&{metrics:Record<string,unknown>;nodes:number;edges:number}}
export function getNetworkScienceCatalog(signal?:AbortSignal):Promise<{operations:NetworkMethod[]}>{return request('/analysis/network-science/catalog',{signal});}
export function runNetworkScience(body:NetworkScienceInput,signal?:AbortSignal):Promise<NetworkScienceResult>{return request('/analysis/network-science/run',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}

export function buildOSMNetwork(snapshot:unknown,speed_kmh_by_class:Record<string,number>,signal?:AbortSignal):Promise<{network:GeoJSON.FeatureCollection;receipt:Record<string,unknown>}>{return request('/analysis/network-science/build-osm',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({snapshot,speed_kmh_by_class})});}

export interface SpacetimeMethod {id:string;group:string;title:string;requires_covariate?:boolean;parameters:SpatialScienceMethod['parameters']}
export interface SpacetimeInput {operation:string;sources:RemoteSource[];observations:RemoteBinding[];covariates?:RemoteBinding[];times:number[];quality:RemoteQuality[];time_unit:string;time_origin?:string;parameters:Record<string,number>}
export function getSpacetimeCatalog(signal?:AbortSignal):Promise<{operations:SpacetimeMethod[];operation_count:number}>{return request('/analysis/spatiotemporal/catalog',{signal});}
export function runSpacetime(body:SpacetimeInput,signal?:AbortSignal):Promise<SpatialScienceResult>{return request('/analysis/spatiotemporal/run',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}

export function archiveStudio(input:StudioInput|StudioComposition,provenance:unknown,signal?:AbortSignal):Promise<{archive:string;manifest:Record<string,unknown>}>{return request('/terrain/studio/archive',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({input,provenance:provenance??null})});}
export function reopenStudio(input:unknown,provenance:unknown,signal?:AbortSignal):Promise<{input:StudioInput|StudioComposition;provenance:unknown}>{return request('/terrain/studio/reopen',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({input,provenance:provenance??null})});}


export interface LidarMethod {id:string;title:string;assumption:string}
export interface LidarResult {mesh_obj?:string;raster_geotiff?:string|null;operation:string;columns:string[];rows:(number|null)[][];row_count:number;csv:string;figure_csv:string;metrics:Record<string,unknown>;assumption:string;receipt:Record<string,unknown>}
export function getLidarCatalog(signal?:AbortSignal):Promise<{operations:LidarMethod[]}>{return request('/analysis/lidar/catalog',{signal});}
export function runLidar(params:Record<string,string>,cloud:File,reference:File|null,signal?:AbortSignal):Promise<LidarResult>{
 const body=new FormData();body.append('cloud',cloud);if(reference)body.append('reference',reference);
 return request('/analysis/lidar/run?'+new URLSearchParams(params),{method:'POST',body,signal});
}

// Resolve disk-backed terrain products only when a consumer requests the exact raster.
// Enforce the existing inline scientific input budgets before buffering the response.
export type ScientificRasterInput = {name:string;data:string;unit?:string;band?:number;product_id?:string};
export async function materializeScientificRaster<T extends ScientificRasterInput>(r:T,limit=24_000_000,signal?:AbortSignal):Promise<T>{
 if(!r.product_id){if(!r.data)throw Error('Raster data is unavailable.');return r;}
 const response=await rawRequest('/terrain/products/'+encodeURIComponent(r.product_id),{signal});
 if(!response.ok)throw await responseError(response);
 const size=Number(response.headers.get('Content-Length'));
 if(size>limit){await response.body?.cancel();throw Error('Exact terrain raster exceeds the inline scientific input limit. Export the GeoTIFF and use a bounded study area or disk workflow.');}
 const reader=response.body?.getReader();if(!reader)throw Error('Raster response has no readable body.');
 const chunks:Uint8Array[]=[];let bytes=0;
 try{for(;;){const {done,value}=await reader.read();if(done)break;bytes+=value.byteLength;if(bytes>limit){await reader.cancel();throw Error('Exact terrain raster exceeds the inline scientific input limit. Export the GeoTIFF and use a bounded study area or disk workflow.');}chunks.push(value);}}finally{reader.releaseLock();}
 const raw=new Uint8Array(bytes);let offset=0;for(const chunk of chunks){raw.set(chunk,offset);offset+=chunk.byteLength;}
 // Use multiples of three so chunked encoding preserves the exact base64 byte stream.
 const encoded:string[]=[];for(let start=0;start<raw.length;start+=32766)encoded.push(btoa(String.fromCharCode(...raw.subarray(start,start+32766))));
 const data=encoded.join('');
 if(!data)throw Error('Raster product is empty.');
 return {...r,data};
}

export function remoteSampleRequest<T>(projectId:string,path='',body?:unknown):Promise<T>{
 return request('/projects/'+encodeURIComponent(projectId)+'/remote-samples'+path,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json','X-GeoFathom-Local-Import':'1'},body:JSON.stringify(body)});
}

export function queueRemoteExperiment(projectId:string,payload:Record<string,unknown>):Promise<GISJob>{
 return request('/projects/'+encodeURIComponent(projectId)+'/jobs',{method:'POST',headers:{'Content-Type':'application/json','X-GeoFathom-Local-Import':'1'},body:JSON.stringify({kind:'remote_experiment',payload})});
}
