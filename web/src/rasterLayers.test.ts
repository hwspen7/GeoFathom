import {it,expect} from 'vitest';import {addRaster,changeRaster} from './rasterLayers';import type {RasterAsset} from './api';
it('keeps DEM and ordinary layers independent and does not duplicate sources',()=>{
 const a={id:'a'} as RasterAsset,b={id:'b'} as RasterAsset;
 let layers=addRaster(addRaster([],a,'image'),b,'dem');
 layers=changeRaster(layers,'b',{visible:false,opacity:.2});
 expect(layers[0]).toMatchObject({asset:a,visible:true,opacity:1});
 expect(layers[1]).toMatchObject({asset:b,visible:false,opacity:.2});
 expect(addRaster(layers,b,'dem')).toHaveLength(2);
});

it('selects only one DEM at a time while retaining imported imagery',async()=>{
 const a={id:'dem-a'} as import('./api').RasterAsset,b={id:'dem-b'} as import('./api').RasterAsset;
 const {selectDEM,hideDEMs}=await import('./rasterLayers');
 const first=selectDEM([],a),second=selectDEM(first,b);
 expect(second).toHaveLength(2);
 expect(second.find(l=>l.asset.id==='dem-a')?.visible).toBe(false);
 expect(second.find(l=>l.asset.id==='dem-b')?.visible).toBe(true);
 expect(hideDEMs(second).every(l=>!l.visible)).toBe(true);
});
