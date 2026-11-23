import {describe,it,expect} from 'vitest';
import {nearestEditableHandle} from './vertexHit';

const project=([longitude,latitude]:[number,number])=>({x:longitude*100,y:latitude*100});
const polygon:GeoJSON.Polygon={
  type:'Polygon',
  coordinates:[[[0,0],[10,0],[10,10],[0,10],[0,0]]],
};

describe('authoritative geometry hit test',()=>{
  it('selects the exact vertex even when the rendered worker has no handle',()=>{
    const hit=nearestEditableHandle(polygon,{x:1001,y:999},project,'vertex');
    expect(hit?.path).toEqual({polygon:0,ring:0,vertex:2});
    expect(hit?.midpoint).toBe(false);
  });
  it('chooses a midpoint only when the user targets that midpoint',()=>{
    const midpoint=nearestEditableHandle(polygon,{x:500,y:1},project,'both');
    expect(midpoint?.midpoint).toBe(true);
    expect(midpoint?.path.vertex).toBe(0);
    expect(nearestEditableHandle(polygon,{x:500,y:1},project,'vertex')).toBeNull();
  });
  it('does not turn unrelated clicks into vertex edits',()=>{
    expect(nearestEditableHandle(polygon,{x:750,y:750},project,'both')).toBeNull();
  });
  it('chooses the correct polygon and ring among disconnected parcels',()=>{
    const parcels:GeoJSON.MultiPolygon={
      type:'MultiPolygon',
      coordinates:[polygon.coordinates,[
        [[20,20],[22,20],[22,22],[20,22],[20,20]],
        [[20.5,20.5],[21,20.5],[21,21],[20.5,21],[20.5,20.5]]
      ]],
    };
    expect(nearestEditableHandle(parcels,{x:2101,y:2100},project,'vertex')?.path)
      .toEqual({polygon:1,ring:1,vertex:2});
  });
  it('resolves the same vertex regardless of nearby midpoint symbols',()=>{
    const tiny:GeoJSON.Polygon={type:'Polygon',
      coordinates:[[[0,0],[0.11,0],[1,1],[0,1],[0,0]]]};
    expect(nearestEditableHandle(tiny,{x:0,y:0},project,'both')?.path.vertex).toBe(0);
    expect(nearestEditableHandle(tiny,{x:0,y:0},project,'both')?.midpoint).toBe(false);
  });
});
