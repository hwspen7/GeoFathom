// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import ProfessionalPanel from './ProfessionalPanel';
import CartographyProPanel from './CartographyProPanel';
import type {ComponentProps} from 'react';
import type {GeoLayer,GeoWorkspace,RasterAsset} from './api';
const api=vi.hoisted(()=>({queryAttributes:vi.fn(),saveAttributes:vi.fn(),exportVectorFile:vi.fn(),
  importVectorFile:vi.fn(),analyzeTerrain:vi.fn(),terrainProfile:vi.fn(),getProjectCRS:vi.fn(),
  getProjectGrid:vi.fn(),patchLayerStyle:vi.fn(),saveGraduatedStyle:vi.fn(),saveProjectCRS:vi.fn(),
  transformProjectCoordinates:vi.fn()}));
vi.mock('./api',()=>api);
const point:GeoJSON.Point={type:'Point',coordinates:[10,20]};
const bbox:[number,number,number,number]=[10,20,10.01,20.01];
const layer:GeoLayer={id:'layer',project_id:'p',name:'Parcels',color:'#2563eb',visible:1,locked:0,z_index:0,style_revision:3,
  style:{labels:{enabled:true,field:'name',font_size:12,text_color:'#183954',halo_color:'#ffffff',halo_width:1.5,
  min_zoom:0,max_zoom:24,allow_overlap:false,priority:50,offset_x:0,offset_y:0,prefix:'',suffix:'',placement:'auto',
  callout:false,rule_field:'',rule_operator:'equals',rule_value:''},symbol:{fill_opacity:.17,line_width:3,
  point_radius:5,stroke_color:'#ffffff',category_field:'',category_colors:{},graduated_field:'',
  graduated_method:'quantile',graduated_breaks:[],graduated_colors:[]}}};
const feature={id:'f',name:'Parcel',revision:4,layer_id:'layer',project_id:'p',geometry:point,properties:{population:12},
  source:'Survey',created_at:'2026-01-01',measurement:{geometry_type:'Point',area_m2:null,area_km2:null,perimeter_m:null,
  length_m:null,bounds:[10,20,10,20],coordinate_count:1,method:'test',note:''}};
const workspace:GeoWorkspace={layers:[layer],features:[feature],total:1};
const raster:RasterAsset={id:'dem',name:'Terrain',width:20,height:20,bands:1,crs:'EPSG:26917',bbox,
  corners:[[10,20],[10.01,20],[10.01,20.01],[10,20.01]],preview_url:'/imagery/dem/preview',acquired_at:null,provenance:'fixture'};
const change=(name:string,value:string)=>fireEvent.change(screen.getByLabelText(name),{target:{value}});
const click=(name:string)=>fireEvent.click(screen.getByRole('button',{name}));
const open=(container:HTMLElement)=>container.querySelectorAll('details').forEach(d=>d.open=true);
beforeEach(()=>{
  vi.resetAllMocks();
  api.queryAttributes.mockResolvedValue({total:1,fields:['name','source','population'],results:[feature]});
  api.getProjectCRS.mockResolvedValue({project_id:'p',epsg:'EPSG:4326',grid_visible:0,revision:2});
});
afterEach(cleanup);
describe('professional GIS',()=>{
  function props():ComponentProps<typeof ProfessionalPanel>{
    return {projectId:'p',workspace,geometry:point,raster,refreshToken:0,onRefresh:vi.fn(),onOpen:vi.fn()};
  }
  it('validates numeric edits, persists revisioned properties, and rejects locked layers',async()=>{
    const p=props();const {container,rerender}=render(<ProfessionalPanel {...p}/>);open(container);
    await screen.findByRole('button',{name:'Parcel'});
    click('Parcel');expect(p.onOpen).toHaveBeenCalledWith('f');
    change('Attribute search field','population');change('Attribute search operator','gte');
    change('Attribute search value','10');click('Filter rows');
    await waitFor(()=>expect(api.queryAttributes).toHaveBeenCalledWith('p',{field:'population',operator:'gte',value:'10',limit:100}));
    await waitFor(()=>expect((screen.getByRole('button',{name:'Filter rows'}) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByLabelText('Select Parcel'));
    change('Attribute property name','height');change('Attribute value type','number');change('New attribute value','bad');
    click('Save properties & revisions');expect(await screen.findByText('Provide a finite number.')).toBeTruthy();
    expect(api.saveAttributes).not.toHaveBeenCalled();
    change('New attribute value','42');api.saveAttributes.mockResolvedValue({count:1});
    click('Save properties & revisions');await screen.findByText('Updated 1 feature attributes atomically.');
    expect(api.saveAttributes).toHaveBeenCalledWith('p',[{id:'f',expected_revision:4,properties:{height:42}}]);
    rerender(<ProfessionalPanel {...p} workspace={{...workspace,layers:[{...layer,locked:1}]}}/>);
    fireEvent.click(screen.getByLabelText('Select Parcel'));click('Save properties & revisions');
    expect(await screen.findByText('Unlock all selected feature layers before editing.')).toBeTruthy();
    expect(api.saveAttributes).toHaveBeenCalledTimes(1);
  });
  it('imports and exports vector files and renders real returned terrain values',async()=>{
    const p=props();const {container,rerender}=render(<ProfessionalPanel {...p}/>);open(container);
    const file=new File(['{}'],'data.geojson');
    api.importVectorFile.mockResolvedValue({created:2});
    fireEvent.change(screen.getByLabelText('Import GIS vector file'),{target:{files:[file]}});
    await screen.findByText('Imported 2 georeferenced GIS features.');
    expect(api.importVectorFile).toHaveBeenCalledWith('p',file);
    change('GIS export format','shapefile');api.exportVectorFile.mockResolvedValue(undefined);
    click('Export');await screen.findByText('GIS export prepared.');
    expect(api.exportVectorFile).toHaveBeenCalledWith('p','shapefile');
    api.analyzeTerrain.mockResolvedValue({elevation_min_m:100,elevation_max_m:150,elevation_relief_m:50,
      mean_slope_deg:0,mean_aspect_deg:null,valid_pixels:64,engine:'native'});
    click('Analyze selected terrain area');await screen.findByText('100.0–150.0 m');expect(screen.getByText('Flat')).toBeTruthy();
    const line:GeoJSON.LineString={type:'LineString',coordinates:[[10,20],[10.01,20.01]]};
    rerender(<ProfessionalPanel {...p} geometry={line}/>);
    api.terrainProfile.mockResolvedValue({samples:[{distance_m:0,elevation_m:100},{distance_m:10,elevation_m:null},{distance_m:20,elevation_m:150}]});
    click('Analyze selected elevation profile');await screen.findByRole('img',{name:'Elevation profile'});
    expect(api.terrainProfile).toHaveBeenCalledWith('dem',line);
    expect(screen.getByText('2 valid samples · 100.0–150.0 m')).toBeTruthy();
    expect(screen.queryByText('Flat')).toBeNull();
    api.terrainProfile.mockRejectedValue(new Error('No DEM coverage'));click('Analyze selected elevation profile');
    expect(await screen.findByText('No DEM coverage')).toBeTruthy();
  });
});
describe('cartography',()=>{
  it('persists classifications, advanced label revisions and projected grid coordinates',async()=>{
    const p:ComponentProps<typeof CartographyProPanel>={projectId:'p',workspace,viewport:bbox,selectedGeometry:point,
      onChanged:vi.fn(),onGrid:vi.fn(),labelMoveMode:false,onLabelMoveMode:vi.fn()};
    const {container}=render(<CartographyProPanel {...p}/>);open(container);
    change('Graduated numeric field','population');change('Graduated method','jenks');change('Graduated class count','3');
    api.saveGraduatedStyle.mockResolvedValue({classification:{classes:3,samples:6,breaks:[10,20]},layer:{...layer,style_revision:4}});
    click('Calculate & save color classes');await screen.findByText('3 graduated classes using 6 values; breaks: 10.00, 20.00');
    expect(api.saveGraduatedStyle).toHaveBeenCalledWith('p',expect.objectContaining({layer_id:'layer',field:'population',classes:3,method:'jenks',expected_revision:3}));
    // Open the visible Mapping page before exercising its label controls.
    click('Labels');
    expect(screen.getByRole('button',{name:'Labels'}).getAttribute('aria-pressed')).toBe('true');
    api.patchLayerStyle.mockResolvedValue({...layer,style_revision:5,style:{...layer.style,labels:{...layer.style.labels,priority:80}}});
    fireEvent.blur(screen.getByLabelText('Label priority'),{target:{value:'80'}});
    await screen.findByText('Advanced label placement saved.');
    expect(api.patchLayerStyle).toHaveBeenCalledWith('p','layer',{labels:{priority:80},expected_revision:4});
    click('Move map labels');expect(p.onLabelMoveMode).toHaveBeenCalledWith(true);
    click('CRS');
    expect(screen.getByRole('button',{name:'CRS'}).getAttribute('aria-pressed')).toBe('true');
    api.saveProjectCRS.mockResolvedValue({project_id:'p',epsg:'EPSG:26917',grid_visible:1,revision:3});
    api.getProjectGrid.mockResolvedValue({type:'FeatureCollection',features:[]});
    change('Project EPSG code','EPSG:26917');fireEvent.click(screen.getByLabelText('Show project CRS grid'));
    await screen.findByText('Project EPSG and coordinate grid settings saved.');
    expect(api.saveProjectCRS).toHaveBeenCalledWith('p','EPSG:26917',true,2);
    await waitFor(()=>expect(p.onGrid).toHaveBeenCalledWith({type:'FeatureCollection',features:[]}));
    api.transformProjectCoordinates.mockResolvedValue({coordinates:[[123,456]],units:'metre'});
    click('Transform map/point coordinates');await screen.findByText('123.000, 456.000 metre');
    expect(api.transformProjectCoordinates).toHaveBeenCalledWith('p',[[10,20]],'EPSG:26917');
  });
});
