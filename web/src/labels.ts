/** Safe plain-text label formatting for vector features and standalone notes.

QGIS/ArcGIS-style field-based labelling, with authoritative geodesic
measurements from the existing FastAPI result. No HTML or code expressions
are evaluated from feature properties.
*/
import type { Measurement,LayerStyle } from './api';

export interface LabelFeature {
  name:string;
  source:string;
  properties:Record<string,unknown>;
  measurement:Measurement;
  style:LayerStyle;
}
export const DEFAULT_LAYER_STYLE:LayerStyle={
  labels:{
    enabled:false,field:'name',font_size:12,text_color:'#183954',
    halo_color:'#ffffff',halo_width:1.5,min_zoom:0,max_zoom:24,
    allow_overlap:false,
  },
  symbol:{
    fill_opacity:.17,line_width:3,point_radius:5,stroke_color:'#ffffff',
    category_field:'',category_colors:{},
  },
};

const fmt = new Intl.NumberFormat('en-US',{maximumFractionDigits:2});
const MAX_TEXT=120;

export function featureLabel(feature:LabelFeature,zoom=14):string {
  const {name,source,properties,measurement,style}=feature;
  if(!Number.isFinite(zoom))return '';
  const labels=style.labels;
  if(zoom<labels.min_zoom || zoom>labels.max_zoom)return '';
  let value:unknown;
  // User-created annotation always displays when its parent layer is visible.
  // The auto-label toggle only affects computed field-based labels.
  if(properties.annotation===true){
    value=properties.annotation_text;
  }else{
    if(!labels.enabled)return '';
    const field=labels.field.trim();
    if(field==='name')value=name;
    else if(field==='source')value=source;
    else if(field==='@area_m2'){
      const n=measurement.area_m2;
      value=n===null||!Number.isFinite(n)?'':fmt.format(n)+' m²';
    }else if(field==='@length_m'){
      const n=measurement.length_m??measurement.perimeter_m;
      value=n===null||!Number.isFinite(n)?'':fmt.format(n)+' m';
    }else value=properties[field];
  }
  if(value===null||value===undefined || typeof value==='object')return '';
  if(typeof value==='number'&&!Number.isFinite(value))return '';
  const text=String(value).replace(/[\u0000-\u001f\u007f]/g,' ').trim();
  if(!text || text==='[object Object]')return '';
  return [...text].slice(0,MAX_TEXT).join('');
}


export function featureColor(
  feature:{name:string;source:string;properties:Record<string,unknown>},
  style:LayerStyle,defaultColor:string,
):string {
  const field=style.symbol.category_field;
  if(!field)return defaultColor;
  const value=field==='name'?feature.name:field==='source'?feature.source:
    feature.properties[field];
  if(typeof value!=='string'&&typeof value!=='number'&&typeof value!=='boolean')
    return defaultColor;
  const category=String(value);
  return Object.prototype.hasOwnProperty.call(style.symbol.category_colors,category)
    ? style.symbol.category_colors[category] : defaultColor;
}

export function legendEntries(
  layers:Array<{id:string;name:string;color:string;visible:number|boolean;style:LayerStyle}>,
  features:Array<{layer_id:string;properties:Record<string,unknown>;name:string;source:string}>=[],
):Array<{id:string;name:string;color:string;lineWidth:number;opacity:number;labels:boolean}> {
  return layers.filter(layer=>Boolean(layer.visible)).flatMap(layer=>{
    const core={
      lineWidth:layer.style.symbol.line_width,
      opacity:layer.style.symbol.fill_opacity,
      labels:layer.style.labels.enabled,
    };
    if(layer.style.symbol.category_field && Object.keys(layer.style.symbol.category_colors).length){
      return [
        {id:layer.id,name:layer.name,color:layer.color,...core},
        ...Object.entries(layer.style.symbol.category_colors).filter(([key])=>
          features.some(feature=>feature.layer_id===layer.id &&
            (layer.style.symbol.category_field==='name'?feature.name:
             layer.style.symbol.category_field==='source'?feature.source:
             String(feature.properties[layer.style.symbol.category_field]))===key,
          )).map(([key,color])=>({
          id:layer.id+':'+key,name:'  '+key,color,...core,
        })),
      ];
    }
    return [{id:layer.id,name:layer.name,color:layer.color,...core}];
  });
}
