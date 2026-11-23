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
 let w=Infinity,s=Infinity,e=-Infinity,n=-Infinity;
 // Avoid spreading an unbounded number of GPS vertices onto the JS call stack.
 for(const [lon,lat] of positions){w=Math.min(w,lon);s=Math.min(s,lat);e=Math.max(e,lon);n=Math.max(n,lat);}
 const bounds:TerrainBBox=[w,s,e,n];
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
export const MAX_DEM_GRID_CELLS=8_000_000;
export const MAX_DEM_GRID_SIDE=4096;
export const DEM_RESOLUTIONS=[1,3,10,30,90] as const;
export type DEMResolution=typeof DEM_RESOLUTIONS[number];
/** The 1/3/10 m presets request USGS 3DEP; that service is not worldwide. */
export function terrainSupportsUSGS(bounds:TerrainBBox|null):boolean{
 if(!validBounds(bounds))return false;
 const [w,s,e,n]=bounds;
 return w>=-180&&e<=-60&&s>=17&&n<=72;
}
export function availableDEMResolutions(bounds:TerrainBBox|null):DEMResolution[]{
 return terrainSupportsUSGS(bounds)?[1,3,10,30,90]:[30,90];
}
export interface FetchBudget {approximateCells:number;estimatedWidth:number;estimatedHeight:number;warning:string|null}
/** Approximate display estimate. Backend validates the exact UTM pixel grid. */
export function terrainFetchBudget(bounds:TerrainBBox|null,resolution:number):FetchBudget|null{
 if(!validBounds(bounds)||!Number.isFinite(resolution)||!DEM_RESOLUTIONS.some(r=>r===resolution))return null;
 const [w,s,e,n]=bounds,mid=(s+n)*Math.PI/360;
 const width=Math.max(5,Math.ceil(((e-w)*111320*Math.cos(mid))/resolution)+8);
 const height=Math.max(5,Math.ceil(((n-s)*111320)/resolution)+8);
 const cells=width*height;
 const warning=e-w>.25||n-s>.25?'Area exceeds the 0.25° single-fetch extent. Divide into smaller study areas.':
   resolution<30&&!terrainSupportsUSGS(bounds)?'USGS 3DEP does not cover this location. Use Copernicus GLO-30/GLO-90 or import a local high-resolution DEM.':
   width>MAX_DEM_GRID_SIDE||height>MAX_DEM_GRID_SIDE||cells>MAX_DEM_GRID_CELLS?
   'Estimated grid exceeds the bounded 8-million-cell / 4096-pixel-side budget. Use Auto resolution, or divide the study area.':null;
 return {approximateCells:cells,estimatedWidth:width,estimatedHeight:height,warning};
}
/** Find the finest actually supported REQUEST grid fitting resource constraints.
 * Output spacing never implies the upstream DEM has the same native accuracy. */
export function recommendDEMResolution(bounds:TerrainBBox|null):DEMResolution|null{
 if(!validBounds(bounds))return null;
 for(const r of availableDEMResolutions(bounds)){
  if(terrainFetchBudget(bounds,r)?.warning===null)return r;
 }
 return null;
}
export function terrainRasterMatchesTarget(asset:Pick<RasterAsset,'bbox'>,target:TerrainBBox){
 if(!validBounds(asset.bbox)||!validBounds(target))return false;
 // The entire request must lie inside the returned georeferenced footprint.
 return target[0]>=asset.bbox[0]-1e-5&&target[1]>=asset.bbox[1]-1e-5 &&
        target[2]<=asset.bbox[2]+1e-5&&target[3]<=asset.bbox[3]+1e-5;
}
export function describeTerrainBounds(bounds:TerrainBBox):string{
 const [w,s,e,n]=bounds;
 return `W ${w.toFixed(5)}° · S ${s.toFixed(5)}° · E ${e.toFixed(5)}° · N ${n.toFixed(5)}°`;
}

/** A selected real area is the intended DEM request by default.
 * A geocoded point has no area and therefore uses the current map view. */
export function preferredTerrainFetchScope(geometry:GeoJSON.Geometry|null):FetchScope{
 return geometry&&['Polygon','MultiPolygon'].includes(geometry.type)?'selection':'viewport';
}

/** A broad old DEM may geometrically cover a chosen campus parcel while
 * obscuring it with miles of irrelevant imagery. Hide, but retain, that DEM. */
export function terrainRasterFitsStudyArea(asset:Pick<RasterAsset,'bbox'>,target:TerrainBBox,maxExcess=2.5):boolean{
 if(!terrainRasterMatchesTarget(asset,target))return false;
 const a=asset.bbox,b=(a[2]-a[0])*(a[3]-a[1]);
 const c=(target[2]-target[0])*(target[3]-target[1]);
 return Number.isFinite(b)&&c>0&&b/c<=maxExcess;
}
