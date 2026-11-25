import type {ScientificRasterInput,SpatialScienceResult,TerrainRasterLayer} from './api';

// Products are scientific inputs, not map layers. A hidden or undisplayed
// raster remains available until its owner removes or replaces it.
export type ScienceModule='Terrain'|'Spatial'|'Temporal'|'Sensing';
export type ScienceRaster=ScientificRasterInput&{id:string;module:ScienceModule;unit:string};
export type ScienceRegistry=Partial<Record<ScienceModule,ScienceRaster[]>>;
export function terrainSource(layer:TerrainRasterLayer):ScienceRaster{
 return {id:'terrain:'+layer.id,module:'Terrain',name:layer.title,data:layer.raster.geotiff,product_id:layer.raster.product_id,unit:layer.raster.unit??'',band:1};
}
export function resultSource(module:Exclude<ScienceModule,'Terrain'>,result:SpatialScienceResult,title:string):ScienceRaster|null{
 const r=result.raster;
 return r?{id:module+':'+r.sha256,module,name:title,data:r.data,unit:r.unit,band:r.band??1}:null;
}
export function registrySources(registry:ScienceRegistry,exclude?:ScienceModule):ScienceRaster[]{
 return (['Terrain','Spatial','Temporal','Sensing'] as const).filter(m=>m!==exclude).flatMap(m=>registry[m]??[]);
}
