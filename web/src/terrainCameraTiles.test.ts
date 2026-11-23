import {describe,it,expect} from 'vitest';
import {streamedTileMeshGeometry,terrainTileRequests} from './terrainCameraTiles';
import type {TerrainMesh,StreamedTerrainTile} from './api';

const mesh:TerrainMesh={
 rows:65,cols:65,dx_m:80,dy_m:80,source_crs:'EPSG:32617',
 source_grid_rows:513,source_grid_cols:513,source_sampling_step:8,
 heights:Array.from({length:65*65},(_,i)=>i*.001)
};
const camera={angle:0,tilt:.6,zoom:1.6,panX:0,panY:0,clip:1};

function tile():StreamedTerrainTile{
 return {source_crs:'EPSG:32617',grid_rows:513,grid_cols:513,
   grid_cell_width_m:10,grid_cell_height_m:10,grid_origin_xy:[0,0],
   level:2,tile_row:0,tile_col:0,
   row_indices:[0,2,4],col_indices:[0,2,4],rows:3,cols:3,
   heights:[1,2,3,4,5,6,7,8,9],
   valid_quads:[true,true,true,true],
   nodata_policy:'unknown_cells_and_intervening_pixels_remove_faces',
   source_elevation_unit:'m'};
}

describe('Camera-driven streaming tile orchestration',()=>{
 it('uses zoom-dependent multiresolution, bounded priority and camera rotation',()=>{
  const standard=terrainTileRequests(mesh,camera);
  expect(standard.length).toBeGreaterThan(0);
  expect(standard.length).toBeLessThanOrEqual(24);
  expect(standard.every(x=>x.level===2)).toBe(true);
  expect(terrainTileRequests(mesh,{...camera,zoom:3}).every(x=>x.level===1)).toBe(true);
  const rotated=terrainTileRequests(mesh,{...camera,angle:Math.PI/2});
  expect(rotated.length).toBeGreaterThan(0);
  const translated=terrainTileRequests(mesh,{...camera,panX:.6});
  expect(translated).not.toEqual(standard);
 });
 it('does not request source tiles that are already at preview resolution',()=>{
  expect(terrainTileRequests({...mesh,source_sampling_step:1},camera)).toEqual([]);
  expect(terrainTileRequests({...mesh,source_sampling_step:2},{...camera,zoom:.7})).toEqual([]);
  expect(terrainTileRequests(mesh,camera,0)).toEqual([]);
 });
 it('builds GPU coordinates in the source grid, preserving exact cell edges',()=>{
  const geo=streamedTileMeshGeometry(mesh,tile(),5120,1,9);
  expect(geo.vertices.length).toBe(3*3*6);
  expect(geo.triangles.length).toBe(4*6);
  expect(geo.edges.length).toBe(4*12);
  expect(geo.triangles[0]).toBe(0);
  expect(geo.triangles[1]).toBe(3);
  expect(geo.vertices[0]).toBeCloseTo(-.5);
  expect(geo.vertices[6]).toBeCloseTo((-2560+20)/5120);
 });
 it('never bridges an unknown interior tile quad',()=>{
  const input=tile();
  input.valid_quads=[false,true,true,true];
  const geo=streamedTileMeshGeometry(mesh,input,5120,1,9);
  expect(geo.triangles.length).toBe(3*6);
  const gapped=tile();
  gapped.heights[4]=null;
  const empty=streamedTileMeshGeometry(mesh,gapped,5120,1,9);
  expect(empty.triangles.length).toBe(0);
 });
 it('rejects source CRS mismatches before GPU upload',()=>{
  const wrong={...tile(),source_crs:'EPSG:3857'};
  expect(()=>streamedTileMeshGeometry(mesh,wrong,1,1,9)).toThrow('Inconsistent');
 });
});
