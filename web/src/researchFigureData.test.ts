import {expect,it} from 'vitest';
import {researchFigureData,researchDistributionData} from './researchFigureData';
import {availableFigures,defaultFigure,figureTable,makeFigure} from './figureLibrary';
import type {ResearchResult} from './api';
const result={runs:[{label:'Baseline'},{label:'A'},{label:'B'}],products:[],metric_table:[{metric:'cut_m3',values:[100,40,20],deltas:[0,-60,null],relative_pct:[0,-60,null]}],sensitivity:[{parameter:'reference',value:10,metrics:{cut_m3:100},derivatives:{}},{parameter:'reference',value:20,metrics:{cut_m3:40},derivatives:{cut_m3:-6}}],uncertainty:{coverage:.95,warning:'Conditional model',metrics:{cut_m3:{baseline:100,mean:105,low:80,high:120}},realizations:{cut_m3:[80,100,110,120]}}} as unknown as ResearchResult;
it('preserves undefined deltas and physical units in the same scene and CSV table',()=>{
 const data=researchFigureData(result,'cut_m3','delta')!;
 expect(data.unit).toBe('m3');expect(availableFigures(data).map(r=>r.id)).toContain('experiment_dot');
 const table=figureTable(data,defaultFigure(data));expect(table.rows.map(r=>r[2])).toEqual([0,-60,null]);
 expect(makeFigure(data,defaultFigure(data)).error).toBeUndefined();
});
it('plots actual numeric response values and excludes undefined secants',()=>{
 const data=researchFigureData(result,'cut_m3','derivative')!;
 expect(figureTable(data,defaultFigure(data)).rows.map(r=>r[2])).toEqual([null,-6]);
 expect(defaultFigure(data).kind).toBe('experiment_line');
});
it('retains empirical model endpoints and the deterministic baseline',()=>{
 const data=researchFigureData(result,'cut_m3','interval')!;
 expect(figureTable(data,defaultFigure(data)).rows[0]).toEqual(['Monte Carlo',0,105,80,120,100]);
 expect(makeFigure(data,defaultFigure(data)).primitives.some(p=>p.kind==='circle'&&p.fill==='#ffffff')).toBe(true);
});
it('computes exact distribution tables from actual realizations and no geographic area',()=>{
 const data=researchFigureData(result,'cut_m3','realizations')!;
 expect(data.histograms!['40'].reduce((s,b)=>s+b.cells,0)).toBe(4);
 expect(data.summary?.median).toBe(105);expect(data.cdf?.at(-1)?.percent_le).toBe(100);
 const table=figureTable(data,defaultFigure(data));expect(table.rows.every(r=>r[4]===null)).toBe(true);
 expect(table.y_label).toBe('Realizations (%)');
});

it('compares separate scenario populations without inventing pooled quartiles',()=>{
 const data=researchFigureData(result,'cut_m3','realizations')!;
 const comparison=researchDistributionData({...result,products:[{name:'Baseline',role:'baseline',plot_data:data},{name:'Alternative',role:'scenario',plot_data:{...data,valid_cells:7}}]} as unknown as ResearchResult)!;
 expect(comparison.valid_cells).toBe(11);expect(availableFigures(comparison).map(f=>f.id)).toEqual(['comparison_boxes','comparison_cdf']);
 for(const recipe of availableFigures(comparison)){const settings={...defaultFigure(comparison),kind:recipe.id};expect(makeFigure(comparison,settings).error).toBeUndefined();expect(figureTable(comparison,settings).rows.length).toBeGreaterThan(1);}
});
it('uses the recorded paired moments rather than fitting a plotted sample',()=>{
 const data=researchFigureData(result,'cut_m3','realizations')!;
 data.joint={x_quantity:'Baseline',x_unit:'m3',y_quantity:'Candidate',y_unit:'m3',population_cells:4,sample_cells:2,sampling:'systematic',pearson_r:1,identity_line:true,samples:[{x:1,y:2},{x:3,y:4}],density_cells:[],notes:[],regression:{slope:1,intercept:1,r_squared:1},agreement:{bias:1,sample_std:0,lower:1,upper:1}};
 expect(figureTable(data,{...defaultFigure(data),kind:'bland_altman'}).rows).toEqual([[1.5,1],[3.5,1]]);
 expect(makeFigure(data,{...defaultFigure(data),kind:'bland_altman'}).primitives.some(p=>p.text?.includes('Mean 1'))).toBe(true);
 expect(makeFigure(data,{...defaultFigure(data),kind:'regression'}).primitives.some(p=>p.text?.includes('R² = 1'))).toBe(true);
});

it('uses a full two-factor grid and leaves unmatched responses blank',()=>{
 const factorial={x_parameter:'reference',y_parameter:'design_east_grade',x_values:[90,95],y_values:[0,.01],cells:[{x:90,y:0,metrics:{cut_m3:100},matched_population:true},{x:90,y:.01,metrics:{cut_m3:101},matched_population:true},{x:95,y:0,metrics:{cut_m3:50},matched_population:true},{x:95,y:.01,metrics:{cut_m3:51},matched_population:false}]};
 const data=researchFigureData({...result,factorial},'cut_m3','factorial')!;
 const settings=defaultFigure(data);expect(settings.kind).toBe('parameter_heatmap');
 expect(figureTable(data,settings).rows).toEqual([[90,0,100],[90,.01,101],[95,0,50],[95,.01,null]]);
 const scene=makeFigure(data,settings);expect(scene.error).toBeUndefined();expect(scene.primitives.some(p=>p.text==='N/A')).toBe(true);
});
