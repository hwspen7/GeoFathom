import type {SpatialScienceResult} from './api';

// Only recommend a local UTM when every vertex lies within the same standard
// EPSG area of use. Cross-zone, polar and cross-equator studies need an explicit CRS.
export function recommendSpatialEpsg(geometries:readonly (GeoJSON.Geometry|null)[]):number|null{
 let zone:number|null=null,north:boolean|null=null,valid=true,count=0;
 function visit(value:unknown){
   if(!Array.isArray(value)){valid=false;return;}
   if(typeof value[0]==='number'){
     const [lon,lat]=value;
     if(!Number.isFinite(lon)||!Number.isFinite(lat)||lon< -180||lon>180||lat< -80||lat>84){valid=false;return;}
     const next=Math.min(60,Math.floor((lon+180)/6)+1),hemi=lat>=0;
     if(zone!==null&&(zone!==next||north!==hemi))valid=false;
     zone=next;north=hemi;count++;
   }else value.forEach(visit);
 }
 function walk(g:GeoJSON.Geometry|null){
   if(!g)return;
   if(g.type==='GeometryCollection')g.geometries.forEach(walk);
   else visit(g.coordinates);
 }
 geometries.forEach(walk);
 return valid&&count&&zone!==null?(north?32600:32700)+zone:null;
}
const suffix=/_((?:km|m)[23]|ha|km|m|deg|pct|percent|seconds|ms|s)$/;
const units:Record<string,string>={km2:'km²',km3:'km³',m2:'m²',m3:'m³',deg:'°',pct:'%',percent:'%',seconds:'s'};
export function spatialMetricLabel(key:string){
 const base=key.replace(suffix,'').replaceAll('_',' ');
 return base?base[0].toUpperCase()+base.slice(1):'';
}
function numberText(value:number){
 if(!Number.isFinite(value))return '—';
 if(value!==0&&Math.abs(value)<1e-6)return value.toExponential(4);
 return value.toLocaleString('en-US',{maximumSignificantDigits:6});
}
export function spatialMetricValue(key:string,value:number){
 let unit=suffix.exec(key)?.[1]??'';
 if(unit==='m2'&&Math.abs(value)>=1e6){value/=1e6;unit='km2';}
 else if(unit==='m'&&Math.abs(value)>=1000){value/=1000;unit='km';}
 else if(unit==='m3'&&Math.abs(value)>=1e9){value/=1e9;unit='km3';}
 const text=numberText(value),symbol=units[unit]??unit;
 return text+(symbol?(symbol==='°'||symbol==='%'?'':' ')+symbol:'');
}
export function spatialResultMetrics(result:SpatialScienceResult):Array<[string,number]>{
 const metrics:Array<[string,number]>=[];
 if(result.features)metrics.push(['Features',result.features.features.length]);
 if(result.columns.length||result.rows.length)metrics.push(['Records',result.rows.length]);
 for(const [key,value] of Object.entries(result.receipt.metrics)){
   if(typeof value==='number'&&Number.isFinite(value))metrics.push([key,value]);
 }
 return metrics;
}
