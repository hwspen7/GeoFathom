import {describe,expect,it} from 'vitest';
import {sketchAddError,sketchFinishError,canPreviewClosedSketch,sketchSegmentsIntersect,closedLineAsPolygon} from './sketch';
import {drawingPreview,type Position} from './editing';

const a:[number,number]=[0,0],b:[number,number]=[2,0],
 c:[number,number]=[2,2],d:[number,number]=[0,2];
const square:Position[]=[a,b,c,d];
describe('professional polygon drawing contract',()=>{
 it('permits concave simple rings and closes with one copy of the origin',()=>{
  const concave:Position[]=[a,b,[1,1],d];
  expect(sketchFinishError('polygon',concave)).toBeNull();
  const g=drawingPreview('polygon',concave) as GeoJSON.Polygon;
  expect(g.type).toBe('Polygon');
  expect(g.coordinates[0]).toHaveLength(5);
  expect(g.coordinates[0][0]).toEqual(g.coordinates[0].at(-1));
 });
 it('rejects bow-tie crossings at insertion, including touching earlier segments',()=>{
  const points:Position[]=[a,c,d];
  expect(sketchAddError('polygon',points,b)).toMatch(/crosses/);
  expect(sketchAddError('polygon',[a,b,c],a)).toMatch(/first point/);
  expect(sketchSegmentsIntersect([0,0],[2,2],[0,2],[2,0])).toBe(true);
  expect(sketchSegmentsIntersect([0,0],[1,0],[2,0],[3,0])).toBe(false);
  expect(sketchSegmentsIntersect([0,0],[2,0],[1,0],[3,0])).toBe(true);
 });
 it('rejects only-at-closure crossings in an otherwise valid open polyline',()=>{
  const path:Position[]=[[3,2],[0,4],[-1,2],[3,-2],[1,-1]];
  for(let i=0;i<path.length;i++)
    expect(sketchAddError('polygon',path.slice(0,i),path[i])).toBeNull();
  expect(sketchFinishError('polygon',path)).toMatch(/Closing edge intersects/);
  expect(canPreviewClosedSketch('polygon',path)).toBe(false);
  expect(drawingPreview('polygon',path)?.type).toBe('LineString');
 });
 it('rejects degenerate polygons, duplicate coordinates, and invalid WGS84',()=>{
  expect(sketchFinishError('polygon',[[0,0],[1,1],[2,2]])).toMatch(/zero area/);
  expect(sketchFinishError('polygon',[[0,0],[1,0]])).toMatch(/1 more/);
  expect(sketchAddError('hole',[a,b,c],[0,0])).toMatch(/first point/);
  expect(sketchAddError('polygon',[a,b],[200,0])).toMatch(/WGS84/);
  expect(sketchAddError('polygon',[a,b],[2,0])).toMatch(/Duplicate/);
  expect(sketchFinishError('rectangle',[a,a])).toMatch(/Duplicate/);
  expect(sketchAddError('polygon',[a,[2,0]],[1,0])).toMatch(/retraces/);
 });
 it('draws only valid open line previews when cursor would cross prior edges',()=>{
  const points:Position[]=[[0,0],[3,0],[3,3],[0,3]];
  const invalidCursor:Position=[2,-1];
  expect(sketchAddError('polygon',points,invalidCursor)).toMatch(/crosses/);
  const draft=drawingPreview('polygon',points,invalidCursor) as GeoJSON.Polygon;
  expect(draft.type).toBe('Polygon');
  expect(draft.coordinates[0]).toHaveLength(5);
  expect(draft.coordinates[0]).not.toContainEqual(invalidCursor);
 });
 it('keeps non-polygon tools usable with distinct point constraints',()=>{
  expect(sketchFinishError('point',[a])).toBeNull();
  expect(sketchFinishError('line',[a,b])).toBeNull();
  expect(sketchFinishError('split',[a,b])).toBeNull();
  expect(sketchFinishError('trace-along',[a,b])).toBeNull();
  expect(sketchFinishError('circle',[a,b])).toBeNull();
  expect(sketchFinishError('hole',square)).toBeNull();
  expect(sketchFinishError('rectangle',square)).toMatch(/Maximum/);
 });
});

describe('closed line sketch becomes a real area feature',()=>{
 it('converts first-node closure into a simple closed Polygon suitable for measurement',()=>{
  const area=closedLineAsPolygon([a,b,c,d,a]);
  expect(area?.type).toBe('Polygon');
  expect(area?.coordinates[0]).toEqual([a,b,c,d,a]);
  const measured=area?drawingPreview('polygon',area.coordinates[0].slice(0,-1) as Position[]):null;
  expect(measured?.type).toBe('Polygon');
 });
 it('leaves genuinely open line drawings as LineString candidates',()=>{
  expect(closedLineAsPolygon([a,b,c,d])).toBeNull();
  expect(closedLineAsPolygon([a,b,c])).toBeNull();
 });
 it('rejects self-intersecting closed paths instead of falsifying an area',()=>{
  expect(()=>closedLineAsPolygon([a,c,b,d,a])).toThrow(/Cannot form enclosed region/);
  expect(()=>closedLineAsPolygon([a,b,[0,1],b,a])).toThrow(/Cannot form enclosed region/);
 });
});
