import {describe,it,expect} from 'vitest';
import {terrainFetchBounds,terrainRasterMatchesTarget,terrainGeometryBounds,terrainBoundsOverlap,terrainFetchBudget} from './terrainSource';

const cmh:[number,number,number,number]=[-82.93,39.96,-82.85,40.03];
const old={type:'Polygon' as const,coordinates:[[[-82.59,39.41],[-82.50,39.41],[-82.50,39.46],[-82.59,39.46],[-82.59,39.41]]]};
describe('intent-safe DEM requests',()=>{
 it('uses CMH viewport by default even when a distant polygon remains selected',()=>{
  expect(terrainFetchBounds(cmh,old,'viewport')).toEqual(cmh);
  const selected=terrainFetchBounds(cmh,old,'selection');
  expect(selected).not.toEqual(cmh);
  expect(terrainBoundsOverlap(selected!,cmh)).toBe(false);
 });
 it('rejects absent or unsupported selections rather than silently reverting to a different location',()=>{
  expect(terrainFetchBounds(cmh,null,'selection')).toBeNull();
  expect(terrainGeometryBounds({type:'Point',coordinates:[-82.89,39.99]})).toBeNull();
  expect(terrainFetchBounds(cmh,{type:'LineString',coordinates:[[-82.9,40],[-82.9,40.01]]},'selection')).not.toBeNull();
 });
 it('checks the returned DEM footprint rather than trusting the file name or source title',()=>{
  expect(terrainRasterMatchesTarget({bbox:[-82.6,39.4,-82.5,39.5]},cmh)).toBe(false);
  expect(terrainRasterMatchesTarget({bbox:[-83,39.9,-82.8,40.1]},cmh)).toBe(true);
  expect(terrainRasterMatchesTarget({bbox:[-82.90,39.97,-82.87,40.02]},cmh)).toBe(false);
 });
 it('measures large polygon coordinates without overflowing the JavaScript argument limit',()=>{
  const ring=Array.from({length:150000},(_,i)=>[-82.90+(i%2)*.03,39.99+(i%3)*.02]);
  const bounds=terrainGeometryBounds({type:'Polygon',coordinates:[ring]});
  expect(bounds![0]).toBeCloseTo(-82.9);expect(bounds![2]).toBeCloseTo(-82.87);expect(bounds![3]).toBeCloseTo(40.03);
 });
 it('reports high-resolution limits before sending requests and rejects bad geography',()=>{
  expect(terrainFetchBudget(cmh,1)!.warning).toMatch(/budget/);
  expect(terrainFetchBudget(cmh,30)!.warning).toBeNull();
  expect(terrainFetchBounds([170,39,-170,40],null,'viewport')).toBeNull();
  expect(terrainFetchBounds([-82,80,-81,84],null,'viewport')).toBeNull();
 });
});
