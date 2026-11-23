// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import TerrainResearchWorkbench from './TerrainResearchWorkbench';
import type {RasterAsset} from './api';

const api=vi.hoisted(()=>({
 runTerrainResearch:vi.fn(),
 checkTerrainCheckpointAccuracy:vi.fn(),
 verifyTerrainResearchArchive:vi.fn(),replayTerrainResearchArchive:vi.fn(),
}));
vi.mock('./api',()=>api);

const asset:RasterAsset={
 id:'a',name:'DEM research source',width:30,height:30,bands:1,
 crs:'EPSG:32617',bbox:[-83,40,-82.99,40.01],
 corners:[[-83,40],[-82.99,40],[-82.99,40.01],[-83,40.01]],
 preview_url:'/scene',acquired_at:null,provenance:'field',vertical_datum:'NAVD88',
};
const second={...asset,id:'b',name:'Supporting criteria raster'};
const polygon:GeoJSON.Polygon={type:'Polygon',coordinates:[[[-83,40],[-82.99,40],[-82.99,40.01],[-83,40]]]};
const output={
 schema:'geofathom.research.v1',
 metrics:{eligible_cells:100,score_mean:.68,eligible_above_threshold_pct:45},
 model:{weights:[.5,.5],ahp:null,uncertainty:{trials:64,seed:42,score_sd_mean:.1}},
 sensitivity:[],archive_base64:'AQID',archive_sha256:'deadbeef',raster_names:['suitability'],
 warning:'Research screening',
};
const change=(label:string,value:string)=>fireEvent.change(screen.getByLabelText(label),{target:{value}});
beforeEach(()=>{vi.resetAllMocks();api.runTerrainResearch.mockResolvedValue(output);api.verifyTerrainResearchArchive.mockResolvedValue({valid:true,files:7,source_sha256:[]});api.replayTerrainResearchArchive.mockResolvedValue({reproducible:true,verified_files:7,outputs:{suitability:0},warning:'Numerical reproduction'});});
afterEach(cleanup);

it('connects selected DEM and study geometry to explicit weighted raster criteria',async()=>{
 render(<TerrainResearchWorkbench dem={asset} geometry={polygon} assets={[asset,second]} connected/>);
 await waitFor(()=>expect((screen.getByLabelText('Factor raster') as HTMLSelectElement).value).toBe('a'));
 expect((screen.getByLabelText('Research factor') as HTMLSelectElement).options).toHaveLength(2);
 fireEvent.click(screen.getByRole('button',{name:'Run research model'}));
 await waitFor(()=>expect(api.runTerrainResearch).toHaveBeenCalledTimes(1));
 const [input,signal]=api.runTerrainResearch.mock.calls[0];
 expect(input.image_id).toBe('a');
 expect(input.criteria).toHaveLength(2);
 expect(input.criteria[0]).toMatchObject({
  image_id:'a',direction:'decreasing',low:0,high:100,weight:1,sigma:0,
 });
 expect(input.geometry).toEqual(polygon);
 expect(input.trials).toBe(64);
 expect(input.threshold).toBe(.65);
 expect(input.seed).toBe(42);
 expect(signal).toBeInstanceOf(AbortSignal);
 expect(await screen.findByText('Research ZIP')).toBeTruthy();
 expect(screen.getByText('0.68')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Verify'}));
 expect(await screen.findByText(/Verified 7 research artifacts/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Recompute'}));
 expect(await screen.findByText(/Numerical replay matched 1 archived raster products/)).toBeTruthy();
});

it('offers explicit factor controls and retains only one selected factor edit surface',()=>{
 render(<TerrainResearchWorkbench dem={asset} geometry={polygon} assets={[asset,second]} connected/>);
 fireEvent.click(screen.getByRole('button',{name:'Add factor'}));
 expect((screen.getByLabelText('Research factor') as HTMLSelectElement).options).toHaveLength(3);
 change('Factor name','Independent road network');
 expect(screen.getByRole('option',{name:'Independent road network'})).toBeTruthy();
 change('Factor raster','b');
 change('Factor direction','target');
 change('Factor target','55');
 fireEvent.click(screen.getByRole('button',{name:'Remove'}));
 expect((screen.getByLabelText('Research factor') as HTMLSelectElement).options).toHaveLength(2);
});

it('rejects missing anchors and out-of-range matrix before calling numerical API',async()=>{
 render(<TerrainResearchWorkbench dem={asset} geometry={polygon} assets={[asset,second]} connected/>);
 change('Factor high','');
 fireEvent.click(screen.getByRole('button',{name:'Run research model'}));
 expect(await screen.findByText(/Every factor needs/)).toBeTruthy();
 expect(api.runTerrainResearch).not.toHaveBeenCalled();
 change('Factor high','200');
 const advanced=screen.getByText('Model validation & sensitivity');
 fireEvent.click(advanced);
 fireEvent.click(screen.getByLabelText('AHP pairwise matrix'));
 change('Research AHP matrix JSON','not-json');
 fireEvent.click(screen.getByRole('button',{name:'Run research model'}));
 expect(api.runTerrainResearch).not.toHaveBeenCalled();
});

it('never starts a research operation without a valid study polygon',()=>{
 render(<TerrainResearchWorkbench dem={asset} geometry={null} assets={[asset]} connected/>);
 fireEvent.click(screen.getByRole('button',{name:'Run research model'}));
 expect(screen.getByText('Select a DEM and polygon study area.')).toBeTruthy();
 expect(api.runTerrainResearch).not.toHaveBeenCalled();
});
