import type {BasemapId} from './basemaps';
export type AreaUnit='auto'|'m2'|'ha'|'km2'|'mu';
export type DistanceUnit='auto'|'m'|'km';
export interface DisplaySettings{area:AreaUnit;distance:DistanceUnit;dimensions:boolean;contrast:'auto'|'light'|'dark';fill:number}
const initial:DisplaySettings={area:'auto',distance:'auto',dimensions:true,contrast:'auto',fill:.08};
export function loadDisplay():DisplaySettings{
 try{const s=JSON.parse(localStorage.getItem('geofathom-display-v2')||'{}');
 return {area:['auto','m2','ha','km2','mu'].includes(s.area)?s.area:initial.area,
 distance:['auto','m','km'].includes(s.distance)?s.distance:initial.distance,
 dimensions:typeof s.dimensions==='boolean'?s.dimensions:initial.dimensions,
 contrast:['auto','light','dark'].includes(s.contrast)?s.contrast:initial.contrast,
 fill:typeof s.fill==='number'&&Number.isFinite(s.fill)?Math.max(0,Math.min(.7,s.fill)):initial.fill};}catch{return initial;}
}
export function saveDisplay(s:DisplaySettings){try{localStorage.setItem('geofathom-display-v2',JSON.stringify(s));}catch{/* private browsing */}}
const fmt=(n:number,d=2)=>n.toLocaleString('en-US',{maximumFractionDigits:d});
export function areaText(m2:number,unit:AreaUnit='auto'){
 const u=unit==='auto'?(Math.abs(m2)>=1e6?'km2':Math.abs(m2)>=10000?'ha':'m2'):unit;
 return fmt(m2/({m2:1,ha:10000,km2:1e6,mu:2000/3}[u]),u==='km2'?4:2)+' '+({m2:'m²',ha:'ha',km2:'km²',mu:'亩'}[u]);
}
export function distanceText(m:number,unit:DistanceUnit='auto'){
 const u=unit==='auto'&&Math.abs(m)>=1000?'km':unit==='km'?'km':'m';
 return fmt(m/(u==='km'?1000:1),u==='km'?3:2)+' '+u;
}
export function mapPalette(base:BasemapId,contrast:DisplaySettings['contrast']){
 const dark=contrast==='light'||(contrast==='auto'&&['imagery','satellite','sentinel','global','custom','relief','imagerytopo'].includes(base));
 return dark?{selected:'#7affc3',draw:'#6bf1ff',halo:'#142826',text:'#ffffff',contour:'#ffd06f',major:'#fff0a7'}:
 {selected:'#006846',draw:'#006c9c',halo:'#ffffff',text:'#162c36',contour:'#91521e',major:'#652e10'};
}
