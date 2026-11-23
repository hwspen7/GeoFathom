import {expect,it} from 'vitest';import {profileSegments,hypsometricPoints,profileGrades,terrainClassStatistics,terrainClassesCsv} from './TerrainCharts';
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

it('computes exact class area, percent and cumulative totals with nodata excluded',()=>{
 const classes=[{label:'0–5°',color:'#123456',cells:3},
  {label:'5–10°',color:'#654321',cells:1},{label:'No observations',color:'#aaaaaa',cells:0}];
 const rows=terrainClassStatistics(classes,100);
 expect(rows.map(r=>r.sharePct)).toEqual([75,25,0]);
 expect(rows.map(r=>r.cumulativePct)).toEqual([75,100,100]);
 expect(rows.map(r=>r.areaM2)).toEqual([300,100,0]);
 expect(terrainClassesCsv(classes,100).split('\\n')).toHaveLength(5);
 const empty=terrainClassStatistics([{label:'empty',color:'#ffffff',cells:0}],100);
 expect(empty[0].cumulativePct).toBe(0);
});
