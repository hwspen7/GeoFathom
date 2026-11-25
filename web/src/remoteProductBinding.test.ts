import {describe,it,expect} from 'vitest';
import {identifyBand,suggestProductBindings} from './remoteProductBinding';
const l='LC09_L2SP_022032_20240701_20240705_02_T1_';
const source=(name:string)=>({name,data:'fixture'});
const roles=[{id:'nir',quantity:'reflectance'},{id:'red',quantity:'reflectance'}];
describe('explicit product band suggestions',()=>{
 it('maps Landsat 8/9 C2 L2 and both quality masks',()=>{
  const r=suggestProductBindings(['SR_B4','SR_B5','QA_PIXEL','QA_RADSAT'].map(x=>source(l+x+'.TIF')),roles);
  expect(r.bindings.nir).toMatchObject({source:1,encoding:'landsat_sr'});
  expect(r.bindings.red.source).toBe(0);expect(r.quality.map(x=>x.scheme)).toEqual(['landsat_clear','landsat_unsaturated']);
 });
 it('never confuses B08 with narrow B8A or chooses duplicate resolution',()=>{
  expect(identifyBand('T33UUP_20230907T100031_B8A_20m.tif')?.role).toBe('nir_narrow');
  expect(()=>suggestProductBindings(['B08_10m','B08_20m','B04_10m'].map(x=>source('T33UUP_20230907T100031_'+x+'.tif')),roles)).toThrow('ambiguous');
 });
 it('rejects mixed acquisitions and unknown filenames',()=>{
  expect(()=>suggestProductBindings([source(l+'SR_B4.TIF'),source(l.replace('20240701','20240702')+'SR_B5.TIF')],roles)).toThrow('Multiple acquisitions');
  expect(identifyBand('B08.tif')).toBeNull();
 });
});
