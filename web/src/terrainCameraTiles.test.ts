import {describe,it,expect} from 'vitest';
import {loadTerrainTileBatch,streamedTileMeshGeometry,terrainAdaptiveTileLevel,terrainTileRequests} from './terrainCameraTiles';
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


describe('Research-grade terrain streaming quality',()=>{
 it('increases LOD in rugged terrain without changing flat-terrain behavior',()=>{
  const flat=terrainAdaptiveTileLevel(mesh,{...camera,zoom:.7});
  expect(flat).toBe(4);
  const rugged:TerrainMesh={...mesh,heights:Array(65*65).fill(0)};
  rugged.heights[32*65+32]=2000;
  const detailed=terrainAdaptiveTileLevel(rugged,{...camera,zoom:1.6,exaggeration:5});
  expect(detailed).toBe(1);
  expect(terrainTileRequests(rugged,{...camera,zoom:1.6,exaggeration:5})
    .every(t=>t.level===1)).toBe(true);
 });
 it('rejects a tile with scrambled or incomplete source indices',()=>{
  const wrong=tile();wrong.col_indices=[0,4,2];
  expect(()=>streamedTileMeshGeometry(mesh,wrong,5120,1,9)).toThrow('Inconsistent');
  const missing=tile();missing.row_indices=[0,2];
  expect(()=>streamedTileMeshGeometry(mesh,missing,5120,1,9)).toThrow('Inconsistent');
 });
 it('loads with limited parallelism and reports measured LOD error',async()=>{
  const requests=Array.from({length:9},(_,n)=>({level:2 as const,tile_row:0,tile_col:n,priority:n}));
  let active=0,peak=0,installed=0;
  const result=await loadTerrainTileBatch(
    requests,request=>request.tile_col===0,
    async request=>{
      active++;peak=Math.max(peak,active);
      await new Promise(resolve=>setTimeout(resolve,1));
      active--;
      return {...tile(),geometric_error_max_m:request.tile_col*.25};
    },
    ()=>{installed++;},undefined,3);
  expect(peak).toBeGreaterThan(1);
  expect(peak).toBeLessThanOrEqual(3);
  expect(result).toEqual({loaded:8,failed:0,maximumErrorM:2});
  expect(installed).toBe(8);
 });
 it('isolates failed tile reads and never installs stale requests',async()=>{
  const requests=Array.from({length:5},(_,n)=>({level:2 as const,tile_row:0,tile_col:n,priority:n}));
  const result=await loadTerrainTileBatch(requests,()=>false,
    async req=>{if(req.tile_col===2)throw Error('Transient DEM tile failure');return tile();},
    ()=>{},undefined,2);
  expect(result.loaded).toBe(4);
  expect(result.failed).toBe(1);
  const controller=new AbortController();let installed=0;
  const cancelled=loadTerrainTileBatch(requests,()=>false,
    async()=>{await new Promise(resolve=>setTimeout(resolve,1));return tile();},
    ()=>{installed++;},controller.signal,2);
  controller.abort();
  expect((await cancelled).loaded).toBe(0);
  expect(installed).toBe(0);
 });
});
