// @vitest-environment jsdom
import type {ComponentProps} from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import DiscoveryPanel from './DiscoveryPanel';
import ImageCorrectionPanel from './ImageCorrectionPanel';
import SurveyTools from './SurveyTools';
import RasterPanel from './RasterPanel';
import SpatialToolsPanel from './SpatialToolsPanel';
import GeoAIAnalysisPanel from './GeoAIAnalysisPanel';
import type {RasterAsset,WorkspaceFeature} from './api';

const api=vi.hoisted(()=>({
  discoverFeatures:vi.fn(),listImagery:vi.fn(),uploadImagery:vi.fn(),
  searchPublicImagery:vi.fn(),selectSpatialFeatures:vi.fn(),reviewTopology:vi.fn(),
  downloadMapPDF:vi.fn(),getGISJob:vi.fn(),getVisionModels:vi.fn(),
  queueGISJob:vi.fn(),saveFeatureBatch:vi.fn(),cancelGISJob:vi.fn(),downloadBuildingArtifact:vi.fn(),
}));
vi.mock('./api',()=>api);

const bbox:[number,number,number,number]=[10,20,10.01,20.01];
const point:GeoJSON.Point={type:'Point',coordinates:[10,20]};
const polygon:GeoJSON.Polygon={type:'Polygon',coordinates:[[[10,20],[10.01,20],[10.01,20.01],[10,20]]]};
const image:RasterAsset={id:'scene',name:'Test image',width:100,height:80,bands:4,
  crs:'EPSG:4326',bbox,corners:[[10,20],[10.01,20],[10.01,20.01],[10,20.01]],
  preview_url:'/imagery/scene/preview',acquired_at:null,provenance:'test'};
const change=(label:string|RegExp,value:string)=>fireEvent.change(screen.getByLabelText(label),{target:{value}});
const click=(name:string|RegExp)=>fireEvent.click(screen.getByRole('button',{name}));
const openDetails=(container:HTMLElement)=>container.querySelectorAll('details').forEach(node=>node.open=true);

beforeEach(()=>{
  vi.resetAllMocks();
  api.listImagery.mockResolvedValue([image,{...image,id:'later',name:'Second date'}]);
  api.getVisionModels.mockResolvedValue({runtime_available:true,models:[{id:'model',classes:['a','b']}]});
});
afterEach(cleanup);

describe('feature discovery',()=>{
  it('disables without bounds and passes exact area filters',async()=>{
    const found=vi.fn();
    const response={results:[],checked:3,truncated:false,warning:'test',category:'water',source:'provider'};
    api.discoverFeatures.mockResolvedValue(response);
    const {rerender}=render(<DiscoveryPanel viewport={null} busy={false} onFound={found}/>);
    expect((screen.getByRole('button') as HTMLButtonElement).disabled).toBe(true);
    rerender(<DiscoveryPanel viewport={bbox} busy={false} onFound={found}/>);
    change('Feature class','water');change('Min area (m²)','50');change('Max area (m²)','900');
    click('Find matching areas');
    await waitFor(()=>expect(found).toHaveBeenCalledWith(response));
    expect(api.discoverFeatures).toHaveBeenCalledWith({bbox,category:'water',minimum_area_m2:50,maximum_area_m2:900});
  });

  it('shows provider errors and resets submission state',async()=>{
    api.discoverFeatures.mockRejectedValueOnce(new Error('Provider offline')).mockRejectedValueOnce('unknown');
    render(<DiscoveryPanel viewport={bbox} busy={false} onFound={vi.fn()}/>);
    change('Min area (m²)','');
    click('Find matching areas');
    expect(await screen.findByText('Provider offline')).toBeTruthy();
    expect(api.discoverFeatures.mock.calls[0][0].minimum_area_m2).toBe(0);
    expect(api.discoverFeatures.mock.calls[0][0].maximum_area_m2).toBeNull();
    click('Find matching areas');
    expect(await screen.findByText('Could not search this area.')).toBeTruthy();
  });
});

describe('image mask correction',()=>{
  it('sends all prompt modes, disables empty refinement and supports clearing',()=>{
    const p:ComponentProps<typeof ImageCorrectionPanel>={enabled:true,mode:null,
      onMode:vi.fn(),positive:[],negative:[],box:[],busy:false,onClear:vi.fn(),onRefine:vi.fn()};
    const {rerender}=render(<ImageCorrectionPanel {...p}/>);
    expect((screen.getByRole('button',{name:'Refine mask'}) as HTMLButtonElement).disabled).toBe(true);
    click(/Include/);click(/Exclude/);click('Box');
    expect(p.onMode).toHaveBeenNthCalledWith(1,'positive');
    expect(p.onMode).toHaveBeenNthCalledWith(2,'negative');
    expect(p.onMode).toHaveBeenNthCalledWith(3,'box');
    for(const mode of ['positive','negative','box'] as const){
      rerender(<ImageCorrectionPanel {...p} mode={mode} positive={[[10,20]]}/>);
      click(mode==='positive'?/Include/:mode==='negative'?/Exclude/:'Box');
      expect(p.onMode).toHaveBeenLastCalledWith(null);
    }
    click('Refine mask');click('Clear prompts');
    expect(p.onRefine).toHaveBeenCalledOnce();expect(p.onClear).toHaveBeenCalledOnce();
    rerender(<ImageCorrectionPanel {...p} enabled={false} busy/>);
    expect((screen.getByRole('button',{name:'Box'}) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button',{name:'Clear prompts'}) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('survey controls',()=>{
  const props=():ComponentProps<typeof SurveyTools>=>({
    mode:null,geometry:null,points:[],editing:false,moving:false,snapping:true,canUndo:false,canRedo:false,
    saved:[],onStart:vi.fn(),onFinish:vi.fn(),onCancel:vi.fn(),onUndoPoint:vi.fn(),onUndo:vi.fn(),onRedo:vi.fn(),
    onEdit:vi.fn(),onSnapping:vi.fn(),onAddPoint:vi.fn(),onNumeric:vi.fn(),onOverlay:vi.fn(),
    onDuplicate:vi.fn(),linked:false,onLinked:vi.fn(),
  });
  it('gates polygon-only operations and connects drawing, editing and history actions',()=>{
    const p=props();
    const {rerender}=render(<SurveyTools {...p}/>);
    expect((screen.getByRole('button',{name:'Cut hole'}) as HTMLButtonElement).disabled).toBe(true);
    click('Polygon');click('Line');click('Rectangle');click('Circle');
    expect((screen.getByRole('button',{name:'Trace network'}) as HTMLButtonElement).disabled).toBe(true);
    expect(p.onStart).toHaveBeenCalledTimes(4);
    rerender(<SurveyTools {...p} saved={[{id:'saved-line',name:'Reference line',
      geometry:{type:'LineString',coordinates:[[10,20],[11,21]]}} as WorkspaceFeature]}/>);
    click('Trace network');
    expect(p.onStart).toHaveBeenCalledTimes(5);
    rerender(<SurveyTools {...p} geometry={polygon} mode="polygon" points={[[10,20]]} canUndo canRedo/>);
    expect((screen.getByRole('button',{name:'Finish'}) as HTMLButtonElement).disabled).toBe(true);
    rerender(<SurveyTools {...p} geometry={polygon} mode="polygon" points={[[10,20],[11,20],[11,21]]} canUndo canRedo/>);
    click('Cut hole');click('Split line');click('Finish');
    fireEvent.click(screen.getByRole('button',{name:'Undo last sketch point'}));
    fireEvent.click(screen.getByTitle('Cancel'));
    expect(screen.queryByRole('button',{name:'Vertices'})).toBeNull();
    expect(screen.queryByRole('button',{name:'Move'})).toBeNull();
    expect(screen.queryByRole('button',{name:'Copy'})).toBeNull();
    rerender(<SurveyTools {...p} geometry={polygon} mode={null} canUndo canRedo/>);
    click('Snap ON');click('Undo');click('Redo');
    click('Vertices');click('Move');click('Copy');
    fireEvent.click(screen.getByLabelText(/Linked\/shared vertices/));
    expect(p.onFinish).toHaveBeenCalledOnce();expect(p.onCancel).toHaveBeenCalledOnce();
    expect(p.onUndoPoint).toHaveBeenCalledOnce();expect(p.onEdit).toHaveBeenCalledWith(true,true);
    expect(p.onSnapping).toHaveBeenCalledWith(false);expect(p.onLinked).toHaveBeenCalledWith(true);
    expect(p.onUndo).toHaveBeenCalledOnce();expect(p.onRedo).toHaveBeenCalledOnce();expect(p.onDuplicate).toHaveBeenCalledOnce();
  });
  it('uses distinct drawing icons, short captions and contextual hover hints',()=>{
    const p=props();
    const {rerender}=render(<SurveyTools {...p}/>);
    const names=['Point','Polygon','Line','Rectangle','Circle','Cut hole','Split line','Trace network'];
    const buttons=names.map(name=>screen.getByRole('button',{name,exact:true}));
    // Lucide supplies a named class for each icon; all eight must differ.
    const icons=buttons.map(button=>Array.from(button.querySelector('svg')!.classList)
      .find(name=>name.startsWith('lucide-')));
    expect(icons.every(Boolean)).toBe(true);
    expect(new Set(icons).size).toBe(names.length);
    expect(buttons.map(button=>button.textContent)).toEqual(['Point','Polygon','Line','Rectangle','Circle','Hole','Split','Trace']);
    expect(buttons[0].getAttribute('title')).toBe('Draw point (P)');
    expect(buttons[5].parentElement?.getAttribute('title')).toBe('Select a polygon first');
    expect(buttons[7].parentElement?.getAttribute('title')).toBe('Save a vector line first');
    rerender(<SurveyTools {...p} geometry={polygon} locked/>);
    expect(screen.getByRole('button',{name:'Split line'}).getAttribute('title')).toBe('Unlock the selected layer');
    rerender(<SurveyTools {...p} geometry={polygon} saved={[{id:'network',name:'Network',
      geometry:{type:'LineString',coordinates:[[10,20],[11,21]]}} as WorkspaceFeature]}/>);
    expect(screen.getByRole('button',{name:'Split line'}).getAttribute('title')).toBe('Split polygon by line');
    expect(screen.getByRole('button',{name:'Trace network'}).getAttribute('title')).toBe('Trace saved network');
    const snap=screen.getByRole('button',{name:'Snap ON'});
    expect(snap.getAttribute('aria-pressed')).toBe('true');
    expect(snap.textContent).toBe('Snap');
    for(const name of ['Undo','Redo','Copy'])expect(screen.getByRole('button',{name}).getAttribute('title')).toBeTruthy();
  });
  it('preserves exact numerical coordinates and overlay identity',()=>{
    const p=props();
    render(<SurveyTools {...p} geometry={polygon} saved={[{id:'reference',name:'Parcel'} as WorkspaceFeature]}/>);
    click('Apply exact geometry');expect(p.onAddPoint).not.toHaveBeenCalled();
    change('Longitude','0');change('Latitude','22');click('Apply exact geometry');
    expect(p.onNumeric).toHaveBeenLastCalledWith('point',{vertices:[[0,22]]});
    change('Numeric construction mode','rectangle');change('Opposite longitude','1');change('Opposite latitude','23');
    click('Apply exact geometry');expect(p.onNumeric).toHaveBeenLastCalledWith('rectangle',{vertices:[[0,22],[1,23]],radius_m:100,bearing_deg:90,length_m:100});
    change('Numeric construction mode','circle');change('Radius or length in meters','500');
    click('Apply exact geometry');expect(p.onNumeric).toHaveBeenLastCalledWith('circle',{vertices:[[0,22]],radius_m:500,bearing_deg:90,length_m:500});
    change('Numeric construction mode','bearing');change('Bearing in degrees','45');click('Apply exact geometry');
    expect(p.onNumeric).toHaveBeenLastCalledWith('bearing',{vertices:[[0,22]],radius_m:500,bearing_deg:45,length_m:500});
    change('Boolean operation target','reference');click('Union');click('Subtract');click('Intersect');
    expect(vi.mocked(p.onOverlay).mock.calls).toEqual([['union','reference'],['difference','reference'],['intersection','reference']]);
  });
});

describe('raster controls',()=>{
  it('selects source, checks upload token, imports and invokes trace settings',async()=>{
    const p:ComponentProps<typeof RasterPanel>={asset:image,onSelect:vi.fn(),tracing:false,
      onTracing:vi.fn(),settings:{method:'color',tolerance:20,window_size:512},onSettings:vi.fn(),viewport:bbox};
    const {container,rerender}=render(<RasterPanel {...p}/>);
    await screen.findByRole('option',{name:'Test image'});
    change('Select georeferenced imagery','later');
    expect(p.onSelect).toHaveBeenLastCalledWith(expect.objectContaining({id:'later'}));
    const input=container.querySelector<HTMLInputElement>('input[type=file]')!;
    const file=new File(['tif'],'data.tif',{type:'image/tiff'});
    fireEvent.change(input,{target:{files:[file]}});
    expect(screen.getByText(/Enter the server administration token/)).toBeTruthy();
    change('Image import administration token','secret');
    api.uploadImagery.mockResolvedValueOnce({...image,id:'import'});
    fireEvent.change(input,{target:{files:[file]}});
    await waitFor(()=>expect(p.onSelect).toHaveBeenLastCalledWith(expect.objectContaining({id:'import'})));
    expect(api.uploadImagery).toHaveBeenCalledWith(file,'secret');
    change('Outline method','sam2');change('Window size','1024');change(/RGB tolerance/,'30');
    expect(p.onSettings).toHaveBeenCalledWith({method:'sam2',tolerance:20,window_size:512});
    expect(p.onSettings).toHaveBeenCalledWith({method:'color',tolerance:20,window_size:1024});
    expect(p.onSettings).toHaveBeenCalledWith({method:'color',tolerance:30,window_size:512});
    click('Start automatic outline');expect(p.onTracing).toHaveBeenCalledWith(true);
    rerender(<RasterPanel {...p} tracing settings={{...p.settings,method:'sam2'}}/>);
    expect(screen.queryByLabelText(/RGB tolerance/)).toBeNull();
    click('Click your target on the map');expect(p.onTracing).toHaveBeenLastCalledWith(false);
  });
  it('handles catalog results, empty results, and provider error',async()=>{
    const p:ComponentProps<typeof RasterPanel>={asset:null,onSelect:vi.fn(),tracing:false,onTracing:vi.fn(),
      settings:{method:'color',tolerance:20,window_size:512},onSettings:vi.fn(),viewport:bbox};
    api.searchPublicImagery.mockResolvedValueOnce({items:[{id:'x',datetime:null,cloud_cover:null,catalog_url:'https://example.test/scene'}]})
      .mockResolvedValueOnce({items:[]}).mockRejectedValueOnce(new Error('offline'));
    render(<RasterPanel {...p}/>);
    await screen.findByRole('option',{name:'Test image'});
    click('Find public satellite scenes in map view');
    expect(await screen.findByText(/Date unknown/)).toBeTruthy();
    expect(screen.getByRole('link',{name:'Catalog item'}).getAttribute('href')).toBe('https://example.test/scene');
    click('Find public satellite scenes in map view');expect(await screen.findByText(/No catalog scenes/)).toBeTruthy();
    click('Find public satellite scenes in map view');expect(await screen.findByText('offline')).toBeTruthy();
    expect(api.searchPublicImagery).toHaveBeenCalledWith(bbox);
  });
});

describe('spatial QA and print',()=>{
  it('checks spatial results, preserves selection and exports exact layout settings',async()=>{
    const p:ComponentProps<typeof SpatialToolsPanel>={projectId:'p',geometry:polygon,viewport:bbox,
      selectedIds:['f'],onSelected:vi.fn(),boxMode:false,onBoxMode:vi.fn(),box:bbox,onBox:vi.fn(),onIssues:vi.fn(),onOpen:vi.fn()};
    api.selectSpatialFeatures.mockResolvedValue({ids:['f'],results:[{id:'f',name:'Parcel'}],total:1});
    const issues=[{type:'overlap',message:'Duplicate area',area_m2:12,feature_ids:['f'],geometry:polygon}];
    api.reviewTopology.mockResolvedValue({issues,issue_count:1,checked_features:2});
    api.downloadMapPDF.mockResolvedValue(undefined);
    const {container}=render(<SpatialToolsPanel {...p}/>);openDetails(container);
    click('Draw selection rectangle');expect(p.onBoxMode).toHaveBeenCalledWith(true);
    change('Spatial relationship','within');fireEvent.click(screen.getByLabelText('Only visible layers'));
    click('Select spatial matches');expect(await screen.findByText('1 matches')).toBeTruthy();
    expect(api.selectSpatialFeatures).toHaveBeenCalledWith('p',expect.objectContaining({type:'Polygon'}),'within',null,false);
    click('Parcel');expect(p.onOpen).toHaveBeenCalledWith('f');
    click('Clear selection');expect(p.onSelected).toHaveBeenLastCalledWith([]);
    change('Topology threshold','1');click('Run topology QA');
    expect(await screen.findByText('1 topology issues')).toBeTruthy();expect(p.onIssues).toHaveBeenCalledWith(issues);
    click(/overlap: Duplicate area/);expect(p.onOpen).toHaveBeenLastCalledWith('f');
    change('PDF map title','My map');change('PDF paper','a3');change('PDF orientation','portrait');change('PDF extent','viewport');
    fireEvent.click(screen.getByLabelText('PDF include grid'));fireEvent.click(screen.getByLabelText('PDF include legend'));
    click('Export vector PDF');
    await waitFor(()=>expect(api.downloadMapPDF).toHaveBeenCalledWith('p',{title:'My map',paper:'a3',orientation:'portrait',extent:bbox,show_grid:false,show_legend:false,layer_ids:null}));
    expect(await screen.findByText('Vector PDF map exported.')).toBeTruthy();
  });
  it('rejects a viewport print before map initialization',async()=>{
    const p:ComponentProps<typeof SpatialToolsPanel>={projectId:'p',geometry:null,viewport:null,selectedIds:[],
      onSelected:vi.fn(),boxMode:false,onBoxMode:vi.fn(),box:null,onBox:vi.fn(),onIssues:vi.fn(),onOpen:vi.fn()};
    const {container}=render(<SpatialToolsPanel {...p}/>);openDetails(container);
    change('PDF extent','viewport');click('Export vector PDF');
    expect(await screen.findByText('Map viewport is not ready.')).toBeTruthy();expect(api.downloadMapPDF).not.toHaveBeenCalled();
  });
});

describe('GeoAI analysis controls',()=>{
  it('runs building extraction at native resolution with selected AOI, then exposes checked scientific outputs',async()=>{
    api.getVisionModels.mockResolvedValue({runtime_available:true,models:[
      {id:'generic',classes:['background','other']},
      {id:'buildings',task:'building_extraction',classes:['background','building']},
    ]});
    api.queueGISJob.mockResolvedValue({id:'building-job',status:'completed',progress:100,result:{
      type:'FeatureCollection',features:[],analysis:'building_extraction',provider:'onnxruntime',
      source_images:['scene'],valid_pixels:8000,warning:'Review footprints',
      summary:{candidate_count:0,total_area_m2:0,foreground_fraction:0},
      artifacts:{'probability.tif':{sha256:'a',size_bytes:100}},
    }});
    api.downloadBuildingArtifact.mockResolvedValue(undefined);
    const {container}=render(<GeoAIAnalysisPanel projectId="p" image={image} studyArea={polygon}
      onPreview={vi.fn()} onSaved={vi.fn()}/>);openDetails(container);
    change('GeoAI analysis operation','semantic_segmentation');
    await screen.findByRole('option',{name:/generic/});
    change('GeoAI analysis operation','building_extraction');
    expect(screen.queryByRole('option',{name:/generic/})).toBeNull();
    expect(screen.queryByLabelText('GeoAI processing resolution')).toBeNull();
    fireEvent.click(screen.getByLabelText('Limit buildings to selected study area'));
    change('Building probability threshold','0.6');change('Minimum building footprint area','12');
    change('GeoAI administration token','admin');click('Run georeferenced analysis');
    await waitFor(()=>expect(api.queueGISJob).toHaveBeenCalledWith('p','building_extraction',{
      image_id:'scene',model_id:'buildings',probability_threshold:.6,minimum_area_m2:12,
      full_resolution:true,memory_mb:64,max_pixels:16777216,aoi:polygon,
      instance_mode:'connected',seed_distance:6},'admin'));
    await screen.findByText('0 building candidates · 0.0 m² retained area');
    click('Download probability.tif');
    await waitFor(()=>expect(api.downloadBuildingArtifact).toHaveBeenCalledWith('p','building-job','probability.tif'));
  });
  it('keeps building extraction disabled until a dedicated model is installed',async()=>{
    const {container}=render(<GeoAIAnalysisPanel projectId="p" image={image}
      onPreview={vi.fn()} onSaved={vi.fn()}/>);openDetails(container);
    await waitFor(()=>expect(api.getVisionModels).toHaveBeenCalled());
    change('GeoAI analysis operation','building_extraction');change('GeoAI administration token','admin');
    expect((screen.getByRole('button',{name:'Run georeferenced analysis'}) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText('Limit buildings to selected study area') as HTMLInputElement).disabled).toBe(true);
  });
  it('validates bands and second-date identity, then preserves full-resolution job budgets',async()=>{
    const p:ComponentProps<typeof GeoAIAnalysisPanel>={projectId:'p',image,onPreview:vi.fn(),onSaved:vi.fn()};
    api.queueGISJob.mockResolvedValue({id:'job-1234',status:'failed',progress:0,error:'controlled task failure'});
    const {container}=render(<GeoAIAnalysisPanel {...p}/>);openDetails(container);
    await waitFor(()=>expect(api.getVisionModels).toHaveBeenCalled());
    change('GeoAI administration token','admin');change('Spectral first band','1');
    click('Run georeferenced analysis');expect(await screen.findByText(/Choose two different bands/)).toBeTruthy();
    change('Spectral first band','4');change('GeoAI analysis operation','spectral_change');
    click('Run georeferenced analysis');expect(await screen.findByText(/Choose a different second date/)).toBeTruthy();
    await screen.findByRole('option',{name:'Second date'});
    change('Second date georeferenced image','later');
    fireEvent.click(screen.getByLabelText('Process full image at native pixel resolution'));
    change('GeoAI tile size','128');change('GeoAI tile memory budget','64');change('GeoAI pixel processing limit','67108864');
    click('Run georeferenced analysis');
    await waitFor(()=>expect(api.queueGISJob).toHaveBeenCalledWith('p','spectral_change',{
      image_id:'scene',max_side:512,first_band:4,second_band:1,threshold:.2,after_image_id:'later',
      full_resolution:true,tile_size:128,memory_mb:64,max_pixels:67108864},'admin'));
    expect(await screen.findByText('controlled task failure')).toBeTruthy();
  });
  it('previews and saves completed image-derived features with provenance',async()=>{
    const p:ComponentProps<typeof GeoAIAnalysisPanel>={projectId:'p',image,onPreview:vi.fn(),onSaved:vi.fn()};
    const feature={type:'Feature',geometry:point,properties:{class_name:'Target'}};
    api.queueGISJob.mockResolvedValue({id:'job-1234',status:'completed',progress:100,has_result:true,result:{
      type:'FeatureCollection',features:[feature],valid_pixels:10,analysis:'spectral_index',provider:'native',
      engine:'cpu',source_images:['scene'],warning:'Review'}});api.saveFeatureBatch.mockResolvedValue({created:1});
    const {container}=render(<GeoAIAnalysisPanel {...p}/>);openDetails(container);
    change('GeoAI administration token','admin');click('Run georeferenced analysis');
    await screen.findByRole('button',{name:'Preview on map'});click('Preview on map');
    expect(p.onPreview).toHaveBeenLastCalledWith([point]);
    click('Save candidates');
    await waitFor(()=>expect(p.onSaved).toHaveBeenCalledOnce());
    expect(api.saveFeatureBatch.mock.calls[0][1][0].properties).toMatchObject({
      source_type:'image_derived',quality:'requires_user_review',source_images:['scene']});
    click('Clear preview');expect(p.onPreview).toHaveBeenLastCalledWith([]);
  });
});
