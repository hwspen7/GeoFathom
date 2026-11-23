/** Accessible, persistable sidebar split handle for every GeoFathom module. */
import {useRef,type PointerEvent as ReactPointerEvent,
        type KeyboardEvent as ReactKeyboardEvent} from 'react';
export const DOCK_LIMITS={min:200,max:540};
export function readDockWidth(key:string,fallback:number){
 try{
  const value=Number(localStorage.getItem('geofathom-dock-width:'+key));
  return Number.isFinite(value)&&value>=DOCK_LIMITS.min&&value<=DOCK_LIMITS.max
    ?value:fallback;
 }catch{return fallback;}
}
function clamp(value:number){
 return Math.round(Math.max(DOCK_LIMITS.min,Math.min(DOCK_LIMITS.max,value)));
}
export default function WorkspaceDockResizer({side,width,onChange}:{
 side:'left'|'right';width:number;onChange:(width:number)=>void;
}){
 const start=useRef<{pointer:number;x:number;width:number}|null>(null);
 const sign=side==='left'?1:-1;
 function pointerDown(event:ReactPointerEvent<HTMLDivElement>){
  if(event.button!==0)return;
  event.preventDefault();
  start.current={pointer:event.pointerId,x:event.clientX,width};
  event.currentTarget.setPointerCapture?.(event.pointerId);
 }
 function pointerMove(event:ReactPointerEvent<HTMLDivElement>){
  const old=start.current;
  if(!old||old.pointer!==event.pointerId)return;
  onChange(clamp(old.width+sign*(event.clientX-old.x)));
 }
 function pointerUp(event:ReactPointerEvent<HTMLDivElement>){
  if(start.current?.pointer!==event.pointerId)return;
  start.current=null;
  if(event.currentTarget.hasPointerCapture?.(event.pointerId))
   event.currentTarget.releasePointerCapture(event.pointerId);
 }
 function keyDown(event:ReactKeyboardEvent<HTMLDivElement>){
  if(event.key==='ArrowRight'||event.key==='ArrowLeft'){
   event.preventDefault();
   onChange(clamp(width+(event.key==='ArrowRight'?1:-1)*sign*20));
  }
  if(event.key==='Home'){event.preventDefault();onChange(DOCK_LIMITS.min);}
  if(event.key==='End'){event.preventDefault();onChange(DOCK_LIMITS.max);}
 }
 return <div role="separator" tabIndex={0}
   aria-label={side==='left'?'Resize operations':'Resize results'}
   aria-orientation="vertical"
   aria-valuemin={DOCK_LIMITS.min} aria-valuemax={DOCK_LIMITS.max}
   aria-valuenow={width} className="workspace-dock-resize"
   onPointerDown={pointerDown} onPointerMove={pointerMove}
   onPointerUp={pointerUp} onPointerCancel={pointerUp}
   onKeyDown={keyDown} title="Resize panel · ← → 20 px"/>;
}
