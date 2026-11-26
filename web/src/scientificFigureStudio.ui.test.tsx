// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import ScientificFigureStudio,{studioHeader} from './ScientificFigureStudio';
const mocked=vi.hoisted(()=>({getStudioCatalog:vi.fn(),renderStudio:vi.fn(),composeStudio:vi.fn()}));
vi.mock('./api',()=>mocked);
afterEach(()=>{cleanup();vi.clearAllMocks();});
it('binds recorded numeric data, displays the server-rendered figure and preserves provenance',async()=>{
 mocked.getStudioCatalog.mockResolvedValue({recipes:[{id:'pareto',title:'Pareto dominance',family:'Scenarios',source:'table',fields:['x','y'],note:'Observed designs',minimum_rasters:1,option:null}]});
 mocked.renderStudio.mockResolvedValue({figure:'AA==',media_type:'image/png',metadata:{input_count:2,used_count:2,method_note:'Actual observations'},table:[['x','y','nondominated'],[1,2,1],[2,3,0]]});
 const close=vi.fn();render(<ScientificFigureStudio source={{name:'Experiment',csv:'cost,benefit\n1,2\n2,3',provenance:{id:'actual'}}} onClose={close}/>);
 await screen.findByRole('button',{name:/Pareto dominance/});
 fireEvent.change(screen.getByLabelText('Figure field x'),{target:{value:'cost'}});
 fireEvent.change(screen.getByLabelText('Figure field y'),{target:{value:'benefit'}});
 fireEvent.click(screen.getByRole('button',{name:'Render figure'}));
 await screen.findByAltText('Pareto dominance preview');
 expect(mocked.renderStudio).toHaveBeenCalledWith(expect.objectContaining({recipe:'pareto',csv:'cost,benefit\n1,2\n2,3',x:'cost',y:'benefit',rasters:[]}),expect.any(AbortSignal));
 expect(screen.getByText('2 used / 2 input observations or cells')).toBeTruthy();
 expect(screen.getByRole('button',{name:'PDF'})).not.toHaveProperty('disabled',true);
 fireEvent.click(screen.getByRole('button',{name:'Close studio'}));expect(close).toHaveBeenCalled();
});
it('reads quoted headers and keeps controls unavailable until required bindings exist',async()=>{
 expect(studioHeader('\ufeff"site, id","slope ""deg"""\nA,3')).toEqual(['site, id','slope "deg"']);
 mocked.getStudioCatalog.mockResolvedValue({recipes:[{id:'kde',title:'Kernel density estimate',family:'Distribution',source:'table',fields:['y'],note:'',minimum_rasters:1,option:null}]});
 mocked.renderStudio.mockRejectedValue(new Error('Invalid numerical observations'));
 render(<ScientificFigureStudio source={{name:'No data'}} onClose={()=>{}}/>);
 await screen.findByRole('button',{name:/Kernel density estimate/});
 expect(screen.getByRole('button',{name:'Render figure'})).toHaveProperty('disabled',true);
 fireEvent.change(screen.getByLabelText('Figure CSV data'),{target:{value:'value\n1\n2'}});
 fireEvent.change(screen.getByLabelText('Figure field y'),{target:{value:'value'}});
 fireEvent.click(screen.getByRole('button',{name:'Render figure'}));
 await waitFor(()=>expect(screen.getByRole('alert').textContent).toContain('Invalid numerical observations'));
});

it('collects two actual render receipts and composes them without image stitching',async()=>{
 mocked.getStudioCatalog.mockResolvedValue({recipes:[{id:'pareto',title:'Pareto dominance',family:'Scenarios',source:'table',fields:['x','y'],note:'',minimum_rasters:1,option:null}]});
 mocked.renderStudio.mockResolvedValue({figure:'AA==',media_type:'image/png',metadata:{input_count:2,used_count:2},table:[['x','y'],[1,2]]});
 mocked.composeStudio.mockResolvedValue({figure:'AA==',media_type:'image/png',metadata:{panel_count:2},table:[]});
 render(<ScientificFigureStudio source={{name:'Experiment',csv:'cost,benefit\n1,2\n2,3'}} onClose={()=>{}}/>);
 await screen.findByRole('button',{name:/Pareto dominance/});
 fireEvent.change(screen.getByLabelText('Figure field x'),{target:{value:'cost'}});
 fireEvent.change(screen.getByLabelText('Figure field y'),{target:{value:'benefit'}});
 fireEvent.click(screen.getByRole('button',{name:'Render figure'}));await screen.findByAltText('Pareto dominance preview');
 fireEvent.click(screen.getByRole('button',{name:'Add to composition'}));
 fireEvent.click(screen.getByRole('button',{name:'Add to composition'}));
 fireEvent.click(screen.getByRole('button',{name:'Figure composer'}));
 fireEvent.change(screen.getByLabelText('Composition title'),{target:{value:'Study'}});
 fireEvent.click(screen.getByRole('button',{name:'Render composition'}));await screen.findByAltText('Publication composition preview');
 expect(mocked.composeStudio).toHaveBeenCalledWith(expect.objectContaining({title:'Study',panels:[expect.objectContaining({recipe:'pareto',x:'cost'}),expect.objectContaining({recipe:'pareto',y:'benefit'})]}),expect.any(AbortSignal));
});

it('separates basic and professional recipes with a compatible initial selection',async()=>{
 const common={source:'table' as const,fields:['x','y'],note:'',minimum_rasters:1,option:null};
 mocked.getStudioCatalog.mockResolvedValue({recipes:[{...common,id:'basic_line',title:'Simple numeric line',family:'Basic',tier:'basic'},{...common,id:'model_roc',title:'Binary ROC',family:'GeoAI validation',tier:'professional'}]});
 render(<ScientificFigureStudio source={{name:'Recorded table',csv:'x,y\n1,2\n2,3'}} initialTier="basic" onClose={()=>{}}/>);
 await screen.findByRole('button',{name:/Simple numeric line/});
 expect(screen.queryByRole('button',{name:/Binary ROC/})).toBeNull();
 fireEvent.change(screen.getByLabelText('Figure library tier'),{target:{value:'professional'}});
 expect(screen.getByRole('button',{name:/Binary ROC/}).getAttribute('aria-pressed')).toBe('true');
 expect(screen.queryByRole('button',{name:/Simple numeric line/})).toBeNull();
});


it('keeps data and style settings separate without showing library counts',async()=>{
 mocked.getStudioCatalog.mockResolvedValue({recipes:[{id:'pareto',title:'Pareto dominance',family:'Scenarios',source:'table',fields:['x','y'],note:'Observed designs',minimum_rasters:1,option:null}]});
 render(<ScientificFigureStudio source={{name:'Experiment',csv:'cost,benefit\n1,2\n2,3'}} onClose={()=>{}}/>);
 await screen.findByRole('button',{name:/Pareto dominance/});
 expect(screen.queryByText(/\d+\s*\/\s*\d+ recipes/)).toBeNull();
 expect(screen.queryByText(/Basic: 24 native/)).toBeNull();
 expect(screen.getByRole('button',{name:/^Data$/}).getAttribute('aria-pressed')).toBe('true');
 fireEvent.change(screen.getByLabelText('Figure field x'),{target:{value:'cost'}});
 fireEvent.click(screen.getByRole('button',{name:/^Style$/}));
 expect(screen.getByRole('group',{name:'Figure style settings'})).toBeTruthy();
 fireEvent.change(screen.getByLabelText('Studio figure title'),{target:{value:'Study'}});
 fireEvent.click(screen.getByRole('button',{name:/^Data$/}));
 expect((screen.getByLabelText('Figure field x') as HTMLSelectElement).value).toBe('cost');
});


it('pages the figure library and keeps the selected item in its original position',async()=>{
 const recipes=Array.from({length:19},(_,i)=>({id:'figure_'+i,title:'Figure '+i,family:'Statistics',source:'table',fields:['x','y'],minimum_rasters:1,option:null}));
 mocked.getStudioCatalog.mockResolvedValue({recipes});
 render(<ScientificFigureStudio source={{name:'Study',csv:'x,y\n1,2'}} onClose={()=>{}}/>);
 await screen.findByRole('button',{name:/^Figure 0 Statistics$/});
 expect(screen.getAllByRole('button',{name:/^Figure \d+ Statistics$/})).toHaveLength(8);
 fireEvent.click(screen.getByRole('button',{name:'Next figure page'}));
 const item=screen.getByRole('button',{name:/^Figure 9 Statistics$/});
 fireEvent.click(item);
 expect(item.getAttribute('aria-pressed')).toBe('true');
 expect(screen.getByText('Page 2 of 3')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Next figure page'}));
 expect(screen.getAllByRole('button',{name:/^Figure \d+ Statistics$/})).toHaveLength(3);
 fireEvent.change(screen.getByLabelText('Search figures'),{target:{value:'Figure 18'}});
 expect(screen.getAllByRole('button',{name:/^Figure \d+ Statistics$/})).toHaveLength(1);
 expect(screen.queryByRole('button',{name:'Next figure page'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Edit CSV'}));
 expect(screen.getByLabelText('Figure CSV data')).toBeTruthy();
});
