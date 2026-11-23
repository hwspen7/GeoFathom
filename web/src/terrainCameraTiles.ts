/** Camera-derived, bounded DEM tile priorities. Pure for regression tests. */
import type {TerrainMesh,StreamedTerrainTile} from './api';

export interface TerrainCamera {
 angle:number;tilt:number;zoom:number;panX:number;panY:number;clip:number;
}
export interface TerrainTileRequest {level:1|2|4|8;tile_row:number;tile_col:number;priority:number}

export function terrainTileRequests(mesh:TerrainMesh,camera:TerrainCamera,
  maxTiles=24,aspect=1.6):TerrainTileRequest[]{
 const rows=mesh.source_grid_rows??0,cols=mesh.source_grid_cols??0;
 const previewStep=mesh.source_sampling_step??1;
 if(rows<2||cols<2||previewStep<=1)return [];
 const level:1|2|4=camera.zoom>=2.4?1:camera.zoom>=1.2?2:4;
 if(level>=previewStep)return [];
 let minHeight=Infinity,maxHeight=-Infinity;
 for(const h of mesh.heights)if(h!==null&&Number.isFinite(h)){
  minHeight=Math.min(h,minHeight);maxHeight=Math.max(h,maxHeight);
 }
 const width=(mesh.cols-1)*mesh.dx_m,height=(mesh.rows-1)*mesh.dy_m;
 const scale=Math.max(width,height,
  Number.isFinite(minHeight)?maxHeight-minHeight:0,1);
 const dx=mesh.dx_m/previewStep,dy=mesh.dy_m/previewStep;
 const rowCount=Math.ceil((rows-1)/(32*level));
 const colCount=Math.ceil((cols-1)/(32*level));
 const sin=Math.sin(camera.angle),cos=Math.cos(camera.angle);
 const aspectSafe=Math.max(.5,aspect);
 const tiltCos=Math.cos(camera.tilt);
 const zMargin=(Number.isFinite(minHeight)?maxHeight-minHeight:0)/scale*
  camera.zoom*Math.abs(Math.sin(camera.tilt))*.5;
 const candidates:TerrainTileRequest[]=[];
 for(let r=0;r<rowCount;r++)for(let c=0;c<colCount;c++){
  const c0=c*32*level,c1=Math.min(cols-1,c0+32*level);
  const r0=r*32*level,r1=Math.min(rows-1,r0+32*level);
  const worldX=(((c0+c1)/2)*dx-width/2)/scale;
  const worldY=(height/2-((r0+r1)/2)*dy)/scale;
  const x=(worldX*cos-worldY*sin)*camera.zoom/aspectSafe+camera.panX;
  const y=(worldX*sin+worldY*cos)*tiltCos*camera.zoom+camera.panY;
  // Conservative projected-tile radius; reject tiles fully outside
  // the viewport, but allow for elevation-induced vertical displacement.
  const radius=(c1-c0)*dx/(2*scale)+(r1-r0)*dy/(2*scale);
  if(Math.abs(x)>1.1+radius*camera.zoom/aspectSafe||
     Math.abs(y)>1.1+radius*camera.zoom+zMargin)continue;
  if(c0/(cols-1)>camera.clip)continue;
  candidates.push({level,tile_row:r,tile_col:c,priority:x*x+y*y});
 }
 candidates.sort((a,b)=>a.priority-b.priority||
   a.tile_row-b.tile_row||a.tile_col-b.tile_col);
 return candidates.slice(0,Math.max(0,Math.min(32,Math.floor(maxTiles))));
}

/** One source-exact tiled mesh buffer, in the same coordinates as the preview.
 * No coarse face is created unless every original DEM cell in that quad was
 * marked valid by the server, including pixels between sampled LOD vertices.
 */
export function streamedTileMeshGeometry(mesh:TerrainMesh,tile:StreamedTerrainTile,
  scale:number,minimum:number,maximum:number){
 if(tile.source_elevation_unit!=='m'||(mesh.source_crs&&tile.source_crs!==mesh.source_crs)||
    tile.rows*tile.cols!==tile.heights.length||
    tile.valid_quads.length!==(tile.rows-1)*(tile.cols-1)||
    !Number.isFinite(scale)||scale<=0)throw Error('Inconsistent streamed terrain tile grid.');
 const spanX=(mesh.cols-1)*mesh.dx_m,spanY=(mesh.rows-1)*mesh.dy_m;
 const vertices:number[]=[],triangles:number[]=[],edges:number[]=[];
 for(let r=0;r<tile.rows;r++)for(let c=0;c<tile.cols;c++){
  const i=r*tile.cols+c,source=tile.heights[i],h=source??minimum;
  const x=tile.col_indices[c]*tile.grid_cell_width_m;
  const y=tile.row_indices[r]*tile.grid_cell_height_m;
  vertices.push((x-spanX/2)/scale,(spanY/2-y)/scale,
   (h-(minimum+maximum)/2)/scale,
   x/Math.max(1,spanX),y/Math.max(1,spanY),
   (h-minimum)/(maximum-minimum||1));
 }
 for(let r=0;r<tile.rows-1;r++)for(let c=0;c<tile.cols-1;c++){
  const i=r*(tile.cols-1)+c;
  if(!tile.valid_quads[i])continue;
  const a=r*tile.cols+c,b=a+1,d=a+tile.cols,e=d+1;
  if([a,b,d,e].some(j=>tile.heights[j]===null||
     !Number.isFinite(tile.heights[j])))continue;
  triangles.push(a,d,b,b,d,e);
  edges.push(a,d,d,b,b,a,b,d,d,e,e,b);
 }
 return {vertices:new Float32Array(vertices),
         triangles:new Uint32Array(triangles),
         edges:new Uint32Array(edges)};
}
