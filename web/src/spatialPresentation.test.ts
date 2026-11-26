import {expect,it} from 'vitest';
import {recommendSpatialEpsg,spatialMetricLabel,spatialMetricValue} from './spatialPresentation';
const point=(x:number,y:number):GeoJSON.Point=>({type:'Point',coordinates:[x,y]});
it('recommends a local metric CRS only within one UTM area',()=>{
 expect(recommendSpatialEpsg([point(120.08,36.35)])).toBe(32651);
 expect(recommendSpatialEpsg([point(-83,40)])).toBe(32617);
 expect(recommendSpatialEpsg([point(151,-33)])).toBe(32756);
 expect(recommendSpatialEpsg([point(119,36),point(121,36)])).toBeNull();
 expect(recommendSpatialEpsg([point(120,85)])).toBeNull();
 expect(recommendSpatialEpsg([point(120,1),point(120,-1)])).toBeNull();
 expect(recommendSpatialEpsg([null])).toBeNull();
});
it('formats scientific result names and physical units without dropping small values',()=>{
 expect(spatialMetricLabel('study_area_m2')).toBe('Study area');
 expect(spatialMetricValue('study_area_m2',11530000)).toBe('11.53 km²');
 expect(spatialMetricValue('distance_m',1500)).toBe('1.5 km');
 expect(spatialMetricValue('count',1000000)).toBe('1,000,000');
 expect(spatialMetricValue('p_value',0.0000000123)).toBe('1.2300e-8');
});
