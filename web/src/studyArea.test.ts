import {describe,it,expect} from 'vitest';
import {studyParcels,suggestedParcel,parcelAt} from './studyArea';
import {terrainGeometryBounds} from './terrainSource';

const campus:GeoJSON.MultiPolygon={type:'MultiPolygon',coordinates:[
 [[[-83.045,39.990],[-83.01,39.990],[-83.01,40.012],[-83.045,40.012],[-83.045,39.990]]],
 [[[-83.08,40.070],[-83.06,40.070],[-83.06,40.076],[-83.08,40.076],[-83.08,40.070]]],
]};
describe('non-destructive OSU campus parcel selection',()=>{
 it('separates a remote northern parcel from main campus without losing original geometry',()=>{
  const parcels=studyParcels(campus);
  expect(parcels).toHaveLength(2);
  expect(suggestedParcel(campus,[-83.022,40.001])).toBe(0);
  expect(suggestedParcel(campus,[-83.07,40.073])).toBe(1);
  const chosen=parcelAt(campus,suggestedParcel(campus,[-83.022,40.001])!)!;
  expect(chosen.type).toBe('Polygon');
  expect(terrainGeometryBounds(chosen)?.[3]).toBeCloseTo(40.012);
  expect(terrainGeometryBounds(parcelAt(campus,'all'))?.[3]).toBeCloseTo(40.076);
  expect(campus.coordinates).toHaveLength(2);
 });
 it('never guesses a polygon from a geocoded Point',()=>{
  expect(studyParcels({type:'Point',coordinates:[-83,40]})).toHaveLength(0);
  expect(suggestedParcel(null,[-83,40])).toBeNull();
 });
 it('keeps holes in the same parcel and does not count them as separate sites',()=>{
  const area:GeoJSON.Polygon={type:'Polygon',coordinates:[
   [[0,0],[2,0],[2,2],[0,2],[0,0]],
   [[.5,.5],[.5,1],[1,1],[1,.5],[.5,.5]],
  ]};
  expect(studyParcels(area)).toHaveLength(1);
  expect(studyParcels(area)[0].areaKm2).toBeGreaterThan(0);
 });
});
