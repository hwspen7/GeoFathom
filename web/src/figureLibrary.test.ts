import {describe,expect,it} from 'vitest';
import {availableFigures,defaultFigure,figureTable,localPlotData,makeFigure,tableCSV,metricUnit} from './figureLibrary';
import {pythonFigure,withPNGDpi} from './figureExport';
import type {PlotData} from './api';
import type {PersistedTerrainResult} from './terrainResultStore';
import {plotFixture} from '../testFixtures/figureData';


describe('scientific figure recipes',()=>{
 it('offers only graph families supported by the actual numerical data',()=>{
  const figures=availableFigures(plotFixture).map(f=>f.id);
  expect(figures).toEqual(expect.arrayContaining(['histogram','cdf','exceedance','box','qq','scatter','joint_density']));
  expect(figures).not.toContain('rose');
  const nominal={...plotFixture,kind:'categorical' as const,histograms:undefined,cdf:undefined,box:undefined,quantiles:undefined,normal_qq:undefined,joint:undefined};
  expect(availableFigures(nominal).map(f=>f.id)).toEqual(['class_bar','class_dot','metrics']);
 });
 it('exports exact bin edges, area, density and units rather than color legend estimates',()=>{
  const settings=defaultFigure(plotFixture),table=figureTable(plotFixture,settings);
  expect(table.columns).toContain('lower_deg');expect(table.rows[0]).toEqual([0,15,7.5,2,200,50,1/30,50]);
  const csv=tableCSV(table);expect(csv).toContain('0,15,7.5,2,200,50');
  const exceedance=figureTable(plotFixture,{...settings,kind:'exceedance'});expect(exceedance.rows.at(-1)?.[3]).toBe(0);
  const qq=figureTable(plotFixture,{...settings,kind:'qq'});expect(qq.rows[0]).toEqual([-1.28,3,.1]);
 });
 it('generates finite vector geometry for every supported template and appearance',()=>{
  for(const recipe of availableFigures(plotFixture))for(const palette of ['mono','blue','earth'] as const){
   const scene=makeFigure(plotFixture,{...defaultFigure(plotFixture),kind:recipe.id,palette});
   expect(scene.error).toBeUndefined();expect(scene.primitives.length).toBeGreaterThan(10);
   const walk=(v:unknown):void=>{if(typeof v==='number')expect(Number.isFinite(v)).toBe(true);else if(Array.isArray(v))v.forEach(walk);else if(v&&typeof v==='object')Object.values(v).forEach(walk);};walk(scene);
  }
 });
 it('preserves profile gaps and derives grade only from adjacent valid samples',()=>{
  const record={profile:{samples:[{distance_m:0,elevation_m:10},{distance_m:10,elevation_m:12},{distance_m:20,elevation_m:null},{distance_m:30,elevation_m:18},{distance_m:40,elevation_m:20}]}} as unknown as PersistedTerrainResult;
  const data=localPlotData(record)!;const settings=defaultFigure(data);
  expect(figureTable(data,{...settings,kind:'grade'}).rows).toEqual([[0,null],[5,20],[15,null],[25,null],[35,20]]);
  const scene=makeFigure(data,settings);expect(scene.primitives.filter(p=>p.kind==='polyline')).toHaveLength(2);
 });
 it('does not mix arbitrary metrics with different physical units on one axis',()=>{
  const table=figureTable(plotFixture,{...defaultFigure(plotFixture),kind:'metrics',metric_keys:['cut_m3','product_valid_cells','fill_m3']});
  expect(table.rows).toEqual([['cut_m3',100],['fill_m3',50]]);expect(metricUnit('covered_grid_area_m2')).toBe('m2');
 });
 it('refuses invalid logarithmic bounds and explains omitted non-positive points',()=>{
  const settings=defaultFigure(plotFixture);
  expect(makeFigure(plotFixture,{...settings,kind:'box',y_log:true}).error).toBeTruthy();
  expect(makeFigure(plotFixture,{...settings,x_log:true}).error).toBeTruthy();
  expect(makeFigure(plotFixture,{...settings,kind:'scatter',y_log:true}).note).toContain('omit non-positive');
  const cdf=makeFigure(plotFixture,{...settings,kind:'cdf',x_log:true});
  expect(cdf.primitives.flatMap(p=>p.points??[]).flat().every(Number.isFinite)).toBe(true);
 });
 it('renders directional frequencies with area-proportional polar sectors',()=>{
  const data:PlotData={schema:'test',kind:'directional',quantity:'Aspect',unit:'degree',valid_cells:5,directional_cells:4,flat_cells:1,cell_area_m2:100,classes:[],notes:[],roses:{'16':Array.from({length:16},(_,i)=>({bearing_deg:22.5*i,cells:i===0?4:0,percent:i===0?100:0,area_m2:i===0?400:0}))}};
  const settings=defaultFigure(data);const scene=makeFigure(data,settings);
  expect(settings.kind).toBe('rose');expect(scene.primitives.filter(p=>p.kind==='polygon')).toHaveLength(16);expect(scene.note).toContain('n = 4');
 });
 it('CSV labels are quoted and cannot execute as spreadsheet formulas',()=>{
  const csv=tableCSV({columns:['class','value'],rows:[['=SUM(1,2)',1],['a"b',2]],x_label:'',y_label:'',unit:''});
  expect(csv).toContain('"\'=SUM(1,2)"');expect(csv).toContain('"a""b"');
 });
 it('embeds data in generated Python as base64 rather than executable string interpolation',()=>{
  const settings={...defaultFigure(plotFixture),title:"''' ; __import__('os').system('false') #"};
  const script=pythonFigure(figureTable(plotFixture,settings),settings,plotFixture,{name:'厦门岛'});
  expect(script).not.toContain(settings.title);expect(script).toContain('base64.b64decode');expect(script).toContain('fig.savefig("research-figure.pdf")');
 });
 it('writes one valid physical-resolution PNG chunk and replaces existing metadata',()=>{
  const raw=Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII='),c=>c.charCodeAt(0));
  const output=withPNGDpi(withPNGDpi(raw,300),600);let offset=8,found=0;
  while(offset<output.length){const view=new DataView(output.buffer,offset);const n=view.getUint32(0),name=String.fromCharCode(...output.slice(offset+4,offset+8));if(name==='pHYs'){found++;expect(view.getUint32(8)).toBe(Math.round(600/.0254));}offset+=n+12;}
  expect(found).toBe(1);expect(()=>withPNGDpi(new Uint8Array(),300)).toThrow();
 });
 it('uses a quartile-matched Q–Q reference for skewed populations',()=>{
  const data={...plotFixture,summary:{...plotFixture.summary!,q1:1,median:2,q3:7}};
  const scene=makeFigure(data,{...defaultFigure(data),kind:'qq'});
  const reference=scene.primitives.find(p=>p.kind==='line'&&p.dashed)!;
  expect(reference).toBeTruthy();
  const xZero=(115+855)/2;
  const referenceAtZero=reference.y!+(reference.y2!-reference.y!)*(xZero-reference.x!)/(reference.x2!-reference.x!);
  // The fitted quartile line crosses x=0 at (q1+q3)/2=4, on y=[0,30].
  expect(referenceAtZero).toBeCloseTo(470-395*4/30,8);
 });
 it('shows isolated valid profile stations without bridging NoData gaps',()=>{
  const data:PlotData={schema:'test',kind:'profile',quantity:'Elevation',unit:'m',valid_cells:1,cell_area_m2:0,classes:[],notes:[],profiles:[{name:'Sparse',points:[{x:0,y:null},{x:10,y:5},{x:20,y:null}]}]};
  const scene=makeFigure(data,defaultFigure(data));
  expect(scene.primitives.filter(p=>p.kind==='circle')).toHaveLength(1);
  expect(scene.primitives.filter(p=>p.kind==='polyline')).toHaveLength(0);
 });

 it('draws the full CDF jump for a constant population',()=>{
  const data={...plotFixture,cdf:[{value:5,cells_le:4,percent_le:100}]};
  const scene=makeFigure(data,{...defaultFigure(data),kind:'cdf'});
  const line=scene.primitives.find(p=>p.kind==='polyline')!;
  expect(line.points!.some((point,i,array)=>i>0&&point[0]===array[i-1][0]&&point[1]!==array[i-1][1])).toBe(true);
  expect(Math.max(...line.points!.map(p=>p[1]))).toBe(470);
  expect(Math.min(...line.points!.map(p=>p[1]))).toBe(75);
 });

 it('preserves native legacy bin counts without offering undefined density estimates',()=>{
  const legacy:PlotData={schema:'test',kind:'binned',quantity:'Elevation',unit:'m',valid_cells:4,cell_area_m2:100,classes:[],notes:[],histograms:{'1':[{lower:100,upper:100,midpoint:100,cells:4,area_m2:400,percent:100,density:null,cumulative_pct:100}]}};
  expect(defaultFigure(legacy).bins).toBe(1);
  expect(availableFigures(legacy).map(r=>r.id)).toEqual(['histogram']);
 });

});
