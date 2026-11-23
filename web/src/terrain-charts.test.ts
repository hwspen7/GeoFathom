import {expect,it} from 'vitest';import {profileSegments,hypsometricPoints,profileGrades} from './TerrainCharts';
it('keeps distance spacing and does not bridge nodata',()=>{
 const lines=profileSegments([{distance_m:0,elevation_m:10},{distance_m:25,elevation_m:20},{distance_m:50,elevation_m:null},{distance_m:100,elevation_m:30}],100,10,30);
 expect(lines).toEqual(['42.00,125.00 113.50,72.50','328.00,20.00']);
});

it('constructs hypsometry from actual cumulative valid-cell percentages',()=>{
 const bins=[
  {lower_m:0,upper_m:50,cells:10,area_m2:100,cumulative_pct:50},
  {lower_m:50,upper_m:100,cells:10,area_m2:100,cumulative_pct:100},
 ];
 expect(hypsometricPoints(bins)).toEqual([
  {area_above:0,relative_elevation:1},
  {area_above:.5,relative_elevation:.5},
  {area_above:1,relative_elevation:0},
 ]);
 expect(hypsometricPoints([])).toEqual([]);
});
it('calculates profile grades without crossing nodata or duplicate stations',()=>{
 expect(profileGrades([
  {distance_m:0,elevation_m:100},
  {distance_m:10,elevation_m:110},
  {distance_m:20,elevation_m:null},
  {distance_m:30,elevation_m:150},
  {distance_m:50,elevation_m:130},
  {distance_m:50,elevation_m:140},
 ])).toEqual([
  {distance_m:5,grade_pct:100},
  {distance_m:40,grade_pct:-100},
 ]);
});
