export type BasemapId='street'|'sentinel'|'satellite'|'global'|'topo'|'relief'|'custom'|'blank';
const usgs=(name:string)=>'https://basemap.nationalmap.gov/arcgis/rest/services/'+name+'/MapServer/tile/{z}/{y}/{x}';
export const BASEMAPS:Array<{id:BasemapId;name:string;url?:string;attribution?:string;maxzoom?:number}>= [
 {id:'street',name:'Street · OSM',url:'https://tile.openstreetmap.org/{z}/{x}/{y}.png',attribution:'© OpenStreetMap contributors',maxzoom:19},
 {id:'sentinel',name:'Satellite · Sentinel-2 global (2016, 10 m)',url:'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg',
   attribution:'<a href="https://cloudless.eox.at/">EOxCloudless</a> by <a href="https://eox.at/">EOX IT Services GmbH</a> (Contains modified Copernicus Sentinel data 2016)',maxzoom:14},
 {id:'satellite',name:'Aerial · USGS (US only)',url:usgs('USGSImageryOnly'),attribution:'USDA, USGS The National Map: Orthoimagery',maxzoom:19},
 {id:'global',name:'Satellite · NASA overview (global)',url:'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg',attribution:'NASA Earth Observatory / GIBS · Blue Marble historical composite',maxzoom:8},
 {id:'topo',name:'Topographic · USGS (US)',url:usgs('USGSTopo'),attribution:'USGS The National Map',maxzoom:19},
 {id:'relief',name:'Shaded relief · USGS (US)',url:usgs('USGSShadedReliefOnly'),attribution:'USGS The National Map / 3DEP',maxzoom:19},
 {id:'custom',name:'Licensed custom imagery'},
 {id:'blank',name:'Blank canvas'},
];

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

// The global Sentinel composite is a fallback, not building-scale imagery.
export function preferredSatellite(viewport:[number,number,number,number]|null,licensed:boolean):BasemapId{
 if(licensed)return 'custom';
 if(viewport){
  const [w,s,e,n]=viewport,lon=(w+e)/2,lat=(s+n)/2;
  if(lon>=-125&&lon<=-66&&lat>=24&&lat<=50)return 'satellite';
 }
 return 'sentinel';
}
export function mapTilerImagery(key:string):CustomBasemap{
 if(!key.trim())throw Error('Enter a restricted MapTiler browser API key.');
 return customBasemap('https://api.maptiler.com/tiles/satellite-v2/{z}/{x}/{y}.jpg?key='+encodeURIComponent(key.trim()),'© MapTiler, imagery providers',22);
}
