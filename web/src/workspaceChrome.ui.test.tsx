// @vitest-environment jsdom
import {describe,it,expect,vi,afterEach} from 'vitest';
import {render,fireEvent,screen,cleanup,within,waitFor} from '@testing-library/react';
afterEach(cleanup);
import {WorkspaceCommandPalette,WorkspaceFeatureTree,WorkspaceModuleBar,WORKSPACE_MODULES,type WorkspaceCommand} from './WorkspaceChrome';
describe('shared research workbench chrome',()=>{
 it('preserves single-word navigation and exposes concise module hints',()=>{
  const activate=vi.fn();
  render(<WorkspaceModuleBar active="tools-raster" open onActivate={activate}/>);
  for(const module of WORKSPACE_MODULES){
   const button=screen.getByRole('button',{name:module.label,exact:true});
   expect(button.getAttribute('title')).toBe(module.hint);
  }
  expect(screen.getByRole('combobox',{name:'Workspace module'}).getAttribute('title')).toBe('Raster and AI extraction');
  fireEvent.click(screen.getByRole('button',{name:'Terrain',exact:true}));
  expect(activate).toHaveBeenCalledWith('tools-terrain');
 });
 it('searches and invokes commands without invoking disabled actions',()=>{
  const perform=vi.fn(),close=vi.fn();
  const commands:WorkspaceCommand[]=[
   {id:'terrain',label:'Terrain',group:'Workbenches',run:perform},
   {id:'save',label:'Save',group:'File',disabled:true,run:perform},
  ];
  render(<WorkspaceCommandPalette open commands={commands} onClose={close}/>);
  fireEvent.change(screen.getByRole('searchbox',{name:'Search workspace commands'}),
   {target:{value:'terrain'}});
  fireEvent.click(screen.getByRole('button',{name:/Terrain/}));
  expect(perform).toHaveBeenCalledTimes(1);
  expect(close).toHaveBeenCalledTimes(1);
 });
 it('groups selected features by layers and filters by name',()=>{
  const open=vi.fn();
  const features=[
   {id:'a',name:'Campus boundary',layer_id:'study',revision:2},
   {id:'b',name:'North parcel',layer_id:'study',revision:1},
   {id:'c',name:'Remote site',layer_id:'off',revision:1},
  ];
  render(<WorkspaceFeatureTree layers={[
    {id:'study',name:'Study area',visible:true},
    {id:'off',name:'Hidden sites',visible:false},
   ]} features={features} selectedId="a" onOpen={open}/>);
  // Revision badges remain visible without becoming part of the feature name.
  const selected=screen.getByRole('button',{name:'Campus boundary'});
  expect(selected.getAttribute('aria-pressed')).toBe('true');
  expect(selected.textContent).toContain('r2');
  expect(screen.getByRole('button',{name:/Remote site/}).hasAttribute('disabled')).toBe(true);
  fireEvent.change(screen.getByRole('searchbox',{name:'Filter project features'}),
    {target:{value:'north'}});
  expect(screen.queryByRole('button',{name:/Campus boundary/})).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:/North parcel/}));
  expect(open).toHaveBeenCalledWith(features[1]);
 });
 it('renames a neighbouring object without selecting it and keeps a failed name editable',async()=>{
  const open=vi.fn(),rename=vi.fn().mockRejectedValueOnce(Error('Revision changed. Refresh and retry.')).mockResolvedValueOnce(undefined);
  const remove=vi.fn().mockResolvedValue(undefined);
  const features=[{id:'a',name:'厦门岛',layer_id:'study'},{id:'b',name:'Polygon 1',layer_id:'study'}];
  render(<WorkspaceFeatureTree layers={[{id:'study',name:'Measurements',visible:true}]}
    features={features} selectedId="a" onOpen={open} onRename={rename} onDelete={remove}/>);
  const row=within(screen.getByRole('group',{name:'Object Polygon 1'}));
  fireEvent.click(row.getByRole('button',{name:'Rename object'}));
  fireEvent.change(row.getByRole('textbox',{name:'Object name'}),{target:{value:'  Study buffer  '}});
  fireEvent.click(row.getByRole('button',{name:'Save name'}));
  expect(await row.findByRole('alert')).toHaveProperty('textContent','Revision changed. Refresh and retry.');
  expect(open).not.toHaveBeenCalled();
  fireEvent.click(row.getByRole('button',{name:'Save name'}));
  await waitFor(()=>expect(row.queryByRole('textbox')).toBeNull());
  expect(rename).toHaveBeenLastCalledWith(features[1],'Study buffer');
  fireEvent.click(row.getByRole('button',{name:'Delete object'}));
  await waitFor(()=>expect(remove).toHaveBeenCalledWith(features[1]));
  expect(open).not.toHaveBeenCalled();
  expect(screen.getByRole('button',{name:'厦门岛'}).getAttribute('aria-pressed')).toBe('true');
 });
 it('locks mutations and pages objects without hiding the selected object',()=>{
  const features=Array.from({length:8},(_,i)=>({id:String(i),name:'Parcel '+i,layer_id:'study'}));
  render(<WorkspaceFeatureTree layers={[{id:'study',name:'Study',visible:true,locked:true}]}
    features={features} selectedId="7" onOpen={vi.fn()} onRename={vi.fn()} onDelete={vi.fn()}/>);
  expect(screen.getByRole('button',{name:'Parcel 7'}).getAttribute('aria-pressed')).toBe('true');
  expect(screen.getAllByRole('button',{name:'Delete object'}).every(button=>button.hasAttribute('disabled'))).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'Previous objects'}));
  expect(screen.getByRole('button',{name:'Parcel 0'})).toBeDefined();
  expect(screen.queryByRole('button',{name:'Parcel 7'})).toBeNull();
 });
 it('bounds the entire object list across many layers and searches beyond the current page',()=>{
  const open=vi.fn();
  const layers=Array.from({length:4},(_,i)=>({id:String(i),name:'Layer '+i,visible:true}));
  const features=Array.from({length:12},(_,i)=>({id:String(i),name:'P-'+i,layer_id:String(Math.floor(i/3))}));
  render(<WorkspaceFeatureTree layers={layers} features={features} selectedId={null} pageSize={3} onOpen={open}/>);
  expect(screen.getAllByRole('button',{name:/^P-/})).toHaveLength(3);
  fireEvent.click(screen.getByRole('button',{name:'Next objects'}));
  expect(screen.getAllByRole('button',{name:/^P-/})).toHaveLength(3);
  fireEvent.change(screen.getByRole('searchbox',{name:'Filter project features'}),{target:{value:'P-11'}});
  fireEvent.click(screen.getByRole('button',{name:'P-11'}));
  expect(open).toHaveBeenCalledWith(features[11]);
 });
});
