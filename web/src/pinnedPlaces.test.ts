import {describe,expect,it} from 'vitest';
import {pinPlace,unpinPlace,visibleGeometry,PIN_LIMIT} from './pinnedPlaces';
import type {Place} from './api';
const place=(id:string):Place=>({id,name:'Location '+id,display_name:'Test location',
 longitude:-82.892,latitude:39.997,bbox:null,geometry:{type:'Point',coordinates:[-82.892,39.997]},
 boundary_status:'location_only',source:'test',osm_type:null,osm_id:null});
describe('pinned places are deleted only by explicit remove',()=>{
 it('does not remove prior places when the user selects another location',()=>{
  const a=place('cmh'),b=place('oth');
  const saved=pinPlace(pinPlace([],a),b);
  expect(saved.map(p=>p.id)).toEqual(['oth','cmh']);
  expect(pinPlace(saved,b)).toHaveLength(2);
  expect(unpinPlace(saved,'cmh').map(p=>p.id)).toEqual(['oth']);
 });
 it('refuses to evict previously pinned places when capacity is reached',()=>{
  const full=Array.from({length:PIN_LIMIT},(_,i)=>place(String(i)));
  expect(pinPlace(full,place('new')).map(p=>p.id)).toEqual(full.map(p=>p.id));
 });
 it('distinguishes geocoded coordinate from mapped polygon',()=>{
  const p=place('cmh');
  expect(visibleGeometry(p).type).toBe('Point');
  expect(visibleGeometry({...p,geometry:null})).toEqual({type:'Point',coordinates:[-82.892,39.997]});
 });
});
