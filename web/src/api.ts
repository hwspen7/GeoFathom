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
}

export interface Capabilities {
  geocoding: string;
  geodesic_measurement: boolean;
  geojson_export: boolean;
  llm_provider: string | null;
  llm_model?: string | null;
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

export function interpret(message: string, bbox?: [number, number, number, number] | null, profile: 'default' | 'analysis' = 'default'): Promise<AssistantResult> {
  return request<AssistantResult>('/assistant', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, bbox: bbox || null, profile }),
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

export function saveProjectFeature(projectId: string, name: string, geometry: GeoJSON.Geometry, source: string): Promise<StoredFeature> {
  return request<StoredFeature>('/projects/' + encodeURIComponent(projectId) + '/features', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, geometry, source }),
  });
}

export function exportProject(projectId: string): Promise<GeoJSON.FeatureCollection> {
  return request<GeoJSON.FeatureCollection>('/projects/' + encodeURIComponent(projectId) + '/export');
}
