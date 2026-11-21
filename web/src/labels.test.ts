import { describe,expect,it } from 'vitest';
import { DEFAULT_LAYER_STYLE,featureLabel,legendEntries,type LabelFeature } from './labels';
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
  it('replaces ASCII controls and trims text without changing Unicode',()=>{
    const styled=feature({style:enabled('notice'),properties:{notice:' Hello\\nworld\\t世界 '}});
    expect(featureLabel(styled)).toBe('Hello\\nworld\\t世界');
    const ctrl=feature({style:enabled('notice'),properties:{notice:'\\u0001Text'}});
    expect(featureLabel(ctrl)).toBe('\\u0001Text');
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
