/** Camera-derived, bounded DEM tile priorities. Pure for regression tests. */
import type {TerrainMesh} from './api';

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
