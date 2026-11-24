/** The only user-facing map-style choice is the toolbar's Map type select.
 * Providers have different coverage, currency, licensing and native imagery
 * resolution. Zoom past native resolution must never be described as HD.
 */
export type BasemapId=
 'street'|'hot'|'imagery'|'sentinel'|'satellite'|'imagerytopo'|
 'opentopo'|'topo'|'relief'|'global'|'custom'|'blank';
export type BasemapCategory='street'|'imagery'|'terrain'|'other';
export interface BasemapDefinition {
 id:BasemapId;name:string;category:BasemapCategory;
 url?:string;attribution?:string;maxzoom?:number;
 coverage:'global'|'usa'|'configured';note:string;
}
const usgs=(name:string)=>'https://basemap.nationalmap.gov/arcgis/rest/services/'+name+'/MapServer/tile/{z}/{y}/{x}';
export const BASEMAPS:BasemapDefinition[]=[
 {id:'street',name:'Street · OpenStreetMap',category:'street',coverage:'global',
  note:'Global streets and landmarks',url:'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  attribution:'© OpenStreetMap contributors',maxzoom:19},
 {id:'hot',name:'Humanitarian · OSM',category:'street',coverage:'global',
  note:'Distinct cartographic styling for field mapping',
  url:'https://tile.openstreetmap.fr/hot/{z}/{x}/{y}.png',
  attribution:'© OpenStreetMap contributors, Humanitarian OpenStreetMap Team',maxzoom:19},
 {id:'imagery',name:'Satellite HD · Esri World Imagery',category:'imagery',coverage:'global',
  note:'Higher-detail world imagery where tiles exist; coverage and usage rights vary',
  url:'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  attribution:'Sources: Esri, Vantor, Earthstar Geographics and the GIS User Community',maxzoom:19},
 {id:'satellite',name:'Aerial HD · USGS (US)',category:'imagery',coverage:'usa',
  note:'US high-detail orthoimagery',
  url:usgs('USGSImageryOnly'),attribution:'USGS The National Map / USDA orthoimagery',maxzoom:19},
 {id:'sentinel',name:'Satellite · Sentinel-2 mosaic',category:'imagery',coverage:'global',
  note:'Historical 2016 mosaic; not building-resolution imagery',maxzoom:14,
  url:'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg',
  attribution:'<a href="https://cloudless.eox.at/">EOxCloudless</a> · modified Copernicus Sentinel data 2016'},
 {id:'global',name:'Satellite · NASA Blue Marble',category:'imagery',coverage:'global',
  note:'Coarse historical global overview only',maxzoom:8,
  url:'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg',
  attribution:'NASA Earth Observatory / GIBS · Blue Marble historical composite'},
 {id:'opentopo',name:'Topographic · OpenTopoMap',category:'terrain',coverage:'global',
  note:'Contours and topographic symbols; provider availability may vary',maxzoom:17,
  url:'https://tile.opentopomap.org/{z}/{x}/{y}.png',
  attribution:'© OpenStreetMap contributors, SRTM · OpenTopoMap (CC-BY-SA)'},
 {id:'topo',name:'Topographic · USGS (US)',category:'terrain',coverage:'usa',
  note:'US National Map topographic raster',maxzoom:19,
  url:usgs('USGSTopo'),attribution:'USGS The National Map',},
 {id:'imagerytopo',name:'Imagery + contours · USGS (US)',category:'terrain',coverage:'usa',
  note:'US National Map imagery/topographic hybrid',maxzoom:19,
  url:usgs('USGSImageryTopo'),attribution:'USGS The National Map / USDA',},
 {id:'relief',name:'Shaded relief · USGS (US)',category:'terrain',coverage:'usa',
  note:'US 3DEP hillshade for landform interpretation',maxzoom:19,
  url:usgs('USGSShadedReliefOnly'),attribution:'USGS The National Map / 3DEP'},
 {id:'custom',name:'Licensed HD / custom XYZ',category:'other',coverage:'configured',
  note:'Available when an authorized tile source is configured'},
 {id:'blank',name:'Blank canvas',category:'other',coverage:'global',
  note:'Neutral background without external basemap tiles'},
];
export const BASEMAP_GROUPS:Array<{category:BasemapCategory;label:string}>=[
 {category:'street',label:'Street and 2D maps'},
 {category:'imagery',label:'Satellite and aerial imagery'},
 {category:'terrain',label:'Terrain and topographic'},
 {category:'other',label:'Workspace and licensed sources'},
];
export function basemapAvailable(item:BasemapDefinition,custom:CustomBasemap|null){
 return item.id!=='custom'||Boolean(custom);
}
export interface CustomBasemap {url:string;attribution:string;maxzoom:number}
export function customBasemap(url:string,attribution:string,maxzoom:number):CustomBasemap{
 const template=url.trim(),credit=attribution.trim();
 if(!['{z}','{x}','{y}'].every(token=>template.includes(token)))throw Error('Enter an XYZ tile URL containing {z}, {x}, {y}.');
 const parsed=new URL(template.replaceAll('{z}','0').replaceAll('{x}','0').replaceAll('{y}','0'));
 if(parsed.protocol!=='https:'||parsed.username||parsed.password)throw Error('Use an HTTPS tile URL without embedded login credentials.');
 if(!credit||credit.length>300||!Number.isInteger(maxzoom)||maxzoom<1||maxzoom>23)throw Error('Provide source attribution and maximum tile zoom 1–23.');
 return {url:template,attribution:credit,maxzoom};
}
export function defaultCustom():CustomBasemap|null{
 try{if(import.meta.env.VITE_MAPTILER_KEY)return mapTilerImagery(import.meta.env.VITE_MAPTILER_KEY);
 return import.meta.env.VITE_SATELLITE_TILES_URL?customBasemap(import.meta.env.VITE_SATELLITE_TILES_URL,
    import.meta.env.VITE_SATELLITE_ATTRIBUTION||'Configured imagery provider',20):null;}
 catch{return null;}
}
// For users selecting "satellite" in legacy shortcuts, prefer a detailed
// service, not the low-native-resolution 2016 Sentinel composite.
export function preferredSatellite(viewport:[number,number,number,number]|null,licensed:boolean):BasemapId{
 if(licensed)return 'custom';
 if(viewport){
  const [w,s,e,n]=viewport,lon=(w+e)/2,lat=(s+n)/2;
  // The rough continental-US bounds also cover Vancouver and southern
  // British Columbia. Never route that Canadian coast to US-only imagery.
  if(lon>=-125&&lon<=-66&&lat>=24&&lat<50&&
     !(lon<-120&&lat>=48.8))return 'satellite';
 }
 return 'imagery';
}
export function mapTilerImagery(key:string):CustomBasemap{
 if(!key.trim())throw Error('Enter a restricted MapTiler browser API key.');
 return customBasemap('https://api.maptiler.com/tiles/satellite-v2/{z}/{x}/{y}.jpg?key='+encodeURIComponent(key.trim()),'© MapTiler, imagery providers',22);
}
