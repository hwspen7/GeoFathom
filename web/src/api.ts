const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '');

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
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API_URL + path, init);
  if (!response.ok) {
    let detail = 'Request failed';
    try {
      const error = (await response.json()) as { detail?: unknown };
      if (typeof error.detail === 'string') detail = error.detail;
    } catch {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }
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
    headers: { 'X-GeoFathom-Admin-Token': adminToken },
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
): Promise<StacSearchResult> {
  return request<StacSearchResult>('/imagery/catalog/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bbox, collection, limit: 8 }),
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
