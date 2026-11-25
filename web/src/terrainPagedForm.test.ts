import {describe,it,expect} from 'vitest';
import {paginateTerrainRows} from './TerrainPagedForm';
describe('fixed terrain form pages',()=>{
 it('packs every row exactly once without splitting controls',()=>{
  expect(paginateTerrainRows([30,30,60,30],100)).toEqual([{page:0,top:0},{page:0,top:36},{page:1,top:0},{page:1,top:66}]);
 });
 it('repaginates when the panel height changes',()=>{
  expect(paginateTerrainRows([30,30,30],65).map(r=>r.page)).toEqual([0,1,2]);
  expect(paginateTerrainRows([30,30,30],102).map(r=>r.page)).toEqual([0,0,0]);
 });
});
