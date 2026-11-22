import {expect,it} from 'vitest';import {profileSegments} from './TerrainCharts';
it('keeps distance spacing and does not bridge nodata',()=>{
 const lines=profileSegments([{distance_m:0,elevation_m:10},{distance_m:25,elevation_m:20},{distance_m:50,elevation_m:null},{distance_m:100,elevation_m:30}],100,10,30);
 expect(lines).toEqual(['42.00,125.00 113.50,72.50','328.00,20.00']);
});
