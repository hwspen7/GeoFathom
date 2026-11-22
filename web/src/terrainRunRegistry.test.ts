import {describe,it,expect} from 'vitest';
import {insertTerrainRun,summarizeTerrainRun} from './terrainRunRegistry';
import type {RasterAsset} from './api';
const source:RasterAsset={id:'a',name:'USGS 3DEP 10 m grid',width:250,height:300,bands:1,
 crs:'EPSG:32610',bbox:[-122.2,37.4,-122.1,37.5],corners:[[-122.2,37.5],[-122.1,37.5],[-122.1,37.4],[-122.2,37.4]],
 preview_url:'',acquired_at:'2026-11-22',provenance:'USGS DEM'};
describe('scientific run metadata history',()=>{
 it('captures immutable source facts and no PNG or GeoTIFF bytes',()=>{
  const run=summarizeTerrainRun('test',123,'slope_map',source,
    {type:'Polygon',coordinates:[[[-122.19,37.41],[-122.11,37.41],[-122.11,37.49],[-122.19,37.49],[-122.19,37.41]]]},
    {product_mean:5.17,product_min:0,invalid:Infinity});
  expect(run.sourceId).toBe('a');expect(run.grid).toEqual([250,300]);
  expect(run.metrics).toEqual({product_mean:5.17,product_min:0});
  expect(JSON.stringify(run)).not.toMatch(/geotiff|preview_url|png/);
 });
 it('retains up to 100 metadata versions without evicting an unrelated run on update',()=>{
  let items=Array.from({length:101},(_,i)=>summarizeTerrainRun(String(i),i,'slope_map',source,{type:'Point',coordinates:[0,0]},{}));
  items=insertTerrainRun(items,summarizeTerrainRun('fresh',999,'slope_map',source,{type:'Point',coordinates:[0,0]},{}));
  expect(items).toHaveLength(100);expect(items[0].id).toBe('fresh');
 });
});


describe('DEM change source lineage',()=>{
 it('records the second DEM independently of the primary input',()=>{
  const reference={...source,id:'reference',name:'Copernicus GLO-30',
    crs:'EPSG:32610',acquired_at:'2025-01-01'};
  const run=summarizeTerrainRun('comparison',180,'dem_difference',source,
    {type:'Point',coordinates:[0,0]},{elevation_change_mean_m:2.5},reference);
  expect(run.sourceId).toBe('a');
  expect(run.referenceSourceId).toBe('reference');
  expect(run.referenceSourceName).toBe('Copernicus GLO-30');
  expect(run.referenceAcquiredAt).toBe('2025-01-01');
  expect(JSON.stringify(run)).not.toMatch(/geotiff|preview_url|png/);
 });
});
