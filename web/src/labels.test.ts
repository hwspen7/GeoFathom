import { describe,expect,it } from 'vitest';
import { DEFAULT_LAYER_STYLE,featureLabel,featureColor,legendEntries,type LabelFeature } from './labels';
import type {Measurement} from './api';

const measurements:Measurement={
  geometry_type:'Polygon',area_m2:12345.678,area_km2:.012345678,
  perimeter_m:400,length_m:null,bounds:[0,0,.1,.1],
  coordinate_count:5,method:'WGS84 ellipsoidal geodesic',note:'',
};
const base:LabelFeature={
  name:'Building A',source:'OSM',
  properties:{height:150,category:'industrial',active:true,blank:null},
  measurement:measurements,
  style:structuredClone(DEFAULT_LAYER_STYLE),
};
function feature(overrides:Partial<LabelFeature>={}):LabelFeature{
  return {...base,style:structuredClone(DEFAULT_LAYER_STYLE),...overrides};
}
function enabled(field='name'){
  const style=structuredClone(DEFAULT_LAYER_STYLE);
  style.labels.enabled=true;style.labels.field=field;
  return style;
}

describe('GIS map layer labelling from safe attributes',()=>{
  it('is off by default but explicit user notes are displayed',()=>{
    expect(featureLabel(feature())).toBe('');
    expect(featureLabel(feature({properties:{annotation:true,annotation_text:'Check boundary'}})))
      .toBe('Check boundary');
  });
  it.each([
    ['name','Building A'],['source','OSM'],['height','150'],
    ['category','industrial'],['active','true'],
    ['@area_m2','12,345.68 m²'],['@length_m','400 m'],
  ])('formats %s field reliably', (field,wanted)=>{
    expect(featureLabel(feature({style:enabled(field)}))).toBe(wanted);
  });
  it('does not fabricate area or distance for a point feature',()=>{
    const point={...measurements,area_m2:null,perimeter_m:null,length_m:null};
    expect(featureLabel(feature({style:enabled('@area_m2'),measurement:point}))).toBe('');
    expect(featureLabel(feature({style:enabled('@length_m'),measurement:point}))).toBe('');
  });
  it('does not stringify objects or missing values',()=>{
    expect(featureLabel(feature({style:enabled('object'),properties:{object:{x:1}}}))).toBe('');
    expect(featureLabel(feature({style:enabled('absent')}))).toBe('');
  });
  it('uses the configured min/max zoom thresholds inclusively',()=>{
    const style=enabled();style.labels.min_zoom=10;style.labels.max_zoom=16;
    expect(featureLabel(feature({style}),9.999)).toBe('');
    expect(featureLabel(feature({style}),10)).toBe('Building A');
    expect(featureLabel(feature({style}),16)).toBe('Building A');
    expect(featureLabel(feature({style}),17)).toBe('');
    expect(featureLabel(feature({style}),Number.NaN)).toBe('');
  });
  it('does not execute HTML embedded in user labels and truncates long text',()=>{
    const text='<img src=x onerror=alert(1)> <script>alert(1)</script>';
    const styled=feature({style:enabled('code'),properties:{code:text}});
    // Literal text is passed to the map renderer, never to innerHTML.
    expect(featureLabel(styled)).toBe(text);
    expect(featureLabel(feature({
      properties:{annotation:true,annotation_text:'測'.repeat(130)},
    })).length).toBe(120);
  });
  it('replaces genuine ASCII controls and preserves Unicode letters',()=>{
    const styled=feature({
      style:enabled('notice'),
      properties:{notice:' Hello'+String.fromCharCode(10)+'world'+
        String.fromCharCode(9)+'世界 '},
    });
    expect(featureLabel(styled)).toBe('Hello world 世界');
    const ctrl=feature({style:enabled('notice'),
      properties:{notice:String.fromCharCode(1)+'Text'}});
    expect(featureLabel(ctrl)).toBe('Text');
  });
  it('displays free-form annotation before attribute fields',()=>{
    const note=feature({style:enabled('category'),
      properties:{annotation:true,annotation_text:'Water sampling point',category:'Industrial'}});
    expect(featureLabel(note)).toBe('Water sampling point');
  });
});

describe('GIS map legend',()=>{
  it('includes only visible layers with their saved colors and label state',()=>{
    const layers=[
      {id:'visible',name:'Buildings',color:'#aa1122',visible:1,style:enabled()},
      {id:'hidden',name:'Private',color:'#001122',visible:0,style:enabled()},
    ];
    const legend=legendEntries(layers);
    expect(legend).toHaveLength(1);
    expect(legend[0]).toMatchObject({name:'Buildings',color:'#aa1122',labels:true});
  });
  it('does not mutate style definitions',()=>{
    const data=feature({style:enabled('height')});
    const before=structuredClone(data);
    for(let i=0;i<1000;i++)featureLabel(data,15);
    expect(data).toEqual(before);
  });
});


describe('QGIS-style categorized symbology and legend classes',()=>{
  const style=structuredClone(DEFAULT_LAYER_STYLE);
  style.symbol.category_field='landuse';
  style.symbol.category_colors={
    residential:'#ec7e39',
    industrial:'#336799',
  };
  it('maps attribute values to stable colors and retains fallback',()=>{
    expect(featureColor({
      name:'Parcel',source:'Manual',properties:{landuse:'residential'},
    },style,'#aaaaaa')).toBe('#ec7e39');
    expect(featureColor({
      name:'Parcel',source:'Manual',properties:{landuse:'industrial'},
    },style,'#aaaaaa')).toBe('#336799');
    expect(featureColor({
      name:'Parcel',source:'Manual',properties:{landuse:'other'},
    },style,'#aaaaaa')).toBe('#aaaaaa');
  });
  it('uses only exact keys and does not trust object prototype lookup',()=>{
    const obj={__proto__:null} as Record<string,unknown>;
    obj.landuse='__proto__';
    const result=featureColor({name:'x',source:'y',properties:obj},style,'#abcabc');
    expect(result).toBe('#abcabc');
  });
  it('lists only active categories present in visible features',()=>{
    const layers=[{id:'zones',name:'Zones',color:'#345678',visible:1,style}];
    const items=[
      {layer_id:'zones',name:'A',source:'Manual',properties:{landuse:'residential'}},
      {layer_id:'zones',name:'B',source:'Manual',properties:{landuse:'residential'}},
      {layer_id:'zones',name:'C',source:'Manual',properties:{landuse:'other'}},
    ];
    const legend=legendEntries(layers,items);
    expect(legend).toHaveLength(2);
    expect(legend[1].color).toBe('#ec7e39');
    expect(legend.map(e=>e.name)).not.toContain('  industrial');
  });
});


describe('conditional attribute label rules',()=>{
  const map=structuredClone(DEFAULT_LAYER_STYLE);
  map.labels.enabled=true;
  map.labels.rule_field='height';
  map.labels.rule_operator='gte';
  map.labels.rule_value='30';
  it('shows only qualifying numeric features',()=>{
    expect(featureLabel(feature({style:map,properties:{height:18}}))).toBe('');
    expect(featureLabel(feature({style:map,properties:{height:34}}))).toBe('Building A');
  });
  it('supports equals, substring and exists rules without eval',()=>{
    const style=structuredClone(map);
    style.labels.rule_field='category';
    style.labels.rule_operator='equals';
    style.labels.rule_value='industrial';
    expect(featureLabel(feature({style}))).toBe('Building A');
    style.labels.rule_operator='contains';
    style.labels.rule_value='dust';
    expect(featureLabel(feature({style}))).toBe('Building A');
    style.labels.rule_operator='exists';
    expect(featureLabel(feature({style}))).toBe('Building A');
    style.labels.rule_field='missing';
    expect(featureLabel(feature({style}))).toBe('');
  });
  it('standalone note overrides layer labeling predicate',()=>{
    const style=structuredClone(map);
    expect(featureLabel(feature({style,properties:{annotation:true,
      annotation_text:'Note',height:5}}))).toBe('Note');
  });
});
