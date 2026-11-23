import {describe,it,expect} from 'vitest';
import {meshLODIndices} from './TerrainMeshView';
import type {TerrainMesh} from './api';

const mesh=(rows:number,cols:number):TerrainMesh=>({
 rows,cols,dx_m:1,dy_m:1,heights:Array.from({length:rows*cols},(_,i)=>i)
});

describe('P1 camera-adaptive 3D LOD',()=>{
 it('coarsens geometry by power-of-two step and retains boundary vertices',()=>{
  const input=mesh(9,9);
  expect(meshLODIndices(input,1).triangles.length).toBe(8*8*6);
  expect(meshLODIndices(input,2).triangles.length).toBe(4*4*6);
  expect(meshLODIndices(input,4).triangles.length).toBe(2*2*6);
  const indices=Array.from(meshLODIndices(input,4).triangles);
  expect(indices).toContain(80);
 });
 it('preserves irregular boundary strips without dropping any edge',()=>{
  const input=mesh(8,10);
  const indices=Array.from(meshLODIndices(input,4).triangles);
  expect(indices).toContain(79); // bottom-right original grid cell
  expect(indices.every(i=>i>=0&&i<input.rows*input.cols)).toBe(true);
 });
 it('never bridges any invalid interior cell from a coarser rectangle',()=>{
  const input=mesh(9,9);
  input.heights[1*9+1]=null;
  const indices=Array.from(meshLODIndices(input,4).triangles);
  expect(indices.length).toBe(3*6);
  expect(indices).not.toContain(0);
 });
 it('checks the LOD step contract',()=>{
  expect(()=>meshLODIndices(mesh(9,9),3)).toThrow('Unsupported');
  expect(()=>meshLODIndices(mesh(9,9),0)).toThrow('Unsupported');
 });
});
