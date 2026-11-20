import { describe, expect, test } from 'vitest';
import {
  GeometryTimeline, addVertex, approximateMeasurement, moveVertex,
  removeVertex, shiftGeometry, snapPixels, verticesOf,
} from './editing';

const box: GeoJSON.Polygon = {
  type: 'Polygon',
  coordinates: [[[0,0],[0.01,0],[0.01,0.01],[0,0.01],[0,0]]],
};

describe('P0 draggable polygon geometry', () => {
  test('vertex manipulation preserves ring closure and does not mutate original', () => {
    const modified = moveVertex(box, { polygon:0,ring:0,vertex:0 }, [0.001,0.001]) as GeoJSON.Polygon;
    expect(modified.coordinates[0][0]).toEqual([0.001,0.001]);
    expect(modified.coordinates[0].at(-1)).toEqual([0.001,0.001]);
    expect(box.coordinates[0][0]).toEqual([0,0]);
  });
  test('midpoint insertion and vertex deletion retain a valid ring size', () => {
    const mid = addVertex(box, {polygon:0,ring:0,vertex:1},[0.01,0.005]) as GeoJSON.Polygon;
    expect(mid.coordinates[0]).toHaveLength(6);
    const again = removeVertex(mid,{polygon:0,ring:0,vertex:2}) as GeoJSON.Polygon;
    expect(again.coordinates[0]).toHaveLength(5);
    expect(() => removeVertex(
      {type:'Polygon',coordinates:[[[0,0],[1,0],[0,1],[0,0]]]},
      {polygon:0,ring:0,vertex:0},
    )).toThrow('Cannot delete');
  });
  test('move entire polygon', () => {
    const shifted = shiftGeometry(box,0.01,0.02) as GeoJSON.Polygon;
    expect(shifted.coordinates[0][0]).toEqual([0.01,0.02]);
    expect(shifted.coordinates[0].at(-1)).toEqual([0.01,0.02]);
  });
  test('area and perimeter preview updates after moving points', () => {
    const first=approximateMeasurement(box);
    const larger=approximateMeasurement(moveVertex(box,{polygon:0,ring:0,vertex:1},[0.02,0]));
    expect(first.area_m2).toBeGreaterThan(1_000_000);
    expect(larger.area_m2).toBeGreaterThan(first.area_m2!);
    expect(first.perimeter_m).toBeGreaterThan(0);
  });
  test('snap uses nearest visible vertex inside pixel threshold', () => {
    const point=snapPixels([10,10],[[0,0],[13,14]],p=>p,6);
    expect(point).toEqual([13,14]);
    expect(snapPixels([20,20],[[0,0]],p=>p,6)).toEqual([20,20]);
  });
});

describe('P1 holes and multipart regions', () => {
  test('interior hole has editable vertices and correctly reduces preview area', () => {
    const hollow:GeoJSON.Polygon={
      type:'Polygon',coordinates:[
        box.coordinates[0],
        [[0.002,0.002],[0.002,0.004],[0.004,0.004],[0.004,0.002],[0.002,0.002]],
      ],
    };
    expect(verticesOf(hollow).some(v=>v.path.ring===1)).toBe(true);
    expect(approximateMeasurement(hollow).area_m2)
      .toBeLessThan(approximateMeasurement(box).area_m2!);
  });
  test('multi-polygon geometry retains individual editing paths', () => {
    const multi:GeoJSON.MultiPolygon={type:'MultiPolygon',coordinates:[
      box.coordinates,shiftGeometry(box,0.05,0.05).type==='Polygon'
        ? (shiftGeometry(box,0.05,0.05) as GeoJSON.Polygon).coordinates:box.coordinates,
    ]};
    const edited=moveVertex(multi,{polygon:1,ring:0,vertex:0},[0.1,0.1]) as GeoJSON.MultiPolygon;
    expect(edited.coordinates[0]).toEqual(box.coordinates);
    expect(edited.coordinates[1][0][0]).toEqual([0.1,0.1]);
  });
});

describe('P0/P2 undo, redo and history', () => {
  test('branching history drops future states and avoids duplicate snapshots', () => {
    const timeline=new GeometryTimeline();
    expect(timeline.canUndo).toBe(false);
    timeline.push(box);
    timeline.push(box);
    expect(timeline.current).toEqual(box);
    const wider=moveVertex(box,{polygon:0,ring:0,vertex:1},[0.02,0]);
    timeline.push(wider);
    expect(timeline.canUndo).toBe(true);
    expect(timeline.undo()).toEqual(box);
    expect(timeline.redo()).toEqual(wider);
    timeline.undo();
    timeline.push(shiftGeometry(box,0.1,0.1));
    expect(timeline.canRedo).toBe(false);
  });
});
