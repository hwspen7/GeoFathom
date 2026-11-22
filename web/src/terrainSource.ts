import type {RasterAsset} from './api';

export type TerrainBBox=[number,number,number,number];
export type FetchScope='viewport'|'selection';
export function validBounds(box:TerrainBBox|null):box is TerrainBBox{
 if(!box)return false;
 const [w,s,e,n]=box;
 return box.every(Number.isFinite)&&w>=-180&&e<=180&&s>=-79&&n<=83&&w<e&&s<n;
}
/** Return bounds only for actual selectable line/polygon geometries, never points. */
export function terrainGeometryBounds(geometry:GeoJSON.Geometry|null):TerrainBBox|null{
 if(!geometry)return null;
 const positions:GeoJSON.Position[]=
   geometry.type==='LineString'?geometry.coordinates:
   geometry.type==='Polygon'?geometry.coordinates.flat():
   geometry.type==='MultiPolygon'?geometry.coordinates.flat(2):[];
 if(!positions.length||positions.some(p=>!Number.isFinite(p[0])||!Number.isFinite(p[1])))return null;
 const x=positions.map(p=>p[0]),y=positions.map(p=>p[1]);
 const bounds:TerrainBBox=[Math.min(...x),Math.min(...y),Math.max(...x),Math.max(...y)];
 // Line segments may be horizontal or vertical; preserve a valid fetch extent.
 return bounds.every(Number.isFinite)?bounds:null;
}
/** Fetching visible map data is the default; a selected feature is never implicit. */
export function terrainFetchBounds(viewport:TerrainBBox|null,geometry:GeoJSON.Geometry|null,scope:FetchScope):TerrainBBox|null{
 if(scope==='viewport')return validBounds(viewport)?viewport:null;
 const selected=terrainGeometryBounds(geometry);if(!selected)return null;
 const [w,s,e,n]=selected,pad=.0004;
 const bbox:TerrainBBox=[w-pad,s-pad,e+pad,n+pad];
 return validBounds(bbox)?bbox:null;
}
export function terrainBoundsOverlap(a:TerrainBBox,b:TerrainBBox):boolean{
 return Math.max(a[0],b[0])<Math.min(a[2],b[2]) &&
        Math.max(a[1],b[1])<Math.min(a[3],b[3]);
}
export function terrainContainsCenter(bounds:TerrainBBox,reference:TerrainBBox):boolean{
 const x=(reference[0]+reference[2])/2,y=(reference[1]+reference[3])/2;
 // Allow a tiny numerical tolerance around projected raster footprints.
 return x>=bounds[0]-1e-5&&x<=bounds[2]+1e-5&&y>=bounds[1]-1e-5&&y<=bounds[3]+1e-5;
}
export interface FetchBudget {approximateCells:number;estimatedWidth:number;estimatedHeight:number;warning:string|null}
/** Informative local estimate; the server validates exact UTM grid dimensions. */
export function terrainFetchBudget(bounds:TerrainBBox|null,resolution:number):FetchBudget|null{
 if(!validBounds(bounds)||!Number.isFinite(resolution)||resolution<=0)return null;
 const [w,s,e,n]=bounds,mid=(s+n)*Math.PI/360;
 const width=Math.ceil(((e-w)*111320*Math.cos(mid))/resolution)+8;
 const height=Math.ceil(((n-s)*111320)/resolution)+8;
 const cells=width*height;
 const warning=e-w>.25||n-s>.25?'Area exceeds 0.25° fetch limit. Zoom in or draw a smaller selection.':
   width>1024||height>1024||cells>1000000?'Estimated grid exceeds the 1-million-cell budget. Choose a coarser resolution or smaller area.':null;
 return {approximateCells:cells,estimatedWidth:width,estimatedHeight:height,warning};
}
export function terrainRasterMatchesTarget(asset:Pick<RasterAsset,'bbox'>,target:TerrainBBox){
 return validBounds(asset.bbox)&&terrainContainsCenter(asset.bbox,target);
}
export function describeTerrainBounds(bounds:TerrainBBox):string{
 const [w,s,e,n]=bounds;
 return `W ${w.toFixed(5)}° · S ${s.toFixed(5)}° · E ${e.toFixed(5)}° · N ${n.toFixed(5)}°`;
}
