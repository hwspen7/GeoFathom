import {useEffect,useMemo,useState} from 'react';
import {verticesOf,type GeometryPath,type Position} from './editing';
import {studyParcels} from './studyArea';
import type {Place} from './api';

interface Props{
 geometry:GeoJSON.Geometry|null;
 sourcePlace:Place|null;
 selectedParcel:number|'all';
 onChooseParcel:(index:number|'all')=>void;
 editing:boolean;
 busy:boolean;
 selectedNode:GeometryPath|null;
 onSelectNode:(path:GeometryPath)=>void;
 onToggleEditing:()=>void;
 onMoveNode:(path:GeometryPath,coordinate:Position)=>void;
 onRemoveNode:(path:GeometryPath)=>void;
}
const same=(a:GeometryPath,b:GeometryPath)=>a.polygon===b.polygon&&a.ring===b.ring&&a.vertex===b.vertex;
const format=(n:number)=>n.toFixed(7);
export default function BoundaryEditor(p:Props){
 const nodes=useMemo(()=>p.geometry?verticesOf(p.geometry).filter(node=>!node.midpoint):[],[p.geometry]);
 const active=nodes.find(node=>p.selectedNode&&same(node.path,p.selectedNode))??nodes[0];
 const parcelOptions=useMemo(()=>studyParcels(p.sourcePlace?.geometry??null),[p.sourcePlace?.geometry]);
 const [lon,setLon]=useState(''),[lat,setLat]=useState('');
 useEffect(()=>{
   setLon(active?format(active.point[0]):'');
   setLat(active?format(active.point[1]):'');
 },[active?.point[0],active?.point[1],active?.path.polygon,active?.path.ring,active?.path.vertex]);
 if(!p.geometry||!nodes.length)return null;
 const value=Number(lon),latitude=Number(lat);
 const valid=lon.trim()!==''&&lat.trim()!==''&&Number.isFinite(value)&&Number.isFinite(latitude)&&
             value>=-180&&value<=180&&latitude>=-85&&latitude<=85;
 const unchanged=!!active&&value===active.point[0]&&latitude===active.point[1];
 return <section className="boundary-inspector" aria-label="Boundary vertices">
   <div className="section-heading">
     <span>Boundary · {nodes.length.toLocaleString()} nodes</span>
   </div>
   {parcelOptions.length>1&&<label>Study area parcel
     <select aria-label="Study area parcel" value={String(p.selectedParcel)}
       disabled={p.busy} onChange={e=>p.onChooseParcel(e.target.value==='all'?'all':Number(e.target.value))}>
       <option value="all">All mapped parcels ({parcelOptions.length})</option>
       {parcelOptions.map(parcel=><option key={parcel.index} value={String(parcel.index)}>
         Parcel {parcel.index+1} · {parcel.areaKm2.toFixed(3)} km² · {parcel.vertices} nodes
       </option>)}
     </select>
   </label>}
   {parcelOptions.length>1&&<small className="compact-notice">
     Separated campus sites are retained in the original mapped boundary. Only the chosen parcel is used for new DEM requests.
   </small>}
   <div className="survey-action-bar">
     <button aria-label="Edit boundary nodes" aria-pressed={p.editing} disabled={p.busy}
       onClick={p.onToggleEditing}>{p.editing?'Finish editing':'Edit boundary nodes'}</button>
   </div>
   <small className="compact-notice">Select a boundary dot to inspect its WGS84 coordinates.
     {p.editing?' Drag white nodes; drag blue midpoints to insert.':''}</small>
   <details className="boundary-node-detail" open={p.editing||p.selectedNode!==null}>
     <summary>Node coordinates</summary>
     {active&&<>
       <label>Node
         <select aria-label="Boundary node" value={nodes.findIndex(node=>same(node.path,active.path))}
           onChange={e=>{const node=nodes[Number(e.target.value)];if(node)p.onSelectNode(node.path);}}>
           {nodes.map((node,i)=><option key={i} value={i}>#{i+1} · P{node.path.polygon+1}/R{node.path.ring+1}/V{node.path.vertex+1}</option>)}
         </select>
       </label>
       <div className="area-fields">
         <label>Longitude
           <input type="number" aria-label="Boundary longitude" step="any" min="-180" max="180"
             value={lon} onChange={e=>setLon(e.target.value)}/>
         </label>
         <label>Latitude
           <input type="number" aria-label="Boundary latitude" step="any" min="-85" max="85"
             value={lat} onChange={e=>setLat(e.target.value)}/>
         </label>
       </div>
       <div className="survey-action-bar">
         <button disabled={p.busy||!valid||unchanged}
           onClick={()=>{if(valid)p.onMoveNode(active.path,[value,latitude]);}}>Apply coordinates</button>
         <button disabled={p.busy||!p.editing||nodes.length<4} aria-label="Remove boundary node"
           title="Remove only this vertex after geometry validation"
           onClick={()=>p.onRemoveNode(active.path)}>Remove node</button>
       </div>
     </>}
   </details>
 </section>;
}
