import {expect,it} from 'vitest';
import {researchFigureData} from './researchFigureData';
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
