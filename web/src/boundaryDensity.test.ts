import {describe,it,expect} from 'vitest';
import {boundaryNodeVisible} from './boundaryDensity';
describe('GIS vertex density without geometric simplification',()=>{
 it('reduces 521-node campus boundaries at regional zoom',()=>{
  const visible=(zoom:number)=>Array.from({length:521},(_,i)=>i)
   .filter(i=>boundaryNodeVisible(i,521,zoom,false,false)).length;
  expect(visible(11)).toBeLessThanOrEqual(16);
  expect(visible(14)).toBeLessThanOrEqual(48);
  expect(visible(16)).toBeLessThanOrEqual(120);
  expect(visible(18)).toBe(521);
 });
 it('always keeps active node and never duplicates editing nodes',()=>{
  expect(boundaryNodeVisible(400,521,11,false,true)).toBe(true);
  expect(boundaryNodeVisible(400,521,11,true,false)).toBe(false);
 });
});
