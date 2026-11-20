import { useEffect, useState, type FormEvent } from 'react';
import {
  ArrowRight, Check, Compass, Download, Globe2, Layers3, MapPin,
  MousePointer2, Pencil, RotateCcw, Ruler, Search, Send, Sparkles,
  Undo2, Wifi, WifiOff,
} from 'lucide-react';

import {
  getCapabilities, interpret, measureGeometry, searchPlaces,
  type Capabilities, type Measurement, type Place,
} from './api';
import MapCanvas, { type FocusPoint } from './MapCanvas';
import DiscoveryPanel from './DiscoveryPanel';
import type { DiscoveryResponse, StoredFeature } from './api';
import ProjectsPanel from './ProjectsPanel';

type Position = [number, number];
type DrawingMode = 'polygon' | 'line' | null;

const number = (value: number, digits = 2) =>
  new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(value);

export default function App() {
  const [locationInput, setLocationInput] = useState('');
  const [prompt, setPrompt] = useState('');
  const [candidates, setCandidates] = useState<Place[]>([]);
  const [selectedPlace, setSelectedPlace] = useState<Place | null>(null);
  const [geometry, setGeometry] = useState<GeoJSON.Geometry | null>(null);
  const [measurement, setMeasurement] = useState<Measurement | null>(null);
  const [drawingMode, setDrawingMode] = useState<DrawingMode>(null);
  const [vertices, setVertices] = useState<Position[]>([]);
  const [viewport, setViewport] = useState<[number, number, number, number] | null>(null);
  const [discovered, setDiscovered] = useState<Place[]>([]);
  const [focus, setFocus] = useState<FocusPoint | null>(null);
  const [message, setMessage] = useState('Search a place or draw a shape directly on the map.');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [assistantQuery, setAssistantQuery] = useState('');
  const [modelProfile, setModelProfile] = useState<'default' | 'analysis'>('default');
  const [modelUsed, setModelUsed] = useState<boolean | null>(null);
  const [toolSteps, setToolSteps] = useState<string[]>([]);
  const [satellite, setSatellite] = useState(false);

  const satelliteAvailable = Boolean(import.meta.env.VITE_SATELLITE_TILES_URL);

  useEffect(() => {
    getCapabilities().then(setCapabilities).catch(() => setCapabilities(null));
  }, []);

  async function selectPlace(place: Place) {
    setSelectedPlace(place);
    setDrawingMode(null);
    setVertices([]);
    setGeometry(
      place.geometry || {
        type: 'Point',
        coordinates: [place.longitude, place.latitude],
      },
    );
    setMeasurement(null);
    setFocus({
      latitude: place.latitude,
      longitude: place.longitude,
      bbox: place.bbox,
      key: Date.now(),
    });
    if (place.geometry) {
      try {
        const result = await measureGeometry(place.geometry);
        setMeasurement(result);
        setMessage('Mapped boundary loaded. Check that it represents your intended area.');
      } catch (problem) {
        setError(problem instanceof Error ? problem.message : 'Could not measure boundary.');
        setMessage('Place found, but the mapped geometry could not be measured.');
      }
    } else {
      setMessage('Location found without a mapped boundary. Draw a polygon to measure it.');
    }
  }

  async function runSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = locationInput.trim();
    if (query.length < 2) return;
    setBusy(true);
    setError('');
    try {
      const found = await searchPlaces(query);
      setCandidates(found);
      if (found.length) {
        await selectPlace(found[0]);
        if (found.length > 1) setMessage('Multiple candidates found. Confirm the correct place below.');
      } else {
        setMessage('No place found. Try a different spelling or draw directly on the map.');
      }
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Search failed.');
    } finally {
      setBusy(false);
    }
  }

  async function runAssistant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = prompt.trim();
    if (query.length < 2) return;
    setBusy(true);
    setError('');
    setAssistantQuery(query);
    try {
      const answer = await interpret(query, viewport, modelProfile);
      setModelUsed(answer.model_used);
      setToolSteps((answer.steps || []).map(step => step.tool + ' · ' + step.status));
      setCandidates(answer.results);
      setMessage(answer.message);
      if (answer.intent.action === 'discover') {
        setDiscovered(answer.results);
        setSelectedPlace(null);
        setGeometry(null);
        setMeasurement(null);
      } else {
        setDiscovered([]);
        if (answer.results.length) await selectPlace(answer.results[0]);
        if (answer.results.length > 1) setMessage(answer.message + ' Select the correct candidate.');
      }
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Assistant request failed.');
    } finally {
      setBusy(false);
    }
  }

  function startDrawing(next: Exclude<DrawingMode, null>) {
    setDrawingMode(next);
    setVertices([]);
    setGeometry(null);
    setSelectedPlace(null);
    setMeasurement(null);
    setCandidates([]);
    setDiscovered([]);
    setError('');
    setMessage(next === 'polygon'
      ? 'Click at least three corners on the map, then finish the polygon.'
      : 'Click at least two points to trace a line, then finish.');
  }

  async function finishDrawing() {
    if (!drawingMode) return;
    const minPoints = drawingMode === 'polygon' ? 3 : 2;
    if (vertices.length < minPoints) {
      setError('Add more points before finishing the drawing.');
      return;
    }
    const result: GeoJSON.Geometry = drawingMode === 'polygon'
      ? { type: 'Polygon', coordinates: [[...vertices, vertices[0]]] }
      : { type: 'LineString', coordinates: vertices };
    setError('');
    try {
      const measured = await measureGeometry(result);
      setGeometry(result);
      setMeasurement(measured);
      setDrawingMode(null);
      setVertices([]);
      setMessage('Measured your custom shape using WGS84 geodesic calculations.');
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Invalid geometry.');
    }
  }

  function clearWorkspace() {
    setGeometry(null);
    setMeasurement(null);
    setDrawingMode(null);
    setVertices([]);
    setSelectedPlace(null);
    setCandidates([]);
    setDiscovered([]);
    setError('');
    setMessage('Workspace cleared. Search or draw to get started.');
  }

  function exportGeoJSON() {
    if (!geometry) return;
    const feature: GeoJSON.Feature = {
      type: 'Feature',
      geometry,
      properties: {
        name: selectedPlace?.name ?? 'Custom measurement',
        source: selectedPlace?.source ?? 'User-drawn geometry',
        boundary_status: selectedPlace?.boundary_status ?? 'user_drawn',
        measured_using: 'WGS84 ellipsoidal geodesic',
      },
    };
    const blob = new Blob([JSON.stringify(feature, null, 2)], { type: 'application/geo+json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'geofathom-feature.geojson';
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div className="workspace">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Globe2 size={23} strokeWidth={1.9} /></div>
          <div><strong>GeoFathom</strong><span>GEOSPATIAL INTELLIGENCE</span></div>
        </div>
        <div className="sidebar-scroll">
          <div className="intro">
            <div className="eyebrow"><Sparkles size={13} /> LOCAL-FIRST WORKSPACE</div>
            <h1>Explore the world, <em>spatially.</em></h1>
            <p>Find geographic features, inspect mapped boundaries, and measure real-world shapes.</p>
          </div>

          <section className="panel-section">
            <div className="section-heading"><Search size={16} /><span>Find a place</span></div>
            <form onSubmit={runSearch} className="search-form">
              <input aria-label="Search for a place" placeholder="Airport, landmark, city, address…" value={locationInput}
                onChange={event => setLocationInput(event.target.value)} maxLength={200} />
              <button aria-label="Search" type="submit" disabled={busy || locationInput.trim().length < 2}>
                <ArrowRight size={17} />
              </button>
            </form>
          </section>

          <section className="panel-section">
            <div className="section-heading"><Sparkles size={16} /><span>Ask GeoFathom</span><span className="section-pill">Assistant</span></div>
            <div className="model-switch">
              <button type="button" className={modelProfile === 'default' ? 'selected' : ''} onClick={() => setModelProfile('default')}>{capabilities?.llm_model || 'Saluki 27B'}</button>
              {capabilities?.analysis_model && <button type="button" className={modelProfile === 'analysis' ? 'selected' : ''} onClick={() => setModelProfile('analysis')}>{capabilities.analysis_model}</button>}
            </div>
            <form onSubmit={runAssistant} className="prompt-form">
              <textarea aria-label="Ask the geospatial assistant" placeholder="Measure Shanghai Hongqiao Airport's mapped boundary…" value={prompt}
                onChange={event => setPrompt(event.target.value)} maxLength={500} rows={3} />
              <div className="prompt-footer">
                <span>{modelProfile === 'analysis' ? 'Advanced reasoning' : capabilities?.llm_provider ? 'Local AI / safe fallback' : 'Search interpreter'}</span>
                <button type="submit" disabled={busy || prompt.trim().length < 2}>
                  <Send size={15} /> Run
                </button>
              </div>
            </form>
            {assistantQuery && <div className="last-prompt">“{assistantQuery}” <span>{modelUsed ? 'AI parsed' : 'Rules parsed'}</span></div>}
            {toolSteps.length > 0 && <div className="tool-trace"><strong>Execution trace</strong><span>{toolSteps.join(' → ')}</span></div>}
          </section>

          <section className="panel-section">
            <div className="section-heading"><Pencil size={16} /><span>Map tools</span></div>
            <div className="tools-grid">
              <button className={drawingMode === 'polygon' ? 'tool active' : 'tool'} onClick={() => startDrawing('polygon')}>
                <Pencil size={17} /><span>Draw area</span>
              </button>
              <button className={drawingMode === 'line' ? 'tool active' : 'tool'} onClick={() => startDrawing('line')}>
                <Ruler size={17} /><span>Draw line</span>
              </button>
            </div>
            {drawingMode && (
              <div className="drawing-actions">
                <span><MousePointer2 size={14} /> {vertices.length} points</span>
                <div>
                  <button title="Undo last point" onClick={() => setVertices(value => value.slice(0, -1))} disabled={!vertices.length}><Undo2 size={16} /></button>
                  <button title="Cancel drawing" onClick={() => { setDrawingMode(null); setVertices([]); }}><RotateCcw size={16} /></button>
                  <button className="finish-button" onClick={finishDrawing}><Check size={15} /> Finish</button>
                </div>
              </div>
            )}
          </section>

          <section className="panel-section">
            <div className="section-heading"><Layers3 size={16} /><span>Projects & saved geometry</span></div>
            <ProjectsPanel
              geometry={geometry}
              featureName={selectedPlace?.name || 'Custom boundary'}
              featureSource={selectedPlace?.source || 'User drawn'}
              onOpen={(feature: StoredFeature) => {
                setGeometry(feature.geometry);
                setMeasurement(feature.measurement);
                setSelectedPlace(null);
                setCandidates([]);
                setDiscovered([]);
                setDrawingMode(null);
                const [west, south, east, north] = feature.measurement.bounds;
                setFocus({
                  longitude: (west + east) / 2,
                  latitude: (south + north) / 2,
                  bbox: [west, south, east, north],
                  key: Date.now(),
                });
                setMessage('Loaded saved feature: ' + feature.name + ' · ' + feature.source);
              }}
            />
          </section>

          <section className="panel-section">
            <div className="section-heading"><Search size={16} /><span>Find areas by size</span><span className="section-pill">Spatial query</span></div>
            <DiscoveryPanel viewport={viewport} busy={busy} onFound={(result: DiscoveryResponse) => {
              setDiscovered(result.results);
              setCandidates(result.results);
              setSelectedPlace(null);
              setGeometry(null);
              setMeasurement(null);
              setMessage(result.results.length
                ? 'Found ' + result.results.length + ' mapped features. ' + result.warning
                : 'No mapped features matched the filter. ' + result.warning);
              setError('');
            }} />
          </section>

          {candidates.length > 0 && (
            <section className="panel-section">
              <div className="section-heading"><MapPin size={16} /><span>Search results</span><span className="result-count">{candidates.length}</span></div>
              <div className="results">
                {candidates.map(place => (
                  <button key={place.id} className={selectedPlace?.id === place.id ? 'result active' : 'result'} onClick={() => { setError(''); void selectPlace(place); }}>
                    <MapPin size={15} />
                    <span className="result-text"><strong>{place.name}</strong><small>{place.display_name}</small></span>
                    <span className={place.boundary_status === 'mapped' ? 'result-tag mapped' : 'result-tag'}>
                      {place.boundary_status === 'mapped' ? 'Boundary' : 'Point'}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}

          <section className="panel-section results-summary">
            <div className="section-heading"><Compass size={16} /><span>Analysis</span></div>
            <div className="analysis-card">
              <div className="analysis-status">{error ? <span className="error">{error}</span> : message}</div>
              {measurement && (
                <>
                  <div className="metric">
                    <span>{measurement.area_m2 !== null ? 'Geographic area' : 'Distance'}</span>
                    <strong>{measurement.area_km2 !== null
                      ? number(measurement.area_km2, 4) + ' km²'
                      : measurement.length_m !== null ? number(measurement.length_m / 1000, 3) + ' km' : 'Location only'}</strong>
                  </div>
                  {measurement.perimeter_m !== null && <div className="metric secondary"><span>Perimeter</span><strong>{number(measurement.perimeter_m / 1000, 3)} km</strong></div>}
                  {measurement.area_m2 !== null && <div className="metric secondary"><span>Square meters</span><strong>{number(measurement.area_m2)} m²</strong></div>}
                  <p className="analysis-footnote">{measurement.method}. {measurement.note}</p>
                </>
              )}
              {selectedPlace && <p className="data-source">Data: {selectedPlace.source} · {selectedPlace.boundary_status === 'mapped' ? 'Mapped outline' : 'Coordinates only'}</p>}
              <div className="analysis-actions">
                <button onClick={exportGeoJSON} disabled={!geometry}><Download size={15} /> Export GeoJSON</button>
                <button onClick={clearWorkspace}><RotateCcw size={15} /> Clear</button>
              </div>
            </div>
          </section>
        </div>
        <div className="sidebar-footer">
          {capabilities ? <span><Wifi size={14} /> API connected</span> : <span><WifiOff size={14} /> API not connected</span>}
          <span>No fabricated measurements</span>
        </div>
      </aside>

      <main className="main">
        <div className="map-topbar">
          <div className="map-title"><span className="map-title-icon"><Layers3 size={18} /></span><div><strong>Explore</strong><span>Interactive map workspace</span></div></div>
          <div className="map-controls">
            <button className={!satellite ? 'map-control selected' : 'map-control'} onClick={() => setSatellite(false)}><Globe2 size={16} /> Streets</button>
            {satelliteAvailable && <button className={satellite ? 'map-control selected' : 'map-control'} onClick={() => setSatellite(true)}><Layers3 size={16} /> Imagery</button>}
          </div>
        </div>
        <div className="map-wrap">
          <MapCanvas
            selected={geometry} drawingMode={drawingMode} vertices={vertices}
            focus={focus} satellite={satellite}
            discovered={discovered.map(place => place.geometry).filter((item): item is GeoJSON.Geometry => item !== null)}
            onViewportChange={setViewport}
            onMapClick={position => setVertices(value => [...value, position])}
          />
          <div className="map-hint"><MousePointer2 size={15} /> {drawingMode ? 'Click to add points, then Finish' : 'Pan, zoom, or choose a result'}</div>
          <div className="map-badge"><span className="live-dot" /> WGS84 GEODESIC ENGINE</div>
        </div>
        <div className="bottom-bar">
          <span><Compass size={14} /> Coordinate-based analysis</span>
          <span><Globe2 size={14} /> OpenStreetMap contributors</span>
        </div>
      </main>
    </div>
  );
}
