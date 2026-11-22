import type {Place} from './api';

/** User-retained search locations are independent of the transient active edit tool. */
export const PIN_LIMIT=16;
const KEY='geofathom-pinned-places-v1';
const storageKey=(scope:string|null)=>KEY+':'+(scope??'local');
export function visibleGeometry(place:Place):GeoJSON.Geometry{
  const g=place.geometry;
  return g&&['Polygon','MultiPolygon','LineString','MultiLineString','Point'].includes(g.type)?
    g:{type:'Point',coordinates:[place.longitude,place.latitude]};
}
function validPlace(value:unknown):value is Place{
  if(!value||typeof value!=='object')return false;
  const p=value as Partial<Place>;
  return typeof p.id==='string'&&p.id.length<=160&&typeof p.name==='string'&&
    Number.isFinite(p.longitude)&&Number.isFinite(p.latitude)&&
    Math.abs(p.longitude!)<=180&&Math.abs(p.latitude!)<=85&&
    (!p.geometry||typeof p.geometry.type==='string');
}
export function readPinnedPlaces(scope:string|null):Place[]{
  try{
    const raw:unknown=JSON.parse(localStorage.getItem(storageKey(scope))||'[]');
    return Array.isArray(raw)?raw.filter(validPlace).slice(0,PIN_LIMIT):[];
  }catch{return [];}
}
export function writePinnedPlaces(scope:string|null,places:Place[]):boolean{
  try{localStorage.setItem(storageKey(scope),JSON.stringify(places.slice(0,PIN_LIMIT)));return true;}
  catch{return false;}
}
export function pinPlace(places:Place[],place:Place):Place[]{
  return [place,...places.filter(p=>p.id!==place.id)].slice(0,PIN_LIMIT);
}
export function unpinPlace(places:Place[],id:string):Place[]{
  return places.filter(p=>p.id!==id);
}
