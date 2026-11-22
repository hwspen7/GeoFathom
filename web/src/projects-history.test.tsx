// @vitest-environment jsdom
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import ProjectsPanel from './ProjectsPanel';
import type {ComponentProps} from 'react';
import type {FeatureHistory,WorkspaceFeature} from './api';

const api=vi.hoisted(()=>({
  getProjects:vi.fn(),getWorkspace:vi.fn(),getFeatureHistory:vi.fn(),
  copyProjectFeature:vi.fn(),createLayer:vi.fn(),deleteProjectFeature:vi.fn(),
  exportProject:vi.fn(),newProject:vi.fn(),patchLayer:vi.fn(),restoreFeature:vi.fn(),
  saveProjectFeature:vi.fn(),saveFeatureBatch:vi.fn(),patchLayerStyle:vi.fn(),updateProjectFeature:vi.fn()
}));
vi.mock('./api',()=>api);
const point:GeoJSON.Point={type:'Point',coordinates:[10,20]};
const measurement={geometry_type:'Point',area_m2:null,area_km2:null,perimeter_m:null,length_m:null,
  bounds:[10,20,10,20],coordinate_count:1,method:'fixture',note:''};
const feature=(id:string):WorkspaceFeature=>({id,project_id:'p',layer_id:'layer',revision:3,
  name:id,source:'survey',geometry:point,properties:{},measurement,created_at:'2026-01-01'});
const first=feature('first'),second=feature('second');
function history(f:WorkspaceFeature,revision:number):FeatureHistory{
  return {feature_id:f.id,current_revision:3,versions:[{
    revision,name:f.name,geometry:point,properties:{},created_at:'2026-01-01',measurement
  }]};
}
function deferred<T>(){
  let resolve!:(value:T)=>void;
  const promise=new Promise<T>(done=>{resolve=done;});
  return {promise,resolve};
}
const props=(id:string|null):ComponentProps<typeof ProjectsPanel>=>({
  geometry:point,featureName:'Feature',featureSource:'survey',featureProperties:{},selectedFeatureId:id,
  splitParts:[],refreshToken:0,onOpen:vi.fn(),onWorkspace:vi.fn(),onPlaceAnnotation:vi.fn(),
  onFeatureDeleted:vi.fn(),extraFeatures:[]
});
beforeEach(()=>{
  sessionStorage.clear();vi.resetAllMocks();
  api.getProjects.mockResolvedValue([{id:'p',name:'Project'}]);
  api.getWorkspace.mockResolvedValue({layers:[],features:[first,second],total:2});
  api.getFeatureHistory.mockImplementation(async (_project,id)=>history(id==='first'?first:second,2));
});
afterEach(()=>{cleanup();sessionStorage.clear();});
it('ignores a late manually requested history after selecting another feature',async()=>{
  const p=props('first');
  const {rerender}=render(<ProjectsPanel {...p}/>);
  await screen.findByRole('button',{name:/Revision 2/});
  fireEvent.click(screen.getByRole('button',{name:'Versions'}));
  expect(screen.queryByRole('button',{name:/Revision 2/})).toBeNull();
  const stale=deferred<FeatureHistory>();
  api.getFeatureHistory.mockReturnValueOnce(stale.promise);
  fireEvent.click(screen.getByRole('button',{name:'Versions'}));
  rerender(<ProjectsPanel {...p} selectedFeatureId="second"/>);
  await screen.findByRole('button',{name:/Revision 2/});
  await act(async()=>{stale.resolve(history(first,1));await stale.promise;});
  expect(screen.queryByRole('button',{name:/Revision 1/})).toBeNull();
  expect(screen.getByRole('button',{name:/Revision 2/})).toBeTruthy();
});
it('reports a manual history request failure without an unhandled rejection',async()=>{
  render(<ProjectsPanel {...props('first')}/>);
  await screen.findByRole('button',{name:/Revision 2/});
  fireEvent.click(screen.getByRole('button',{name:'Versions'}));
  api.getFeatureHistory.mockRejectedValueOnce(new Error('History service offline'));
  fireEvent.click(screen.getByRole('button',{name:'Versions'}));
  expect(await screen.findByText('History service offline')).toBeTruthy();
  expect(screen.queryByRole('button',{name:/Revision 2/})).toBeNull();
});
it('rejects a mismatched feature history response',async()=>{
  render(<ProjectsPanel {...props('first')}/>);
  await screen.findByRole('button',{name:/Revision 2/});
  fireEvent.click(screen.getByRole('button',{name:'Versions'}));
  api.getFeatureHistory.mockResolvedValueOnce(history(second,1));
  fireEvent.click(screen.getByRole('button',{name:'Versions'}));
  await screen.findByText('Feature history identity mismatch.');
  expect(screen.queryByRole('button',{name:/Revision 1/})).toBeNull();
});
it('cannot save a draft before its workspace has loaded',async()=>{
  const pending=deferred<{layers:unknown[];features:unknown[];total:number}>();
  api.getWorkspace.mockReturnValue(pending.promise);
  const p=props(null);
  render(<ProjectsPanel {...p}/>);
  await screen.findByText('Loading selected project…');
  const button=screen.getByRole('button',{name:'Save selected'}) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.click(button);
  expect(api.saveProjectFeature).not.toHaveBeenCalled();
  await act(async()=>{pending.resolve({layers:[],features:[],total:0});await pending.promise;});
  await waitFor(()=>expect(button.disabled).toBe(false));
});
