import {describe,expect,it} from 'vitest';
import {PixelSnapIndex} from './spatialIndex';

describe('viewport-scale spatial hash snapping',()=>{
  it('finds nearest vertex and edge in pixel space',()=>{
    const index=new PixelSnapIndex([
      [[0,0],[100,0],[100,100]],
    ],point=>point);
    expect(index.snap([0,3],12).kind).toBe('vertex');
    expect(index.snap([44,3],12)).toMatchObject({kind:'edge',point:[44,0]});
    expect(index.snap([300,300],12).kind).toBe('none');
  });
  it('indexes 100,000 discrete screen segments and returns the right neighbor',()=>{
    const paths:Array<[number,number][]>=[];
    for(let i=0;i<100000;i++){
      paths.push([[i*20,0],[i*20,100]]);
    }
    const t=performance.now();
    const index=new PixelSnapIndex(paths,point=>point);
    expect(index.size).toBe(300000);
    for(let i=0;i<100;i++){
      const target=100+i*900;
      const found=index.snap([target*20+2,50],10);
      expect(found.kind).toBe('edge');
      expect(found.point[0]).toBe(target*20);
    }
    console.info('100k segment spatial hash build+100 queries (ms):',
      (performance.now()-t).toFixed(1));
  });
  it('handles long segments without allocating enormous bucket ranges',()=>{
    const index=new PixelSnapIndex([[[0,0],[1_000_000,0]]],p=>p);
    expect(index.snap([900_000,3]).point).toEqual([900_000,0]);
  });
});
