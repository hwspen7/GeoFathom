import {SectionIcon} from './SectionIcon';
import { useState, type FormEvent } from 'react';
import {createPortal} from 'react-dom';
import {
  Check, Circle, Copy, Eraser, MapPin, Minus, MousePointer2,
  Pencil, Pentagon, Redo2, Route, Ruler, Scissors, Split, Square, Undo2, X, type LucideIcon,
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
  cuttingEdge?:boolean;
  onCutEdge?:()=>void;
}

// Keep the accessible operation names stable while giving each compact tool
// a distinct icon, a one-word caption, and a short hover description.
const buttonModes: Array<{
  mode: Exclude<ShapeMode, null>; title: string; caption: string;
  hint: string; icon: LucideIcon;
}> = [
  { mode: 'point', title: 'Point', caption: 'Point', hint: 'Draw point (P)', icon: MapPin },
  { mode: 'polygon', title: 'Polygon', caption: 'Polygon', hint: 'Draw polygon (G)', icon: Pentagon },
  { mode: 'line', title: 'Line', caption: 'Line', hint: 'Draw line (L)', icon: Minus },
  { mode: 'rectangle', title: 'Rectangle', caption: 'Rectangle', hint: 'Draw rectangle (R)', icon: Square },
  { mode: 'circle', title: 'Circle', caption: 'Circle', hint: 'Draw circle (C)', icon: Circle },
  { mode: 'hole', title: 'Cut hole', caption: 'Hole', hint: 'Cut polygon hole', icon: Eraser },
  { mode: 'split', title: 'Split line', caption: 'Split', hint: 'Split polygon by line', icon: Split },
  { mode: 'trace-along', title: 'Trace network', caption: 'Trace', hint: 'Trace saved network', icon: Route },
];

export default function SurveyTools({
  mode, geometry, points, editing, moving, snapping, canUndo, canRedo, saved,
  onStart, onFinish, onCancel, onUndoPoint, onUndo, onRedo, onEdit,
  onSnapping, onAddPoint, onNumeric, onOverlay, onDuplicate, linked, onLinked,
  toolbarTarget,busy=false,locked=false,edgeMoving=false,onEdgeMove,sketchError,cuttingEdge=false,onCutEdge,
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
  const modeName=buttonModes.find(item=>item.mode===mode)?.caption;
  const polygonReady=geometry?.type==='Polygon'||geometry?.type==='MultiPolygon';
  function renderMode(item:typeof buttonModes[number]){
    const polygonOnly=item.mode==='hole'||item.mode==='split';
    const blocked=busy&&mode!==item.mode?'Wait for current operation':
      item.mode==='trace-along'&&!traceReady?'Save a vector line first':
      polygonOnly&&locked?'Unlock the selected layer':
      polygonOnly&&!polygonReady?'Select a polygon first':null;
    const hint=blocked??item.hint;
    const Icon=item.icon;
    // A wrapper also exposes the explanation when the native button is disabled.
    return <span className="survey-mode-item" key={item.mode} title={hint}>
      <button type="button" className={mode===item.mode?'active':''}
        aria-label={item.title} title={hint} aria-pressed={mode===item.mode}
        onClick={()=>mode===item.mode?onCancel():onStart(item.mode)}
        disabled={blocked!==null}>
        <Icon size={15} aria-hidden="true"/>
        <span className="survey-button-caption">{item.caption}</span>
      </button>
    </span>;
  }
  const toolbar=<div className={'survey-command-bar'+(mode?' is-drawing':'')}>
      <div className="survey-mode-grid" role="group" aria-label="Draw and reshape tools">
        <div className="survey-mode-family survey-primary-modes" role="group" aria-label="Drawing tools">
          {buttonModes.slice(0,5).map(renderMode)}
        </div>
        <div className="survey-mode-family survey-topology-tools" role="group" aria-label="Topology tools">
          {renderMode(buttonModes[5])}
          {onCutEdge&&<span className="survey-mode-item" title="Cut segment between two vertices"><button type="button" aria-label="Cut edge" title="Cut segment between two vertices" aria-pressed={cuttingEdge} className={cuttingEdge?'active':''} disabled={busy||locked||Boolean(mode)||!geometry||!['LineString','MultiLineString','Polygon','MultiPolygon'].includes(geometry.type)} onClick={onCutEdge}><Scissors size={15} aria-hidden="true"/><span className="survey-button-caption">Cut</span></button></span>}
          {buttonModes.slice(6).map(renderMode)}
        </div>
      </div>
      {mode && (
        <div className="survey-action-bar survey-sketch-session" role="group" aria-label="Active drawing">
          <strong>{modeName}</strong><span>{points.length} pts</span>
          <button title="Undo last sketch point (Backspace)" aria-label="Undo last sketch point"
            disabled={!points.length||busy} onClick={onUndoPoint}><Undo2 size={14}/> Undo</button>
          <button title="Cancel" aria-label="Cancel drawing" className="survey-cancel-button" onClick={onCancel}><X size={14}/> Cancel <kbd>Esc</kbd></button>
          <button className="finish-button" aria-label="Finish" title="Finish drawing (Enter / F2)"
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
          title="Finish geometry editing (Enter / Esc)" onClick={()=>onEdit(false,false)}><Check size={14}/> Done</button>}
        <button title="Edit vertices (E)" disabled={!geometry||locked||busy||Boolean(mode)} className={editing && !moving && !edgeMoving ? 'active' : ''}
          onClick={() => onEdit(!editing || moving || edgeMoving, false)}><Pencil size={14}/> Vertices</button>
        <button title="Move whole shape (M)" disabled={!geometry||locked||busy||Boolean(mode)} className={moving ? 'active' : ''}
          onClick={() => onEdit(!moving, !moving)}><MousePointer2 size={14}/> Move</button>
        {onEdgeMove&&<button title="Move segment endpoints (B)" disabled={!geometry||locked||busy||Boolean(mode)||geometry.type==='Point'} className={edgeMoving?'active':''}
          onClick={()=>onEdgeMove(!edgeMoving)}><Ruler size={14}/> Edge</button>}
        <button title={snapping?'Disable vertex snapping (S)':'Enable vertex snapping (S)'}
          aria-label={snapping?'Snap ON':'Snap OFF'} aria-pressed={snapping}
          className={snapping ? 'active' : ''}
          onClick={() => onSnapping(!snapping)}>Snap</button>
      </div>
      <div className="survey-action-bar">
        <button title="Undo last edit" disabled={!canUndo||busy} onClick={onUndo}><Undo2 size={14}/> Undo</button>
        <button title="Redo last edit" disabled={!canRedo||busy} onClick={onRedo}><Redo2 size={14}/> Redo</button>
        <button title="Duplicate selected geometry" disabled={!geometry||busy||Boolean(mode)} onClick={onDuplicate}><Copy size={14}/> Copy</button>
      </div>
      </div>}
    </div>;
  return (
    <div className="survey-tools">
      {toolbarTarget?createPortal(toolbar,toolbarTarget):toolbar}
      {/* Keep high-frequency survey controls visible, like GIS tools. */}
      <section className="survey-flat-group" aria-label="Vertex editing options">
      <h3 className="survey-flat-heading" title="Drag vertices to reshape, midpoints to insert, or right-click a vertex to remove it."><SectionIcon role="vertices" size={13}/> Vertices</h3>
      <label className="linked-vertex-toggle">
        <input type="checkbox" checked={linked} onChange={e=>onLinked(e.target.checked)} />
        <span title="Preview neighboring feature edits">Linked/shared vertices</span>
      </label>
      </section>
      <section className="survey-flat-group" aria-label="Exact coordinates and construction">
      <h3 className="survey-flat-heading"><SectionIcon role="construction" size={13}/> Construction</h3>
      <form className="survey-numeric" onSubmit={numeric}>
        <select aria-label="Numeric construction mode" value={numericMode} onChange={event => setNumericMode(event.target.value)}>
          <option value="point">Point</option>
          <option value="rectangle">Rectangle</option>
          <option value="circle">Geodesic circle</option>
          <option value="bearing">Bearing / distance</option>
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
      </section>
      <section className="survey-flat-group" aria-label="Combine with saved feature">
      <h3 className="survey-flat-heading"><SectionIcon role="boolean" size={13}/> Boolean operations</h3>
      <div className="survey-overlay">
        <select aria-label="Boolean operation target" value={reference}
          onChange={event => setReference(event.target.value)}>
          <option value="">Select feature</option>
          {saved.filter(feature => feature.id).map(feature =>
            <option key={feature.id} value={feature.id}>{feature.name}</option>)}
        </select>
        <div className="survey-action-bar">
          <button disabled={!geometry || !reference||Boolean(mode)||busy} onClick={() => onOverlay('union',reference)}>Union</button>
          <button disabled={!geometry || !reference||Boolean(mode)||busy} onClick={() => onOverlay('difference',reference)}>Subtract</button>
          <button disabled={!geometry || !reference||Boolean(mode)||busy} onClick={() => onOverlay('intersection',reference)}>Intersect</button>
        </div>
      </div>
      </section>
    </div>
  );
}
