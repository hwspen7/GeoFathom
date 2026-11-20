import { useEffect, useRef, useState } from 'react';
import maplibregl, { type GeoJSONSource, type StyleSpecification } from 'maplibre-gl';

type Position = [number, number];
type DrawingMode = 'polygon' | 'line' | null;
export interface FocusPoint {
  longitude: number;
  latitude: number;
  bbox: [number, number, number, number] | null;
  key: number;
}

interface Props {
  selected: GeoJSON.Geometry | null;
  drawingMode: DrawingMode;
  vertices: Position[];
  focus: FocusPoint | null;
  satellite: boolean;
  onMapClick: (position: Position) => void;
  onViewportChange: (bbox: [number, number, number, number]) => void;
  discovered: GeoJSON.Geometry[];
}

const satelliteURL = import.meta.env.VITE_SATELLITE_TILES_URL;
const satelliteAttribution = import.meta.env.VITE_SATELLITE_ATTRIBUTION || 'Satellite imagery';

function mapStyle(): StyleSpecification {
  const style: StyleSpecification = {
    version: 8,
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
      type: 'raster',
      tiles: [satelliteURL],
      tileSize: 256,
      attribution: satelliteAttribution,
    };
    style.layers.push({
      id: 'satellite',
      type: 'raster',
      source: 'satellite',
      layout: { visibility: 'none' },
    });
  }
  return style;
}

function featureCollection(
  selected: GeoJSON.Geometry | null,
  vertices: Position[],
  discovered: GeoJSON.Geometry[],
): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = discovered.map(geometry => ({ type: 'Feature', properties: { role: 'candidate' }, geometry }));
  if (selected) {
    features.push({ type: 'Feature', properties: { role: 'selected' }, geometry: selected });
  }
  if (vertices.length >= 3) {
    features.push({
      type: 'Feature',
      properties: { role: 'drawing' },
      geometry: {
        type: 'Polygon',
        coordinates: [[...vertices, vertices[0]]],
      },
    });
  } else if (vertices.length >= 2) {
    features.push({
      type: 'Feature',
      properties: { role: 'drawing' },
      geometry: { type: 'LineString', coordinates: vertices },
    });
  }
  for (const position of vertices) {
    features.push({
      type: 'Feature',
      properties: { role: 'vertex' },
      geometry: { type: 'Point', coordinates: position },
    });
  }
  return { type: 'FeatureCollection', features };
}

export default function MapCanvas({
  selected, drawingMode, vertices, focus, satellite, onMapClick, onViewportChange, discovered,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const clickRef = useRef(onMapClick);
  const viewportRef = useRef(onViewportChange);
  const drawRef = useRef(drawingMode);
  const [ready, setReady] = useState(false);
  clickRef.current = onMapClick;
  viewportRef.current = onViewportChange;
  drawRef.current = drawingMode;

  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: mapStyle(),
      center: [0, 22],
      zoom: 2.1,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'bottom-right');
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-left');
    function reportViewport() {
      const extent = map.getBounds();
      viewportRef.current([extent.getWest(), extent.getSouth(), extent.getEast(), extent.getNorth()]);
    }
    map.on('moveend', reportViewport);
    map.on('click', (event) => {
      if (drawRef.current) clickRef.current([event.lngLat.lng, event.lngLat.lat]);
    });
    map.on('load', () => {
      map.addSource('workspace', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
      map.addLayer({
        id: 'workspace-fill', type: 'fill', source: 'workspace',
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: { 'fill-color': '#3977e3', 'fill-opacity': 0.17 },
      });
      map.addLayer({
        id: 'workspace-lines', type: 'line', source: 'workspace',
        filter: ['any', ['==', ['geometry-type'], 'Polygon'], ['==', ['geometry-type'], 'LineString']],
        paint: { 'line-color': '#2563eb', 'line-width': 3, 'line-opacity': 0.95 },
      });
      map.addLayer({
        id: 'workspace-points', type: 'circle', source: 'workspace',
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-color': '#ffffff', 'circle-radius': 6,
          'circle-stroke-color': '#2563eb', 'circle-stroke-width': 3,
        },
      });
      setReady(true);
      reportViewport();
    });
    mapRef.current = map;
    return () => {
      setReady(false);
      mapRef.current = null;
      map.remove();
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource('workspace') as GeoJSONSource).setData(featureCollection(selected, vertices, discovered));
  }, [selected, vertices, discovered, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !focus) return;
    const bounds = focus.bbox;
    if (bounds && bounds[0] < bounds[2] && bounds[1] < bounds[3]) {
      map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], {
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
    if (mapRef.current) {
      mapRef.current.getCanvas().style.cursor = drawingMode ? 'crosshair' : '';
    }
  }, [drawingMode, ready]);

  return <div aria-label="Interactive geospatial map" className="map-canvas" ref={container} />;
}
