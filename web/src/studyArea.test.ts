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


describe('parcel geometry governs study-area acquisition, not its envelope',()=>{
 it('chooses a nearby real parcel when a distant concave parcel has an enclosing bounding box',()=>{
  const disconnected:GeoJSON.MultiPolygon={type:'MultiPolygon',coordinates:[
   [[[0,0],[10,0],[10,1],[1,1],[1,10],[0,10],[0,0]]],
   [[[8.5,8.5],[9,8.5],[9,9],[8.5,9],[8.5,8.5]]],
  ]};
  // Neither polygon contains the search reference. The first polygon's
  // bounding box contains it, but its actual land is several degrees away.
  expect(suggestedParcel(disconnected,[8,8])).toBe(1);
  expect(suggestedParcel(disconnected,[.5,5])).toBe(0);
  expect(disconnected.coordinates).toHaveLength(2);
 });
 it('computes finite meter-scale parcel area without longitude cancellation',()=>{
  const lon=-123.456789,lat=40.123456,step=.00001;
  const tiny:GeoJSON.Polygon={type:'Polygon',coordinates:[[
   [lon,lat],[lon+step,lat],[lon+step,lat+step],
   [lon,lat+step],[lon,lat],
  ]]};
  const expected=(111320*step)**2*Math.cos(lat*Math.PI/180);
  expect(studyParcels(tiny)[0].areaKm2*1e6).toBeCloseTo(expected,5);
 });
});
