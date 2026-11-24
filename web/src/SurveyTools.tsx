import { useState, type FormEvent } from 'react';
import {createPortal} from 'react-dom';
import {
  Check, Circle, Copy, CornerDownRight, Eraser, GitMerge, MousePointer2,
  Pencil, Redo2, Ruler, Scissors, Undo2, X,
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
  linked: boolean;
  toolbarTarget?: HTMLElement|null;
  edgeMoving?:boolean;
  onEdgeMove?:(active:boolean)=>void;
  busy?:boolean;
  locked?:boolean;
  onLinked: (enabled:boolean) => void;
  sketchError?:string|null;
}

const buttonModes: Array<{ mode: Exclude<ShapeMode, null>; title: string }> = [
  { mode: 'point', title: 'Point' },
  { mode: 'polygon', title: 'Polygon' },
  { mode: 'line', title: 'Line' },
  { mode: 'rectangle', title: 'Rectangle' },
  { mode: 'circle', title: 'Circle' },
  { mode: 'hole', title: 'Cut hole' },
  { mode: 'split', title: 'Split line' },
  { mode: 'trace-along', title: 'Trace network' },
];

export default function SurveyTools({
  mode, geometry, points, editing, moving, snapping, canUndo, canRedo, saved,
  onStart, onFinish, onCancel, onUndoPoint, onUndo, onRedo, onEdit,
  onSnapping, onAddPoint, onNumeric, onOverlay, onDuplicate, linked, onLinked,
  toolbarTarget,busy=false,locked=false,edgeMoving=false,onEdgeMove,sketchError,
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
      if(mode)onAddPoint(first);
      else onNumeric('point',{vertices:[first]});
      return;
    }
    if(numericMode==='rectangle'&&(!endLongitude||!endLatitude))return;
    const second: Position = [Number(endLongitude), Number(endLatitude)];
    onNumeric(numericMode, {
      vertices: numericMode === 'rectangle' ? [first, second] : [first],
      radius_m: Number(radius),
      bearing_deg: Number(bearing), length_m: Number(radius),
    });
  }

  const traceReady=saved.some(feature=>
    feature.geometry?.type==='LineString'||feature.geometry?.type==='MultiLineString');
  const modeName=buttonModes.find(item=>item.mode===mode)?.title;
  const toolbar=<div className={'survey-command-bar'+(mode?' is-drawing':'')}>
      <div className="survey-mode-grid" role="group" aria-label="Draw and reshape tools">
        <div className="survey-mode-family survey-primary-modes" role="group" aria-label="Drawing tools">
          {buttonModes.slice(0,5).map(item => (
          <button key={item.mode} className={mode === item.mode ? 'active' : ''}
            aria-label={item.title}
            title={item.mode==='trace-along'&&!traceReady?
              'Save a vector line in the active project before tracing.':
              ['hole','split'].includes(item.mode)&&(!geometry||!['Polygon','MultiPolygon'].includes(geometry.type))?
                'Select an editable polygon first.':
                'Draw '+item.title.toLowerCase()+
                (({point:' (P)',polygon:' (G)',line:' (L)',rectangle:' (R)',circle:' (C)'} as Partial<Record<Exclude<ShapeMode,null>,string>>)[item.mode]??'')}
            aria-pressed={mode===item.mode} onClick={() => mode===item.mode?onCancel():onStart(item.mode)}
            disabled={(busy&&mode!==item.mode)||(item.mode==='trace-along'&&!traceReady)||
              (['hole','split'].includes(item.mode)&&
                (locked||(geometry?.type!=='Polygon'&&geometry?.type!=='MultiPolygon')))}>
            {item.mode === 'circle' ? <Circle size={15}/> :
             item.mode === 'line' ? <Ruler size={15}/> :
             item.mode === 'split' || item.mode === 'trace-along' ? <Scissors size={15}/> :
             item.mode === 'hole' ? <Eraser size={15}/> : <Pencil size={15}/>}
            <span className="survey-button-caption">{item.title}</span>
          </button>
        ))}
        </div>
        <div className="survey-mode-family survey-topology-tools" role="group" aria-label="Topology tools">
          {buttonModes.slice(5).map(item => (
          <button key={item.mode} className={mode === item.mode ? 'active' : ''}
            aria-label={item.title}
            title={item.mode==='trace-along'&&!traceReady?
              'Save a vector line in the active project before tracing.':
              ['hole','split'].includes(item.mode)&&(!geometry||!['Polygon','MultiPolygon'].includes(geometry.type))?
                'Select an editable polygon first.':
                'Draw '+item.title.toLowerCase()+
                (({point:' (P)',polygon:' (G)',line:' (L)',rectangle:' (R)',circle:' (C)'} as Partial<Record<Exclude<ShapeMode,null>,string>>)[item.mode]??'')}
            aria-pressed={mode===item.mode} onClick={() => mode===item.mode?onCancel():onStart(item.mode)}
            disabled={(busy&&mode!==item.mode)||(item.mode==='trace-along'&&!traceReady)||
              (['hole','split'].includes(item.mode)&&
                (locked||(geometry?.type!=='Polygon'&&geometry?.type!=='MultiPolygon')))}>
            {item.mode === 'circle' ? <Circle size={15}/> :
             item.mode === 'line' ? <Ruler size={15}/> :
             item.mode === 'split' || item.mode === 'trace-along' ? <Scissors size={15}/> :
             item.mode === 'hole' ? <Eraser size={15}/> : <Pencil size={15}/>}
            <span className="survey-button-caption">{item.title}</span>
          </button>
        ))}
        </div>
      </div>
      {mode && (
        <div className="survey-action-bar survey-sketch-session" role="group" aria-label="Active drawing">
          <strong>{modeName}</strong><span>{points.length} pts</span>
          <button title="Undo last sketch point (Backspace)" aria-label="Undo last sketch point"
            disabled={!points.length||busy} onClick={onUndoPoint}><Undo2 size={14}/> Undo point</button>
          <button title="Cancel" aria-label="Cancel drawing" className="survey-cancel-button" onClick={onCancel}><X size={14}/> Cancel <kbd>Esc</kbd></button>
          <button className="finish-button" aria-label="Finish" title="Finish (Enter / F2; double-click, right-click, or click the first polygon vertex)"
            disabled={busy||points.length<(mode==='point'?1:['polygon','hole'].includes(mode)?3:2)}
            onClick={onFinish}><Check size={14}/> Finish <kbd>Enter</kbd></button>
        </div>
      )}
      {mode&&<div className={'survey-sketch-feedback'+(sketchError?' has-error':'')} role={sketchError?'alert':'status'}>
        {sketchError??(busy?'Validating geometry… Cancel remains available.':
          mode==='hole'?'Draw a closed ring inside the selected polygon. Enter finishes · Esc cancels.':
          mode==='split'?'Draw across the selected polygon. Enter finishes · Esc cancels.':
          'Enter finishes · Esc cancels · click the active tool again to exit.')}
      </div>}
      {!mode&&<div className="survey-idle-actions">
      <div className="survey-action-bar" role="group" aria-label="Edit selected object">
        {editing&&<button className="finish-button" aria-label="Finish geometry editing"
          title="Finish geometry editing (Enter / Esc)" onClick={()=>onEdit(false,false)}><Check size={14}/> Done editing</button>}
        <button title="Edit vertices (E)" disabled={!geometry||locked||busy||Boolean(mode)} className={editing && !moving && !edgeMoving ? 'active' : ''}
          onClick={() => onEdit(!editing || moving || edgeMoving, false)}><Pencil size={14}/> Vertices</button>
        <button title="Move whole shape (M)" disabled={!geometry||locked||busy||Boolean(mode)} className={moving ? 'active' : ''}
          onClick={() => onEdit(!moving, !moving)}><MousePointer2 size={14}/> Move</button>
        {onEdgeMove&&<button title="Drag a segment midpoint to move both endpoints (B)" disabled={!geometry||locked||busy||Boolean(mode)||geometry.type==='Point'} className={edgeMoving?'active':''}
          onClick={()=>onEdgeMove(!edgeMoving)}><Ruler size={14}/> Edge</button>}
        <button title="Snap to nearby vertices" className={snapping ? 'active' : ''}
          onClick={() => onSnapping(!snapping)}>Snap {snapping ? 'ON' : 'OFF'}</button>
      </div>
      <div className="survey-action-bar">
        <button disabled={!canUndo||busy} onClick={onUndo}><Undo2 size={14}/> Undo</button>
        <button disabled={!canRedo||busy} onClick={onRedo}><Redo2 size={14}/> Redo</button>
        <button disabled={!geometry||busy||Boolean(mode)} onClick={onDuplicate}><Copy size={14}/> Copy</button>
      </div>
      </div>}
    </div>;
  return (
    <div className="survey-tools">
      {toolbarTarget?createPortal(toolbar,toolbarTarget):toolbar}
      <p className="survey-workflow-hint">Choose a drawing tool above, or select an object to edit it. Finish with Enter; cancel with Esc.</p>
      <details className="survey-options">
      <summary>Vertex editing options</summary>
      <label className="linked-vertex-toggle">
        <input type="checkbox" checked={linked} onChange={e=>onLinked(e.target.checked)} />
        Linked/shared vertices (preview neighboring feature edits)
      </label>
      <p className="project-hint">Drag white corner handles to reshape. Drag blue midpoints to insert. Right-click a corner to remove it. Use Move to drag the whole feature.</p>
      </details>
      <details className="survey-options">
      <summary>Exact coordinates and construction</summary>
      <form className="survey-numeric" onSubmit={numeric}>
        <div className="section-heading"><CornerDownRight size={14}/> Construct geometry</div>
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
        <button type="submit" className="numeric-submit"
          disabled={Boolean(mode)&&numericMode!=='point'}
          title={mode&&numericMode!=='point'?'Finish or cancel the active sketch first.':'Create exact geometry'}>
          {mode&&numericMode==='point'?'Add precise vertex':'Apply exact geometry'}
        </button>
      </form>
      </details>
      <details className="survey-options">
      <summary>Combine with saved feature</summary>
      <div className="survey-overlay">
        <div className="section-heading"><GitMerge size={14}/> Boolean operations</div>
        <select aria-label="Boolean operation target" value={reference}
          onChange={event => setReference(event.target.value)}>
          <option value="">Choose another feature…</option>
          {saved.filter(feature => feature.id).map(feature =>
            <option key={feature.id} value={feature.id}>{feature.name}</option>)}
        </select>
        <div className="survey-action-bar">
          <button disabled={!geometry || !reference||Boolean(mode)||busy} onClick={() => onOverlay('union',reference)}>Union</button>
          <button disabled={!geometry || !reference||Boolean(mode)||busy} onClick={() => onOverlay('difference',reference)}>Subtract</button>
          <button disabled={!geometry || !reference||Boolean(mode)||busy} onClick={() => onOverlay('intersection',reference)}>Intersect</button>
        </div>
      </div>
      </details>
    </div>
  );
}
