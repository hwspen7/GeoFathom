import { useState, type FormEvent } from 'react';
import {
  Check, Circle, Copy, CornerDownRight, Eraser, GitMerge, MousePointer2,
  Pencil, Redo2, RotateCcw, Ruler, Scissors, Undo2,
} from 'lucide-react';

import type { ShapeMode, Position } from './editing';
import type { WorkspaceFeature } from './api';

interface Props {
  mode: ShapeMode;
  geometry: GeoJSON.Geometry | null;
  points: Position[];
  editing: boolean;
  moving: boolean;
  snapping: boolean;
  canUndo: boolean;
  canRedo: boolean;
  saved: WorkspaceFeature[];
  onStart: (mode: Exclude<ShapeMode, null>) => void;
  onFinish: () => void;
  onCancel: () => void;
  onUndoPoint: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onEdit: (editing: boolean, moving: boolean) => void;
  onSnapping: (enabled: boolean) => void;
  onAddPoint: (position: Position) => void;
  onNumeric: (mode: string, body: {
    vertices: Position[]; radius_m?: number; bearing_deg?: number; length_m?: number;
  }) => void;
  onOverlay: (mode: 'union' | 'difference' | 'intersection', featureId: string) => void;
  onDuplicate: () => void;
}

const buttonModes: Array<{ mode: Exclude<ShapeMode, null>; title: string }> = [
  { mode: 'polygon', title: 'Polygon' },
  { mode: 'line', title: 'Line' },
  { mode: 'rectangle', title: 'Rectangle' },
  { mode: 'circle', title: 'Circle' },
  { mode: 'hole', title: 'Cut hole' },
  { mode: 'split', title: 'Split line' },
];

export default function SurveyTools({
  mode, geometry, points, editing, moving, snapping, canUndo, canRedo, saved,
  onStart, onFinish, onCancel, onUndoPoint, onUndo, onRedo, onEdit,
  onSnapping, onAddPoint, onNumeric, onOverlay, onDuplicate,
}: Props) {
  const [longitude, setLongitude] = useState('');
  const [latitude, setLatitude] = useState('');
  const [endLongitude, setEndLongitude] = useState('');
  const [endLatitude, setEndLatitude] = useState('');
  const [radius, setRadius] = useState('100');
  const [bearing, setBearing] = useState('90');
  const [numericMode, setNumericMode] = useState('point');
  const [reference, setReference] = useState('');

  function numeric(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const first: Position = [Number(longitude), Number(latitude)];
    if (!Number.isFinite(first[0]) || !Number.isFinite(first[1]) || !longitude || !latitude) return;
    if (numericMode === 'point') {
      onAddPoint(first);
      return;
    }
    const second: Position = [Number(endLongitude), Number(endLatitude)];
    onNumeric(numericMode, {
      vertices: numericMode === 'rectangle' ? [first, second] : [first],
      radius_m: Number(radius),
      bearing_deg: Number(bearing), length_m: Number(radius),
    });
  }

  return (
    <div className="survey-tools">
      <div className="survey-mode-grid">
        {buttonModes.map(item => (
          <button key={item.mode} className={mode === item.mode ? 'active' : ''}
            title={'Draw ' + item.title.toLowerCase()} onClick={() => onStart(item.mode)}
            disabled={['hole','split'].includes(item.mode) && geometry?.type !== 'Polygon' && geometry?.type !== 'MultiPolygon'}>
            {item.mode === 'circle' ? <Circle size={15}/> :
             item.mode === 'line' ? <Ruler size={15}/> :
             item.mode === 'split' ? <Scissors size={15}/> :
             item.mode === 'hole' ? <Eraser size={15}/> : <Pencil size={15}/>}
            {item.title}
          </button>
        ))}
      </div>
      {mode && (
        <div className="survey-action-bar">
          <span><MousePointer2 size={13}/> {points.length} pts</span>
          <button title="Remove last point" disabled={!points.length} onClick={onUndoPoint}><Undo2 size={14}/></button>
          <button title="Cancel" onClick={onCancel}><RotateCcw size={14}/></button>
          <button className="finish-button" onClick={onFinish}><Check size={14}/> Finish</button>
        </div>
      )}
      <div className="survey-action-bar">
        <button title="Edit vertices" disabled={!geometry} className={editing && !moving ? 'active' : ''}
          onClick={() => onEdit(!editing || moving, false)}><Pencil size={14}/> Vertices</button>
        <button title="Move whole shape" disabled={!geometry} className={moving ? 'active' : ''}
          onClick={() => onEdit(!moving, !moving)}><MousePointer2 size={14}/> Move</button>
        <button title="Snap to nearby vertices" className={snapping ? 'active' : ''}
          onClick={() => onSnapping(!snapping)}>Snap {snapping ? 'ON' : 'OFF'}</button>
      </div>
      <p className="project-hint">Drag white corner handles to reshape. Drag blue midpoints to insert. Right-click a corner to remove it. Use Move to drag the whole feature.</p>
      <div className="survey-action-bar">
        <button disabled={!canUndo} onClick={onUndo}><Undo2 size={14}/> Undo</button>
        <button disabled={!canRedo} onClick={onRedo}><Redo2 size={14}/> Redo</button>
        <button disabled={!geometry} onClick={onDuplicate}><Copy size={14}/> Copy</button>
      </div>
      <form className="survey-numeric" onSubmit={numeric}>
        <div className="section-heading"><CornerDownRight size={14}/> Exact coordinates and construction</div>
        <select aria-label="Numeric construction mode" value={numericMode} onChange={event => setNumericMode(event.target.value)}>
          <option value="point">Add precise longitude / latitude point</option>
          <option value="rectangle">Rectangle between two coordinates</option>
          <option value="circle">Geodesic circle around a coordinate</option>
          <option value="bearing">Line at bearing and distance</option>
        </select>
        <div className="area-fields">
          <input aria-label="Longitude" type="number" min="-180" max="180" step="any"
            placeholder="Longitude" value={longitude} onChange={event => setLongitude(event.target.value)}/>
          <input aria-label="Latitude" type="number" min="-90" max="90" step="any"
            placeholder="Latitude" value={latitude} onChange={event => setLatitude(event.target.value)}/>
        </div>
        {numericMode === 'rectangle' && <div className="area-fields">
          <input aria-label="Opposite longitude" type="number" min="-180" max="180" step="any"
            placeholder="Opposite lon" value={endLongitude} onChange={event => setEndLongitude(event.target.value)}/>
          <input aria-label="Opposite latitude" type="number" min="-90" max="90" step="any"
            placeholder="Opposite lat" value={endLatitude} onChange={event => setEndLatitude(event.target.value)}/>
        </div>}
        {(numericMode === 'circle' || numericMode === 'bearing') && <div className="area-fields">
          <input aria-label="Radius or length in meters" type="number" min="0" max="100000" step="any"
            placeholder="Meters" value={radius} onChange={event => setRadius(event.target.value)}/>
          {numericMode === 'bearing' && <input aria-label="Bearing in degrees" type="number"
            step="any" placeholder="Bearing °" value={bearing} onChange={event => setBearing(event.target.value)}/>}
        </div>}
        <button type="submit" className="numeric-submit">Apply exact geometry</button>
      </form>
      <div className="survey-overlay">
        <div className="section-heading"><GitMerge size={14}/> Combine with saved feature</div>
        <select aria-label="Boolean operation target" value={reference}
          onChange={event => setReference(event.target.value)}>
          <option value="">Choose another feature…</option>
          {saved.filter(feature => feature.id).map(feature =>
            <option key={feature.id} value={feature.id}>{feature.name}</option>)}
        </select>
        <div className="survey-action-bar">
          <button disabled={!geometry || !reference} onClick={() => onOverlay('union',reference)}>Union</button>
          <button disabled={!geometry || !reference} onClick={() => onOverlay('difference',reference)}>Subtract</button>
          <button disabled={!geometry || !reference} onClick={() => onOverlay('intersection',reference)}>Intersect</button>
        </div>
      </div>
    </div>
  );
}
