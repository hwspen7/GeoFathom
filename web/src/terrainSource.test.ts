import {describe,it,expect} from 'vitest';
import {terrainFetchBounds,terrainRasterMatchesTarget,terrainGeometryBounds,terrainBoundsOverlap,terrainFetchBudget,preferredTerrainFetchScope,terrainRasterFitsStudyArea} from './terrainSource';

const cmh:[number,number,number,number]=[-82.93,39.96,-82.85,40.03];
const old={type:'Polygon' as const,coordinates:[[[-82.59,39.41],[-82.50,39.41],[-82.50,39.46],[-82.59,39.46],[-82.59,39.41]]]};
describe('intent-safe DEM requests',()=>{
 it('hides previously downloaded far-north DEM while retaining a tight campus DEM',()=>{
  const main:[number,number,number,number]=[-83.045,39.990,-83.010,40.012];
  expect(terrainRasterFitsStudyArea({bbox:[-83.084,39.988,-83.003,40.077]},main)).toBe(false);
  expect(terrainRasterFitsStudyArea({bbox:[-83.048,39.988,-83.008,40.014]},main)).toBe(true);
 });
 it('automatically downloads the selected OSU campus, not an unrelated large viewport',()=>{
  const campus:GeoJSON.Polygon={type:'Polygon',coordinates:[[[-83.042,39.986],[-83.012,39.986],[-83.012,40.01],[-83.042,40.01],[-83.042,39.986]]]};
  const huge:[number,number,number,number]=[-83.08,39.97,-82.99,40.06];
  expect(preferredTerrainFetchScope(campus)).toBe('selection');
  const actual=terrainFetchBounds(huge,campus,preferredTerrainFetchScope(campus));
  expect(actual).not.toEqual(huge);
  expect(actual?.[0]).toBeCloseTo(-83.0424,6);
  expect(actual?.[1]).toBeCloseTo(39.9856,6);
  expect(actual?.[2]).toBeCloseTo(-83.0116,6);
  expect(actual?.[3]).toBeCloseTo(40.0104,6);
  expect(terrainFetchBudget(actual,10)?.warning).toBeNull();
  expect(preferredTerrainFetchScope({type:'Point',coordinates:[-83.02,40]})).toBe('viewport');
  expect(preferredTerrainFetchScope(null)).toBe('viewport');
 });
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
