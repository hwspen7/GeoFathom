import {describe,it,expect} from 'vitest';
import {nearestProfileSample} from './profileLink';
const samples=[0,100,200,300].map((distance_m,i)=>({
 distance_m,elevation_m:100+i*5,coordinate:[i*100,10] as [number,number],
}));
const project=(p:[number,number])=>({x:p[0],y:p[1]});
describe('map to profile coordinate linking',()=>{
 it('selects nearest real station on the map line',()=>{
  expect(nearestProfileSample(samples,{x:95,y:11},project)).toBe(1);
  expect(nearestProfileSample(samples,{x:198,y:9},project)).toBe(2);
 });
 it('clears selection off the profile line and for missing data',()=>{
  expect(nearestProfileSample(samples,{x:180,y:50},project)).toBeNull();
  expect(nearestProfileSample([],{x:100,y:10},project)).toBeNull();
 });
 it('interpolates screen segment position but returns existing sample data',()=>{
  expect(nearestProfileSample(samples,{x:145,y:9},project)).toBe(1);
  expect(nearestProfileSample(samples,{x:156,y:9},project)).toBe(2);
 });
 it('does not join across missing coordinates',()=>{
  const missing=samples.map((s,i)=>i===2?{...s,coordinate:undefined}:s);
  expect(nearestProfileSample(missing,{x:250,y:10},project)).toBeNull();
 });
});
