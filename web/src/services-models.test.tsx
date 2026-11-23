// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import ModelControls from './ModelControls';
import DataServicesPanel from './DataServicesPanel';
import ApiAccessPanel from './ApiAccessPanel';
import type {ComponentProps} from 'react';

const api=vi.hoisted(()=>({
  getModelCatalog:vi.fn(),probeModel:vi.fn(),saveModel:vi.fn(),deleteModel:vi.fn(),selectDefaultModel:vi.fn(),
  getOGCSources:vi.fn(),getGISJobs:vi.fn(),getPostGISStatus:vi.fn(),ogcTileTemplate:vi.fn(),
  registerOGCSource:vi.fn(),inspectOGCSource:vi.fn(),remoteOGCFeatures:vi.fn(),
  removeOGCSource:vi.fn(),saveFeatureBatch:vi.fn(),queryPostGIS:vi.fn(),viewportFeatures:vi.fn(),
  queueGISJob:vi.fn(),cancelGISJob:vi.fn(),downloadGISJob:vi.fn(),setApiAccessToken:vi.fn(),
}));
vi.mock('./api',()=>api);
const change=(name:string,value:string)=>fireEvent.change(screen.getByLabelText(name),{target:{value}});
const click=(name:string|RegExp)=>fireEvent.click(screen.getByRole('button',{name}));
const model={id:'local',name:'Local',provider:'ollama',model:'test',base_url:'http://127.0.0.1:11434',
  credential_env:'',enabled:true,configured:true,preset:false};
const catalog={default_id:'local',models:[model]};
const bbox:[number,number,number,number]=[10,20,10.01,20.01];
const point:GeoJSON.Point={type:'Point',coordinates:[10,20]};
const raster={id:'wms',project_id:'p',service:'wms',title:'Raster',layer_name:'image',
  base_url:'https://example.test/wms',attribution:'License',tile_matrix_set:''};
const vector={...raster,id:'wfs',title:'Vector',service:'wfs',layer_name:'parcels'};
const completed={id:'finished',kind:'export_geojson',status:'completed',progress:100};
const pending={id:'pending',kind:'topology_qa',status:'queued',progress:0};

beforeEach(()=>{
  vi.resetAllMocks();
  api.getModelCatalog.mockResolvedValue(catalog);
  api.getOGCSources.mockResolvedValue({sources:[raster,vector]});
  api.getGISJobs.mockResolvedValue({jobs:[completed,pending]});
  api.getPostGISStatus.mockResolvedValue({connected:true,configured:true,note:'test'});
  api.ogcTileTemplate.mockReturnValue('https://example.test/{z}/{x}/{y}');
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

describe('model directory',()=>{
  it('connects, edits and updates defaults with server-side credentials',async()=>{
    const onChange=vi.fn();
    render(<ModelControls modelId="local" onChange={onChange}/>);
    await screen.findByText('Local · Configured');
    expect(onChange).toHaveBeenCalledWith('local');
    api.probeModel.mockResolvedValueOnce({intent:{action:'search',query:'sample'}});
    click('Test API');
    expect(await screen.findByText('Live response: search · sample')).toBeTruthy();
    api.probeModel.mockRejectedValueOnce(new Error('unreachable'));
    click('Test API');expect(await screen.findByText('unreachable')).toBeTruthy();
    click('Manage models');click('Add model');
    change('Identifier','new-model');change('Display name','Custom');change('Model identifier / installed tag','tag');
    change('Provider','groq');
    expect((screen.getByLabelText('Server-side API key variable') as HTMLInputElement).value).toBe('GEOFATHOM_GROQ_API_KEY');
    expect(screen.queryByLabelText('API base URL')).toBeNull();
    change('Provider','gemini');
    expect((screen.getByLabelText('Server-side API key variable') as HTMLInputElement).value).toBe('GEOFATHOM_GEMINI_API_KEY');
    change('Provider','openai-compatible');change('API base URL','https://example.test/v1');
    change('Server-side API key variable','GEOFATHOM_MODEL_KEY_TEST');fireEvent.click(screen.getByLabelText('Enabled'));
    change('Configuration access token','admin');
    api.saveModel.mockResolvedValue(catalog);
    click('Save model');expect(await screen.findByText('Model configuration saved in the server catalog.')).toBeTruthy();
    expect(api.saveModel).toHaveBeenCalledWith({id:'new-model',name:'Custom',model:'tag',provider:'openai-compatible',
      base_url:'https://example.test/v1',credential_env:'GEOFATHOM_MODEL_KEY_TEST',enabled:false},'admin');
    click('Edit');expect((screen.getByLabelText('Identifier') as HTMLInputElement).value).toBe('local');
    click('Cancel');
    api.selectDefaultModel.mockResolvedValue(catalog);
    click('Set default');expect(await screen.findByText('Default model updated for this workspace.')).toBeTruthy();
    expect(api.selectDefaultModel).toHaveBeenCalledWith('local','admin');
    api.deleteModel.mockResolvedValue(catalog);
    click('Delete selected custom model');expect(await screen.findByText('Custom model deleted.')).toBeTruthy();
    expect(api.deleteModel).toHaveBeenCalledWith('local','admin');
  });
  it('reports directory errors without inventing a model',async()=>{
    api.getModelCatalog.mockRejectedValue(new Error('offline'));
    render(<ModelControls modelId="missing" onChange={vi.fn()}/>);
    expect(await screen.findByText('Could not load model directory from FastAPI.')).toBeTruthy();
    expect(screen.queryByRole('button',{name:'Test API'})).toBeNull();
  });
});

describe('external GIS services',()=>{
  function props():ComponentProps<typeof DataServicesPanel>{
    return {projectId:'p',viewport:bbox,drawnGeometry:point,onTiles:vi.fn(),onPreview:vi.fn(),onPage:vi.fn(),onRefresh:vi.fn()};
  }
  it('registers, toggles, inspects, previews and imports actual remote data',async()=>{
    const p=props();const {container}=render(<DataServicesPanel {...p}/>);
    container.querySelectorAll('details').forEach(d=>d.open=true);
    await screen.findByText('2 configured services');
    click('Toggle OGC raster Raster');
    await waitFor(()=>expect(p.onTiles).toHaveBeenLastCalledWith([{id:'wms',title:'Raster',attribution:'License',template:'https://example.test/{z}/{x}/{y}'}]));
    click('Toggle OGC raster Raster');
    await waitFor(()=>expect(p.onTiles).toHaveBeenLastCalledWith([]));
    const row=screen.getByText('Vector · WFS').closest('.service-entry') as HTMLElement;
    api.inspectOGCSource.mockResolvedValue({version:'2.0'});
    fireEvent.click(within(row).getByRole('button',{name:'Capabilities'}));
    expect(await screen.findByText('Capabilities: {"version":"2.0"}')).toBeTruthy();
    api.remoteOGCFeatures.mockResolvedValue({type:'FeatureCollection',features:[
      {type:'Feature',geometry:point,properties:{name:'Parcel'}}]});
    click('Preview features');
    expect(await screen.findByText('Fetched 1 georeferenced remote objects for review.')).toBeTruthy();
    expect(p.onPreview).toHaveBeenLastCalledWith([point]);
    api.saveFeatureBatch.mockResolvedValue({created:1});
    click('Import 1 previewed objects into project');
    expect(await screen.findByText('Imported 1 remote features to the active project.')).toBeTruthy();
    expect(p.onRefresh).toHaveBeenCalledOnce();
    expect(api.saveFeatureBatch).toHaveBeenCalledWith('p',[{name:'Parcel',source:'OGC service import',geometry:point,properties:{name:'Parcel'}}]);
    click('Add source');
    change('New OGC service type','wmts');change('OGC layer or collection','tiles');
    change('OGC display title','Tiles');change('OGC HTTPS endpoint','https://example.test/wmts');
    change('WMTS tile matrix set','custom');change('OGC attribution','Source');change('GIS administrator token','admin');
    api.registerOGCSource.mockResolvedValue({...raster,id:'third',title:'Tiles',service:'wmts'});
    click('Register OGC source');await screen.findByText('3 configured services');
    expect(api.registerOGCSource).toHaveBeenCalledWith('p',{service:'wmts',title:'Tiles',base_url:'https://example.test/wmts',
      layer_name:'tiles',attribution:'Source',tile_matrix_set:'custom'},'admin');
    api.removeOGCSource.mockResolvedValue(undefined);
    click('Previous');
    fireEvent.click(within(row).getByRole('button',{name:'Remove'}));
    await screen.findByText('2 configured services');
    expect(api.removeOGCSource).toHaveBeenCalledWith('p','wfs','admin');
  });
  it('pages both spatial indexes and controls persistent queue operations',async()=>{
    const p=props();const {container}=render(<DataServicesPanel {...p}/>);
    container.querySelectorAll('details').forEach(d=>d.open=true);
    await screen.findByText(/PostGIS: Connected/);
    api.viewportFeatures.mockResolvedValue({results:[{id:'a'}],total:51});
    api.queryPostGIS.mockResolvedValue({results:[{id:'b'}],total:22});
    change('Viewport page offset','20');click('Load SQLite R-tree page');
    await screen.findByText('SQLite R-tree: 1 of 51 region features.');
    expect(api.viewportFeatures).toHaveBeenCalledWith('p',bbox,500,20);
    click('Load PostGIS page');await screen.findByText('PostGIS GiST: 1 of 22 region features.');
    expect(p.onPage).toHaveBeenLastCalledWith([{id:'b'}]);
    click('Refresh service status');await waitFor(()=>expect(api.getPostGISStatus).toHaveBeenCalledTimes(2));
    api.queueGISJob.mockResolvedValue({...pending,id:'new-task',kind:'spatial_select'});
    change('Background GIS job type','spatial_select');click('Queue background operation');
    await screen.findByText('Queued spatial_select as new-task.');
    expect(api.queueGISJob).toHaveBeenCalledWith('p','spatial_select',{geometry:point,relation:'intersects'},'');
    api.downloadGISJob.mockResolvedValue(undefined);click('Download GeoJSON');
    await waitFor(()=>expect(api.downloadGISJob).toHaveBeenCalledWith('p','finished'));
    api.cancelGISJob.mockResolvedValue(undefined);api.getGISJobs.mockResolvedValue({jobs:[completed]});
    const entry=screen.getByText('topology_qa · queued').closest('.service-entry') as HTMLElement;
    fireEvent.click(within(entry).getByRole('button',{name:'Cancel job'}));
    await waitFor(()=>expect(api.cancelGISJob).toHaveBeenCalledWith('p','pending'));
    await waitFor(()=>expect(screen.queryByText('topology_qa · queued')).toBeNull());
  });
});

it('server access shows only session-local status and never exposes the stored token',()=>{
  sessionStorage.setItem('geofathom-api-token','test-secret');
  try{
    render(<ApiAccessPanel/>);
    expect(screen.getByText(/session unlocked/)).toBeTruthy();
    expect((screen.getByLabelText('Server API access key') as HTMLInputElement).value).toBe('');
    expect((screen.getByRole('button',{name:'Use key'}) as HTMLButtonElement).disabled).toBe(true);
    change('Server API access key',' replacement ');
    expect((screen.getByRole('button',{name:'Use key'}) as HTMLButtonElement).disabled).toBe(false);
  }finally{sessionStorage.clear();}
});
