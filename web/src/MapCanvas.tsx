import { useEffect, useRef, useState } from 'react';
import maplibregl, { type GeoJSONSource, type MapMouseEvent, type StyleSpecification } from 'maplibre-gl';

import { rasterPreviewUrl, type RasterAsset } from './api';
import { PixelSnapIndex } from './spatialIndex';
import { featureLabel } from './labels';
import type { Measurement,LayerStyle } from './api';
import {
  addVertex, moveVertex, removeVertex, translateSpherical, geodesicDrag, pathsOf,
  verticesOf, type GeometryPath, type Position, type ShapeMode,
} from './editing';

export interface FocusPoint {
  longitude: number;
  latitude: number;
  bbox: [number, number, number, number] | null;
  key: number;
}

export interface MapLayerFeature {
  id: string;
  name: string;
  properties: Record<string,unknown>;
  source: string;
  measurement: Measurement;
  style: LayerStyle;
  geometry: GeoJSON.Geometry;
  layer_id: string;
  color: string;
  visible: boolean;
  locked: boolean;
}

interface Props {
  selected: GeoJSON.Geometry | null;
  drawingMode: ShapeMode;
  vertices: Position[];
  focus: FocusPoint | null;
  satellite: boolean;
  onMapClick: (position: Position) => void;
  onViewportChange: (bbox: [number, number, number, number]) => void;
  discovered: GeoJSON.Geometry[];
  imageLayer: RasterAsset | null;
  traceMode: boolean;
  onTraceClick: (position: Position) => void;
  editing: boolean;
  moving: boolean;
  snapping: boolean;
  selectedLocked: boolean;
  layerFeatures: MapLayerFeature[];
  promptPositive:Position[];
  promptNegative:Position[];
  promptBox:Position[];
  annotationMode:boolean;
  onAnnotationClick:(position:Position)=>void;
  onGeometryPreview: (geometry: GeoJSON.Geometry) => void;
  onGeometryCommit: (geometry: GeoJSON.Geometry, movement?: {
    original:GeoJSON.Geometry;bearing_deg:number;distance_m:number;
  }) => void;
  onSelectSavedFeature: (id: string) => void;
}

const satelliteURL = import.meta.env.VITE_SATELLITE_TILES_URL;
const satelliteAttribution = import.meta.env.VITE_SATELLITE_ATTRIBUTION || 'Satellite imagery';

function mapStyle(): StyleSpecification {
  const style: StyleSpecification = {
    version: 8,
    glyphs:import.meta.env.VITE_GLYPHS_URL ||
      'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {
      street: {
        type: 'raster',
        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
        tileSize: 256,
        attribution: '© OpenStreetMap contributors',
        maxzoom: 19,
      },
    },
    layers: [{ id: 'street', type: 'raster', source: 'street' }],
  };
  if (satelliteURL) {
    style.sources.satellite = {
      type: 'raster', tiles: [satelliteURL], tileSize: 256,
      attribution: satelliteAttribution,
    };
    style.layers.push({
      id: 'satellite', type: 'raster', source: 'satellite',
      layout: { visibility: 'none' },
    });
  }
  return style;
}

function featureCollection(
  selected: GeoJSON.Geometry | null,
  vertices: Position[],
  drawingMode: ShapeMode,
  discovered: GeoJSON.Geometry[],
  layerFeatures: MapLayerFeature[],
  editing: boolean,
  promptPositive:Position[],promptNegative:Position[],promptBox:Position[],
  zoom:number,
): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  for (const saved of layerFeatures) {
    if (!saved.visible) continue;
    features.push({
      type: 'Feature', geometry: saved.geometry,
      properties: {
        role:'saved',id:saved.id,color:saved.color,
        locked:saved.locked,layer_id:saved.layer_id,
        name:saved.name,
        label:featureLabel(saved,zoom),
        labelSize:saved.style.labels.font_size,
        labelColor:saved.style.labels.text_color,
        labelHaloColor:saved.style.labels.halo_color,
        labelHaloWidth:saved.style.labels.halo_width,
        labelOverlap:saved.style.labels.allow_overlap,
        fillOpacity:saved.style.symbol.fill_opacity,
        lineWidth:saved.style.symbol.line_width,
        pointRadius:saved.style.symbol.point_radius,
        strokeColor:saved.style.symbol.stroke_color,
      },
    });
  }
  for (const geometry of discovered) {
    features.push({
      type: 'Feature', properties: { role: 'candidate', color: '#9d8b4a' }, geometry,
    });
  }
  if (selected) {
    features.push({
      type: 'Feature', properties: { role: 'selected', color: '#2563eb' },
      geometry: selected,
    });
  }

  if (vertices.length >= 3 && drawingMode !== 'line' && drawingMode !== 'split') {
    features.push({
      type: 'Feature', properties: { role: 'drawing', color: '#ec8b2c' },
      geometry: { type: 'Polygon', coordinates: [[...vertices, vertices[0]]] },
    });
  } else if (vertices.length >= 2) {
    features.push({
      type: 'Feature', properties: { role: 'drawing', color: '#ec8b2c' },
      geometry: { type: 'LineString', coordinates: vertices },
    });
  }
  for (const position of vertices) {
    features.push({
      type: 'Feature', properties: { role: 'draw-vertex' },
      geometry: { type: 'Point', coordinates: position },
    });
  }

  for(const [role,points] of [['prompt-positive',promptPositive],['prompt-negative',promptNegative]] as const){
    for(const point of points){
      features.push({type:'Feature',
        properties:{role},geometry:{type:'Point',coordinates:point}});
    }
  }
  for(const point of promptBox){
    features.push({type:'Feature',
      properties:{role:'prompt-box-corner'},geometry:{type:'Point',coordinates:point}});
  }
  if(promptBox.length===2){
    const [a,b]=promptBox;
    const west=Math.min(a[0],b[0]),east=Math.max(a[0],b[0]);
    const south=Math.min(a[1],b[1]),north=Math.max(a[1],b[1]);
    features.push({type:'Feature',properties:{role:'prompt-box',color:'#ef9238'},
      geometry:{type:'Polygon',coordinates:[[[west,south],[east,south],
        [east,north],[west,north],[west,south]]]}});
  }
  if (editing && selected) {
    for (const node of verticesOf(selected)) {
      features.push({
        type: 'Feature',
        properties: {
          role: node.midpoint ? 'edit-midpoint' : 'edit-vertex',
          polygon: node.path.polygon,
          ring: node.path.ring,
          vertex: node.path.vertex,
        },
        geometry: { type: 'Point', coordinates: node.point },
      });
    }
  }
  return { type: 'FeatureCollection', features };
}

type Drag = {
  start: Position;
  end: Position;
  original: GeoJSON.Geometry;
  last: GeoJSON.Geometry;
  path: GeometryPath | null;
  kind: 'vertex' | 'feature';
};

export default function MapCanvas({
  selected, drawingMode, vertices, focus, satellite, onMapClick,
  onViewportChange, discovered, imageLayer, traceMode, onTraceClick,
  editing, moving, snapping, selectedLocked, layerFeatures,
  promptPositive,promptNegative,promptBox,annotationMode,onAnnotationClick,
  onGeometryPreview, onGeometryCommit, onSelectSavedFeature,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const eventRef = useRef({
    selected, drawingMode, traceMode, annotationMode,editing, moving, snapping, selectedLocked,
    layerFeatures, onMapClick, onTraceClick,onAnnotationClick,onViewportChange,
    onGeometryPreview, onGeometryCommit, onSelectSavedFeature,
  });
  const renderRef = useRef({
    selected,vertices,drawingMode,discovered,layerFeatures,editing,
    promptPositive,promptNegative,promptBox,
  });
  renderRef.current={
    selected,vertices,drawingMode,discovered,layerFeatures,editing,
    promptPositive,promptNegative,promptBox,
  };
  const drag = useRef<Drag | null>(null);
  const spatialSnap = useRef<PixelSnapIndex|null>(null);
  const [ready, setReady] = useState(false);
  eventRef.current = {
    selected, drawingMode, traceMode, annotationMode,editing, moving, snapping, selectedLocked,
    layerFeatures, onMapClick, onTraceClick,onAnnotationClick,onViewportChange,
    onGeometryPreview, onGeometryCommit, onSelectSavedFeature,
  };

  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current, style: mapStyle(), center: [0, 22],
      zoom: 2.1, attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'bottom-right');
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-left');
    map.addControl(new maplibregl.ScaleControl({ maxWidth:140,unit:'metric' }), 'bottom-left');
    const refreshZoomLabels=()=>{
      const view=renderRef.current;
      const source=map.getSource('workspace') as GeoJSONSource | undefined;
      if(!source)return;
      source.setData(featureCollection(
        view.selected,view.vertices,view.drawingMode,view.discovered,view.layerFeatures,
        view.editing,view.promptPositive,view.promptNegative,view.promptBox,map.getZoom(),
      ));
    };
    map.on('zoomend',refreshZoomLabels);

    function bounds() {
      spatialSnap.current=null;
      const extent = map.getBounds();
      eventRef.current.onViewportChange([
        extent.getWest(), extent.getSouth(), extent.getEast(), extent.getNorth(),
      ]);
    }
    function coordinates(event: MapMouseEvent): Position {
      return [event.lngLat.lng, event.lngLat.lat];
    }
    function hits(event: MapMouseEvent) {
      if (!map.getLayer('workspace-points')) return [];
      return map.queryRenderedFeatures(event.point, {
        layers: ['workspace-points', 'workspace-lines', 'workspace-fill'],
      });
    }
    function nodePath(props: GeoJSON.GeoJsonProperties): GeometryPath {
      return {
        polygon: Number(props?.polygon || 0),
        ring: Number(props?.ring || 0),
        vertex: Number(props?.vertex || 0),
      };
    }
    function beginDrag(event: MapMouseEvent) {
      spatialSnap.current=null;
      const state = eventRef.current;
      if (!state.editing || state.selectedLocked || !state.selected) return;
      const features = hits(event);
      const handle = features.find(f => f.properties?.role === 'edit-vertex'
                                   || f.properties?.role === 'edit-midpoint');
      let first = state.selected;
      let path: GeometryPath | null = null;
      let kind: Drag['kind'] | null = null;
      if (handle) {
        path = nodePath(handle.properties);
        if (handle.properties?.role === 'edit-midpoint') {
          first = addVertex(first, path, coordinates(event));
          path = { ...path, vertex: path.vertex + 1 };
          state.onGeometryPreview(first);
        }
        kind = 'vertex';
      } else if (
        state.moving && features.some(f => f.properties?.role === 'selected')
      ) {
        kind = 'feature';
      }
      if (!kind) return;
      drag.current = { original: first, last: first, path, kind,
        start: coordinates(event),end:coordinates(event) };
      map.dragPan.disable();
      map.getCanvas().style.cursor = 'grabbing';
      event.preventDefault();
    }
    function snapAt(point:Position,movingPath:GeometryPath|null):Position {
      const state=eventRef.current;
      if(!state.snapping)return point;
      if(!spatialSnap.current) {
        const paths:Position[][]=[];
        for(const feature of state.layerFeatures) {
          if(!feature.visible)continue;
          // Do not snap a selected saved polygon onto the geometry that is
          // currently being dragged; keep neighboring polygons available.
          if(state.selected && JSON.stringify(feature.geometry)===JSON.stringify(state.selected))
            continue;
          paths.push(...pathsOf(feature.geometry));
        }
        if(!movingPath && state.selected)paths.push(...pathsOf(state.selected));
        spatialSnap.current=new PixelSnapIndex(paths,position=>{
          const p=map.project(position as maplibregl.LngLatLike);
          return [p.x,p.y];
        });
      }
      const pixel=map.project(point as maplibregl.LngLatLike);
      const old=movingPath&&state.selected?
        verticesOf(state.selected).find(item=>!item.midpoint&&
          item.path.polygon===movingPath.polygon&&
          item.path.ring===movingPath.ring&&
          item.path.vertex===movingPath.vertex)?.point :undefined;
      const hit=spatialSnap.current.snap([pixel.x,pixel.y],12,old);
      return hit.kind==='none'?point:hit.point;
    }
    function dragging(event: MapMouseEvent) {
      const current = drag.current;
      if (!current) return;
      const coordinate = coordinates(event);
      current.end=coordinate;
      let changed: GeoJSON.Geometry;
      if (current.kind === 'feature') {
        const delta=geodesicDrag(current.start,coordinate);
        changed=translateSpherical(current.original,delta.bearing_deg,delta.distance_m);
      } else {
        changed = moveVertex(current.original, current.path!, snapAt(coordinate, current.path));
      }
      current.last = changed;
      eventRef.current.onGeometryPreview(changed);
    }
    function finishDrag() {
      const current = drag.current;
      if (!current) return;
      drag.current = null;
      map.dragPan.enable();
      map.getCanvas().style.cursor = 'crosshair';
      if(current.kind==='feature'){
        const delta=geodesicDrag(current.start,current.end);
        if(delta.distance_m>0.001){
          eventRef.current.onGeometryCommit(current.last,{
            original:current.original,...delta,
          });
        }
      }else{
        eventRef.current.onGeometryCommit(current.last);
      }
    }
    function click(event: MapMouseEvent) {
      const state = eventRef.current;
      if (drag.current) return;
      if (state.annotationMode) state.onAnnotationClick(coordinates(event));
      else if (state.traceMode) state.onTraceClick(coordinates(event));
      else if (state.drawingMode) state.onMapClick(snapAt(coordinates(event), null));
      else if (!state.editing) {
        const feature = hits(event).find(f => f.properties?.role === 'saved');
        if (feature?.properties?.id) state.onSelectSavedFeature(String(feature.properties.id));
      }
    }
    function removeByRightClick(event: MapMouseEvent) {
      const state = eventRef.current;
      if (!state.editing || state.selectedLocked || !state.selected) return;
      const feature = hits(event).find(f => f.properties?.role === 'edit-vertex');
      if (!feature) return;
      event.preventDefault();
      try {
        state.onGeometryCommit(removeVertex(state.selected, nodePath(feature.properties)));
      } catch { /* The minimum ring size is enforced by the edit toolbar. */ }
    }
    function insertByDoubleClick(event: MapMouseEvent) {
      const state = eventRef.current;
      if (!state.editing || state.selectedLocked || !state.selected) return;
      const edges = verticesOf(state.selected).filter(p => p.midpoint);
      if (!edges.length) return;
      const pixel = event.point;
      let distance = 10;
      let selectedPath: GeometryPath | null = null;
      let snapped: Position | null = null;
      const geoms = pathsOf(state.selected);
      for (const node of edges) {
        const index = state.selected?.type === 'MultiPolygon'
          ? state.selected.coordinates.slice(0,node.path.polygon).reduce((sum,group) => sum+group.length,0) + node.path.ring
          : node.path.ring;
        const path = geoms[index];
        if (!path) continue;
        const first = path[node.path.vertex];
        const next = path[node.path.vertex + 1];
        if (!first || !next) continue;
        const a = map.project(first as maplibregl.LngLatLike);
        const b = map.project(next as maplibregl.LngLatLike);
        const dx = b.x - a.x, dy = b.y - a.y;
        const length = dx * dx + dy * dy;
        if (!length) continue;
        const t = Math.max(0, Math.min(1,
          ((pixel.x - a.x) * dx + (pixel.y - a.y) * dy) / length));
        const close = Math.hypot(pixel.x - a.x - dx * t,pixel.y - a.y - dy * t);
        if (close < distance) {
          distance = close;
          selectedPath = node.path;
          snapped = [first[0] + (next[0] - first[0]) * t,
                     first[1] + (next[1] - first[1]) * t];
        }
      }
      if (selectedPath && snapped) {
        event.preventDefault();
        state.onGeometryCommit(addVertex(state.selected, selectedPath, snapped));
      }
    }

    map.on('moveend', bounds);
    map.on('click', click);
    map.on('mousedown', beginDrag);
    map.on('mousemove', dragging);
    map.on('mouseup', finishDrag);
    map.on('contextmenu', removeByRightClick);
    map.on('dblclick', insertByDoubleClick);
    map.on('load', () => {
      map.addSource('workspace', {
        type: 'geojson', data: { type: 'FeatureCollection', features: [] },
      });
      map.addLayer({
        id: 'workspace-fill', type: 'fill', source: 'workspace',
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: {
          'fill-color': ['coalesce', ['get', 'color'], '#2563eb'],
          'fill-opacity': ['coalesce',['get','fillOpacity'],0.17],
        },
      });
      map.addLayer({
        id: 'workspace-lines', type: 'line', source: 'workspace',
        filter: ['any', ['==', ['geometry-type'], 'Polygon'],
                        ['==', ['geometry-type'], 'LineString']],
        paint: {
          'line-color': ['coalesce', ['get', 'color'], '#2563eb'],
          'line-width': ['coalesce',['get','lineWidth'],3], 'line-opacity': 0.95,
        },
      });
      map.addLayer({
        id: 'workspace-points', type: 'circle', source: 'workspace',
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-color': [
            'match',['get','role'],
            'prompt-positive','#39b779','prompt-negative','#ed4a4a',
            'prompt-box-corner','#f2a138','edit-midpoint','#c9e5ff',
            'saved',['coalesce',['get','color'],'#2563eb'],'#ffffff',
          ],
          'circle-radius': [
            'case',['==',['get','role'],'edit-midpoint'],4,
            ['coalesce',['get','pointRadius'],6],
          ],
          'circle-stroke-color': ['coalesce',['get','strokeColor'],'#2563eb'],
          'circle-stroke-width': 2,
        },
      });
      map.addLayer({
        id:'workspace-labels',type:'symbol',source:'workspace',
        filter:['all',['==',['get','role'],'saved'],['!=',['get','label'],'']],
        layout:{
          'text-field':['get','label'],
          'text-font':['Open Sans Regular'],
          'text-size':['coalesce',['get','labelSize'],12],
          'text-max-width':15,
          'text-allow-overlap':['coalesce',['get','labelOverlap'],false],
          'text-padding':4,
          'text-optional':true,
        },
        paint:{
          'text-color':['coalesce',['get','labelColor'],'#183954'],
          'text-halo-color':['coalesce',['get','labelHaloColor'],'#ffffff'],
          'text-halo-width':['coalesce',['get','labelHaloWidth'],1.5],
        },
      });
      setReady(true);
      bounds();
    });
    mapRef.current = map;
    return () => {
      map.off('zoomend',refreshZoomLabels);
      map.off('mousemove', dragging);
      map.off('mouseup', finishDrag);
      map.dragPan.enable();
      mapRef.current = null;
      map.remove();
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource('workspace') as GeoJSONSource).setData(
      featureCollection(selected, vertices, drawingMode, discovered, layerFeatures, editing,
        promptPositive,promptNegative,promptBox,map.getZoom()),
    );
    if (!drag.current) spatialSnap.current=null;
  }, [selected, vertices, drawingMode, discovered, layerFeatures, editing,
      promptPositive,promptNegative,promptBox,ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !focus) return;
    if (focus.bbox && focus.bbox[0] < focus.bbox[2] && focus.bbox[1] < focus.bbox[3]) {
      map.fitBounds([[focus.bbox[0], focus.bbox[1]], [focus.bbox[2], focus.bbox[3]]], {
        padding: 70, maxZoom: 16, duration: 950,
      });
    } else {
      map.flyTo({ center: [focus.longitude, focus.latitude], zoom: 15, duration: 950 });
    }
  }, [focus, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (ready && map && satelliteURL) {
      map.setLayoutProperty('satellite', 'visibility', satellite ? 'visible' : 'none');
    }
  }, [satellite, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (map.getLayer('imported-imagery')) map.removeLayer('imported-imagery');
    if (map.getSource('imported-imagery')) map.removeSource('imported-imagery');
    if (imageLayer) {
      map.addSource('imported-imagery', {
        type: 'image', url: rasterPreviewUrl(imageLayer),
        coordinates: imageLayer.corners,
      });
      map.addLayer({
        id: 'imported-imagery', type: 'raster', source: 'imported-imagery',
        paint: { 'raster-opacity': 0.88, 'raster-fade-duration': 0 },
      }, 'workspace-fill');
    }
  }, [imageLayer, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.doubleClickZoom[editing ? 'disable' : 'enable']();
    map.getCanvas().style.cursor = drawingMode || traceMode || editing || annotationMode ? 'crosshair' : '';
  }, [editing, drawingMode, traceMode, annotationMode, ready]);

  return <div aria-label="Interactive geospatial map" className="map-canvas" ref={container} />;
}
