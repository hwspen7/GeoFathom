import {describe,expect,it} from 'vitest';
import {registrySources,resultSource,terrainSource,type ScienceRegistry} from './scienceRegistry';
import type {SpatialScienceResult,TerrainRasterLayer} from './api';
describe('shared scientific raster registry',()=>{
 it('retains exact disk-backed terrain products and separates consumer modules',()=>{
  const raster=terrainSource({id:'slope',title:'Slope',raster:{geotiff:'',product_id:'disk-id',unit:'degree'},opacity:0,resampling:'nearest'} as TerrainRasterLayer);
  const result=resultSource('Temporal',{raster:{sha256:'hash',data:'exact-tiff',unit:'degree/year',name:'trend'}} as SpatialScienceResult,'Trend')!;
  const registry:ScienceRegistry={Terrain:[raster],Temporal:[result]};
  expect(registrySources(registry).map(r=>r.id)).toEqual(['terrain:slope','Temporal:hash']);
  expect(registrySources(registry,'Temporal')).toEqual([raster]);
  expect(registrySources(registry,'Terrain')).toEqual([result]);
  expect(raster.product_id).toBe('disk-id');
  expect(result.data).toBe('exact-tiff');
  expect(resultSource('Spatial',{raster:null} as SpatialScienceResult,'Vector')).toBeNull();
 });
});
