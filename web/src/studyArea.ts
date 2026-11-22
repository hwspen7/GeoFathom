import {terrainGeometryBounds,type TerrainBBox} from './terrainSource';

export interface StudyParcel{
 index:number;geometry:GeoJSON.Polygon;bounds:TerrainBBox;
 areaKm2:number;vertices:number;center:[number,number];
}
type Coord=[number,number];
function ringArea(ring:GeoJSON.Position[]):number{
 if(ring.length<4)return 0;
 const latitude=ring.reduce((sum,p)=>sum+p[1],0)/ring.length*Math.PI/180;
 const mx=111320*Math.cos(latitude),my=111320;
 let twice=0;
 for(let i=0;i<ring.length-1;i++){
  const [ax,ay]=ring[i],[bx,by]=ring[i+1];
  twice+=(ax*bx-ay*by)*mx*my;
 }
 return Math.abs(twice)/2;
}
function area(polygon:GeoJSON.Position[][]):number{
 return Math.max(0,(ringArea(polygon[0]??[])-polygon.slice(1).reduce((sum,hole)=>sum+ringArea(hole),0))/1e6);
}
/** Separate components without altering source geometry or fabricating a campus outline. */
export function studyParcels(geometry:GeoJSON.Geometry|null):StudyParcel[]{
 if(!geometry||(geometry.type!=='Polygon'&&geometry.type!=='MultiPolygon'))return [];
 const polygons:GeoJSON.Position[][][]=geometry.type==='Polygon'?[geometry.coordinates]:geometry.coordinates;
 return polygons.flatMap((rings,index)=>{
  const polygon:GeoJSON.Polygon={type:'Polygon',coordinates:structuredClone(rings)};
  const bounds=terrainGeometryBounds(polygon);
  if(!bounds)return [];
  const [w,s,e,n]=bounds;
  return [{index,geometry:polygon,bounds,areaKm2:area(rings),
   vertices:rings.reduce((sum,ring)=>sum+Math.max(0,ring.length-1),0),
   center:[(w+e)/2,(s+n)/2] as Coord}];
 });
}
function inside(point:Coord,ring:GeoJSON.Position[]):boolean{
 let inRing=false;const [lon,lat]=point;
 for(let i=0,j=ring.length-1;i<ring.length;j=i++){
  const a=ring[i],b=ring[j];
  if(((a[1]>lat)!==(b[1]>lat)) &&
    lon<(b[0]-a[0])*(lat-a[1])/(b[1]-a[1])+a[0])inRing=!inRing;
 }
 return inRing;
}
function contains(point:Coord,rings:GeoJSON.Position[][]):boolean{
 return !!rings.length&&inside(point,rings[0])&&!rings.slice(1).some(hole=>inside(point,hole));
}
/** Prefer parcel containing place reference, or closest spatial parcel, not the
 * widest multipolygon bounding box that may include unrelated distant sites. */
export function suggestedParcel(geometry:GeoJSON.Geometry|null,point:Coord):number|null{
 const parcels=studyParcels(geometry);
 if(!parcels.length)return null;
 if(!point.every(Number.isFinite))return parcels.reduce((best,p)=>p.areaKm2>best.areaKm2?p:best).index;
 const containing=parcels.find(p=>contains(point,p.geometry.coordinates));
 if(containing)return containing.index;
 let best:StudyParcel=parcels[0],distance=Infinity;
 for(const p of parcels){
  const [w,s,e,n]=p.bounds;
  const dx=Math.max(w-point[0],0,point[0]-e)*Math.cos(point[1]*Math.PI/180);
  const dy=Math.max(s-point[1],0,point[1]-n);
  const d=dx*dx+dy*dy;
  if(d<distance){distance=d;best=p;}
 }
 return best.index;
}
/** The original multipolygon remains available for explicit full-boundary use. */
export function parcelAt(geometry:GeoJSON.Geometry,index:number|'all'):GeoJSON.Geometry|null{
 if(!geometry)return null;
 if(index==='all')return structuredClone(geometry);
 return studyParcels(geometry).find(p=>p.index===index)?.geometry??null;
}
