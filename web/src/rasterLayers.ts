import type {RasterAsset} from './api';
export interface RasterLayerView {asset:RasterAsset;visible:boolean;opacity:number;kind:'image'|'dem'}
export function addRaster(layers:RasterLayerView[],asset:RasterAsset,kind:RasterLayerView['kind']){
 return layers.some(l=>l.asset.id===asset.id)?layers.map(l=>l.asset.id===asset.id?{...l,visible:true}:l):
 [...layers,{asset,visible:true,opacity:kind==='dem'?.55:1,kind}];
}
export function changeRaster(layers:RasterLayerView[],id:string,update:Partial<Pick<RasterLayerView,'visible'|'opacity'>>){
 return layers.map(l=>l.asset.id===id?{...l,...update,opacity:update.opacity===undefined?l.opacity:Math.max(0,Math.min(1,update.opacity))}:l);
}

/** Make exactly one imported elevation surface visible without deleting prior source files. */
export function selectDEM(layers:RasterLayerView[],asset:RasterAsset){
 return addRaster(layers.map(l=>l.kind==='dem'?{...l,visible:false}:l),asset,'dem');
}
export function hideDEMs(layers:RasterLayerView[]){
 return layers.map(l=>l.kind==='dem'?{...l,visible:false}:l);
}
