export type BasemapId='street'|'satellite'|'global'|'topo'|'relief'|'custom'|'blank';
const usgs=(name:string)=>'https://basemap.nationalmap.gov/arcgis/rest/services/'+name+'/MapServer/tile/{z}/{y}/{x}';
export const BASEMAPS:Array<{id:BasemapId;name:string;url?:string;attribution?:string;maxzoom?:number}>= [
 {id:'street',name:'Street · OSM',url:'https://tile.openstreetmap.org/{z}/{x}/{y}.png',attribution:'© OpenStreetMap contributors',maxzoom:19},
 {id:'satellite',name:'Aerial · USGS (US)',url:usgs('USGSImageryOnly'),attribution:'USDA, USGS The National Map: Orthoimagery',maxzoom:19},
 {id:'global',name:'Satellite · NASA (global)',url:'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg',attribution:'NASA Earth Observatory / GIBS · Blue Marble historical composite',maxzoom:8},
 {id:'topo',name:'Topographic · USGS (US)',url:usgs('USGSTopo'),attribution:'USGS The National Map',maxzoom:19},
 {id:'relief',name:'Shaded relief · USGS (US)',url:usgs('USGSShadedReliefOnly'),attribution:'USGS The National Map / 3DEP',maxzoom:19},
 ...(import.meta.env.VITE_SATELLITE_TILES_URL?[{id:'custom' as const,name:'Configured imagery',url:import.meta.env.VITE_SATELLITE_TILES_URL,attribution:import.meta.env.VITE_SATELLITE_ATTRIBUTION||'Configured imagery provider',maxzoom:20}]:[]),
 {id:'blank',name:'Blank canvas'},
];
