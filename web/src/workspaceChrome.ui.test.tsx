// @vitest-environment jsdom
import {describe,it,expect,vi,afterEach} from 'vitest';
import {render,fireEvent,screen,cleanup} from '@testing-library/react';
afterEach(cleanup);
import {WorkspaceCommandPalette,WorkspaceFeatureTree,type WorkspaceCommand} from './WorkspaceChrome';
describe('shared research workbench chrome',()=>{
 it('searches and invokes commands without invoking disabled actions',()=>{
  const perform=vi.fn(),close=vi.fn();
  const commands:WorkspaceCommand[]=[
   {id:'terrain',label:'Terrain',group:'Workbenches',run:perform},
   {id:'save',label:'Save',group:'File',disabled:true,run:perform},
  ];
  render(<WorkspaceCommandPalette open commands={commands} onClose={close}/>);
  fireEvent.change(screen.getByRole('searchbox',{name:'Search workspace commands'}),
   {target:{value:'terrain'}});
  fireEvent.click(screen.getByRole('listitem',{name:/Terrain/}));
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
  expect(screen.getByRole('button',{name:/Campus boundary/}).getAttribute('aria-pressed')).toBe('true');
  expect(screen.getByRole('button',{name:/Remote site/}).hasAttribute('disabled')).toBe(true);
  fireEvent.change(screen.getByRole('searchbox',{name:'Filter project features'}),
    {target:{value:'north'}});
  expect(screen.queryByRole('button',{name:/Campus boundary/})).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:/North parcel/}));
  expect(open).toHaveBeenCalledWith(features[1]);
 });
});
