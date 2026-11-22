import {describe,it,expect} from 'vitest';
import {drawingPreview,measurementAnchor,approximateMeasurement,moveVertex,verticesOf,moveEdge} from './editing';
describe('interactive geometry',()=>{
 it('previews a closed rectangle from the pointer before finish',()=>{
  const g=drawingPreview('rectangle',[[0,0]],[.001,.001]);
  expect(g?.type).toBe('Polygon');
  expect(approximateMeasurement(g!).area_m2).toBeGreaterThan(12000);
 });
 it('previews real circle geometry, not a line',()=>{
  const g=drawingPreview('circle',[[0,0]],[.001,0]) as GeoJSON.Polygon;
  expect(g.coordinates[0]).toHaveLength(73);
  expect(approximateMeasurement(g).area_m2).toBeGreaterThan(38000);
 });
 it('handles points and open multiline endpoints',()=>{
  expect(moveVertex({type:'Point',coordinates:[0,0]},{polygon:0,ring:0,vertex:0},[1,2])).toEqual({type:'Point',coordinates:[1,2]});
  const g:GeoJSON.MultiLineString={type:'MultiLineString',coordinates:[[[0,0],[1,1]],[[2,2],[3,3]]]};
  expect(verticesOf(g).filter(v=>!v.midpoint)).toHaveLength(4);
  expect(approximateMeasurement(g).length_m).toBeGreaterThan(300000);
 });
 it('places a measurement anchor outside a polygon hole',()=>{
  const g:GeoJSON.Polygon={type:'Polygon',coordinates:[[[0,0],[10,0],[10,10],[0,10],[0,0]],[[2,2],[8,2],[8,8],[2,8],[2,2]]]};
  const p=measurementAnchor(g)!;
  expect(p[0]>2&&p[0]<8&&p[1]>2&&p[1]<8).toBe(false);
 });
});

it('moves both endpoints of a closing edge without changing point count',()=>{
 const g:GeoJSON.Polygon={type:'Polygon',coordinates:[[[0,0],[.01,0],[.01,.01],[0,.01],[0,0]]]};
 const moved=moveEdge(g,{polygon:0,ring:0,vertex:3},90,10) as GeoJSON.Polygon;
 expect(moved.coordinates[0]).toHaveLength(5);
 expect(moved.coordinates[0][0]).toEqual(moved.coordinates[0][4]);
 expect(moved.coordinates[0][0][0]).toBeGreaterThan(0);
 expect(moved.coordinates[0][3][0]).toBeGreaterThan(0);
 expect(moved.coordinates[0][1]).toEqual(g.coordinates[0][1]);
});
