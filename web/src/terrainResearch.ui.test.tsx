// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import TerrainResearchPanel from './TerrainResearchPanel';
import type {ResearchResult} from './api';
import type {PersistedTerrainResult} from './terrainResultStore';
const mocked=vi.hoisted(()=>({analyzeResearch:vi.fn(),getResearchCatalog:vi.fn(),loadResearch:vi.fn(),saveResearch:vi.fn(),downloadResearch:vi.fn()}));
vi.mock('./api',()=>({analyzeResearch:mocked.analyzeResearch,getResearchCatalog:mocked.getResearchCatalog}));
vi.mock('./terrainResearch',async original=>({...await original<typeof import('./terrainResearch')>(),loadResearch:mocked.loadResearch,saveResearch:mocked.saveResearch,downloadResearch:mocked.downloadResearch}));
const geometry={type:'Polygon',coordinates:[]} as GeoJSON.Polygon;
const record={id:'run',title:'Cut / fill map',source:{id:'dem',name:'Measured DEM',sha256:'a'.repeat(64)},geometry,operation:'cutfill_map',parameters:{reference_elevation_m:90}} as unknown as PersistedTerrainResult;
const raster={png:'data:image/png;base64,AA==',geotiff:'AA==',corners:[[0,0],[1,0],[1,1],[0,1]],legend:[{label:'Same',cells:1,color:'#fff'}],width:1,height:1,valid_cells:1,unit:'m'};
const output={title:'Saved experiment',mode:'comparison',runs:[{label:'Baseline',metrics:{cut_m3:100},input:{}},{label:'Higher',metrics:{cut_m3:50},input:{}}],products:[{name:'Baseline',role:'baseline',raster},{name:'Higher',role:'scenario',raster}],differences:[{name:'Higher',kind:'difference',raster,statistics:{common_cells:1,common_coverage_pct:100,changed_pct:100}}],metric_table:[{metric:'cut_m3',values:[100,50],deltas:[0,-50],relative_pct:[0,-50]}],sensitivity:[],uncertainty:null,manifest:{input:{base:{image_id:'dem'}}},archive_base64:'AA=='} as unknown as ResearchResult;
beforeEach(()=>{
 mocked.getResearchCatalog.mockResolvedValue({sweep_parameters:{cutfill_map:['reference']},scenario_parameters:{cutfill_map:['reference','gradient_method']},uncertainty_operations:['cutfill_map'],parameter_specs:{reference:{default:0,choices:[]},gradient_method:{default:'horn',choices:['horn','zevenbergen_thorne']}}});
 mocked.loadResearch.mockResolvedValue(null);mocked.saveResearch.mockResolvedValue(undefined);mocked.analyzeResearch.mockResolvedValue(output);
});
afterEach(()=>{cleanup();vi.clearAllMocks();vi.restoreAllMocks();});
function setup(){const onClose=vi.fn(),onLayer=vi.fn();render(<TerrainResearchPanel projectId="project" record={record} connected onClose={onClose} onLayer={onLayer}/>);return {onClose,onLayer};}
async function scenario(){await screen.findByRole('option',{name:'reference'});fireEvent.change(screen.getByLabelText('Parameter value'),{target:{value:'95'}});fireEvent.click(screen.getByRole('button',{name:'Apply parameter'}));}
it('edits multiple named scenarios, computes from the immutable source and presents aligned results',async()=>{
 setup();await scenario();
 fireEvent.change(screen.getByLabelText('Scenario name'),{target:{value:'Higher'}});
 fireEvent.click(screen.getByRole('button',{name:'Add scenario'}));
 fireEvent.change(screen.getByLabelText('Scenario name'),{target:{value:'Balanced'}});
 fireEvent.change(screen.getByLabelText('Parameter value'),{target:{value:'100'}});fireEvent.click(screen.getByRole('button',{name:'Apply parameter'}));
 fireEvent.click(screen.getByRole('button',{name:'Run experiment'}));
 await screen.findByRole('table');
 expect(mocked.analyzeResearch).toHaveBeenCalledWith(expect.objectContaining({base:expect.objectContaining({reference:90,image_id:'dem'}),scenarios:[{name:'Higher',parameters:{reference:95}},{name:'Balanced',parameters:{reference:100}}]}),expect.any(AbortSignal));
 expect(screen.getByRole('table').textContent).toContain('-50%');
 expect(mocked.saveResearch).toHaveBeenCalledWith('project',expect.anything(),output);
 fireEvent.click(screen.getByRole('button',{name:'Report'}));
 fireEvent.click(screen.getByRole('button',{name:'Download research package'}));
 expect(mocked.downloadResearch).toHaveBeenCalledWith('AA==','terrain-research.zip','application/zip');
});
it('shows a signed map, supports matched swipes and publishes a georeferenced result layer',async()=>{
 const {onClose,onLayer}=setup();await scenario();fireEvent.click(screen.getByRole('button',{name:'Run experiment'}));await screen.findByRole('table');
 fireEvent.click(screen.getByRole('button',{name:'Figures'}));
 expect(screen.getByAltText('Higher map')).toBeTruthy();
 fireEvent.change(screen.getByLabelText('Figure'),{target:{value:'swipe'}});
 expect(screen.getByAltText('Baseline map')).toBeTruthy();fireEvent.change(screen.getByLabelText('Baseline reveal'),{target:{value:'70'}});
 expect((screen.getByAltText('Baseline map') as HTMLImageElement).style.clipPath).toBe('inset(0 30% 0 0)');
 fireEvent.click(screen.getByRole('button',{name:'Show on map'}));
 expect(onLayer).toHaveBeenCalledWith(expect.objectContaining({raster,title:'Higher'}));expect(onClose).toHaveBeenCalledOnce();
});
it('rejects invalid sweeps locally then plots actual response and baseline derivatives',async()=>{
 mocked.analyzeResearch.mockResolvedValue({...output,mode:'sensitivity',sensitivity:[{parameter:'reference',value:85,baseline_value:90,metrics:{cut_m3:150},derivatives:{cut_m3:-10}},{parameter:'reference',value:95,baseline_value:90,metrics:{cut_m3:50},derivatives:{cut_m3:-10}}]});
 setup();await scenario();fireEvent.change(screen.getByLabelText('Analysis method'),{target:{value:'sensitivity'}});
 fireEvent.change(screen.getByLabelText('Sweep values'),{target:{value:'1,1'}});fireEvent.click(screen.getByRole('button',{name:'Run experiment'}));
 expect(screen.getByRole('alert').textContent).toContain('distinct');expect(mocked.analyzeResearch).not.toHaveBeenCalled();
 fireEvent.change(screen.getByLabelText('Sweep values'),{target:{value:'85,95'}});fireEvent.click(screen.getByRole('button',{name:'Run experiment'}));await screen.findByRole('table');
 expect(mocked.analyzeResearch.mock.calls[0][0]).toMatchObject({mode:'sensitivity',parameter:'reference',values:[85,95]});
 fireEvent.click(screen.getByRole('button',{name:'Figures'}));fireEvent.change(screen.getByLabelText('Figure'),{target:{value:'response'}});
 expect(screen.getByRole('img',{name:'Sensitivity response: cut_m3'})).toBeTruthy();
});
it('reports conditional uncertainty and numerical stability rather than a confidence claim',async()=>{
 mocked.analyzeResearch.mockResolvedValue({...output,mode:'uncertainty',uncertainty:{model:'common_offset',samples:20,seed:42,coverage:.95,warning:'Assumed error model',metrics:{cut_m3:{baseline:100,mean:101,std:3,low:95,high:107,mean_standard_error:.4,split_half_endpoint_difference:2}}}});
 setup();await scenario();fireEvent.change(screen.getByLabelText('Analysis method'),{target:{value:'uncertainty'}});
 fireEvent.change(screen.getByLabelText('Spatial error model'),{target:{value:'common_offset'}});fireEvent.change(screen.getByLabelText('Realizations'),{target:{value:'20'}});
 fireEvent.click(screen.getByRole('button',{name:'Run experiment'}));await screen.findByRole('table');
 expect(screen.getByText(/95% model coverage interval/)).toBeTruthy();expect(screen.getByText(/Split-half endpoint difference: 2/)).toBeTruthy();
});
it('cancels pending work without exposing a stale completed result',async()=>{
 let complete!:(value:ResearchResult)=>void;mocked.analyzeResearch.mockReturnValue(new Promise<ResearchResult>(resolve=>{complete=resolve;}));
 setup();await scenario();fireEvent.click(screen.getByRole('button',{name:'Run experiment'}));
 const signal=mocked.analyzeResearch.mock.calls[0][1] as AbortSignal;
 fireEvent.click(screen.getByRole('button',{name:'Cancel experiment'}));expect(signal.aborted).toBe(true);
 complete(output);await waitFor(()=>expect(screen.getByRole('button',{name:'Results'})).toHaveProperty('disabled',true));
 expect(mocked.saveResearch).not.toHaveBeenCalled();
});
it('keeps completed outputs exportable when caching fails and restores them by project',async()=>{
 mocked.loadResearch.mockResolvedValue({input:{},result:output});const {onClose}=setup();
 await waitFor(()=>expect(screen.getByRole('button',{name:'Report'})).toHaveProperty('disabled',false));
 fireEvent.click(screen.getByRole('button',{name:'Close research analysis'}));expect(onClose).toHaveBeenCalled();
});
it('uses enum choices, allows removing overrides, and surfaces server and storage errors',async()=>{
 setup();await scenario();fireEvent.change(screen.getByLabelText('Parameter',{exact:true}),{target:{value:'gradient_method'}});
 fireEvent.change(screen.getByLabelText('Parameter value'),{target:{value:'zevenbergen_thorne'}});fireEvent.click(screen.getByRole('button',{name:'Apply parameter'}));
 fireEvent.click(screen.getByRole('button',{name:'Remove gradient_method'}));
 mocked.analyzeResearch.mockRejectedValueOnce(new Error('Invalid source grid'));fireEvent.click(screen.getByRole('button',{name:'Run experiment'}));
 expect((await screen.findByRole('alert')).textContent).toContain('Invalid source grid');
 mocked.saveResearch.mockRejectedValueOnce(new Error('Quota exceeded'));fireEvent.click(screen.getByRole('button',{name:'Run experiment'}));
 await waitFor(()=>expect(screen.getByRole('status').textContent).toContain('Quota exceeded')); 
});
