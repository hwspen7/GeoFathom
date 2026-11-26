// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import SpatialSciencePanel from './SpatialSciencePanel';
const mocked=vi.hoisted(()=>({catalog:vi.fn(),run:vi.fn()}));
vi.mock('./api',()=>({getSpatialScienceCatalog:mocked.catalog,runSpatialScience:mocked.run,getSpatialLayerSource:vi.fn(),getSpatialRasterSource:vi.fn()}));
vi.mock('./ScientificFigureStudio',()=>({default:()=>null}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
it('uses exact catalog parameters and returns only actual result geometry',async()=>{
 const geometry={type:'Point',coordinates:[-81,40.6]} as GeoJSON.Point;
 const feature={type:'Feature',geometry,properties:{}} as GeoJSON.Feature;
 mocked.catalog.mockResolvedValue({operation_count:1,operations:[{id:'buffer',group:'Vector',title:'Metric buffer',source:'vector',minimum:1,maximum:1,parameters:[{name:'distance_m',label:'Distance (m)',default:100,minimum:.01,maximum:100000,integer:false}],result:'vector',assumption:'Projected metres'}]});
 mocked.run.mockResolvedValue({operation:'buffer',receipt:{crs:'EPSG:32617',metrics:{}},features:{type:'FeatureCollection',features:[feature]},raster:null,columns:[],rows:[],csv:''});
 const onPreview=vi.fn();render(<SpatialSciencePanel geometry={geometry} connected onPreview={onPreview}/>);
 fireEvent.click(screen.getByRole('button',{name:'Open Spatial Analysis'}));
 await screen.findByRole('option',{name:'Metric buffer'});
 const run=screen.getByRole('button',{name:'Run analysis'});expect((run as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'Use current map geometry'}));
 fireEvent.change(screen.getByLabelText('Distance (m)'),{target:{value:'25'}});
 fireEvent.click(run);
 await screen.findByText(/1 features/);
 expect(mocked.run).toHaveBeenCalledWith(expect.objectContaining({operation:'buffer',epsg:32617,parameters:{distance_m:25},vectors:[{type:'FeatureCollection',features:[feature]}]}),expect.any(AbortSignal));
 fireEvent.click(screen.getByRole('button',{name:'Show vectors on map'}));expect(onPreview).toHaveBeenCalledWith([feature]);
 await waitFor(()=>expect(screen.queryByRole('dialog',{name:'Spatial science workbench'})).toBeNull());
});


it('distinguishes structural fits from held-out predictions',async()=>{
 mocked.catalog.mockResolvedValue({operation_count:2,operations:[
 {id:'spatial_lag_regression',group:'Integrated',title:'Spatial lag regression (2SLS)',source:'raster',minimum:2,maximum:8,parameters:[],result:'raster',assumption:'Conditional structural fit',requires_regression_view:true},
 {id:'geographically_weighted_regression',group:'Integrated',title:'Geographically weighted regression',source:'raster',minimum:2,maximum:8,parameters:[],result:'raster',assumption:'Leave-one-out',requires_regression_view:true}
 ]});
 render(<SpatialSciencePanel geometry={null} connected onPreview={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Open Spatial Analysis'}));
 await screen.findByRole('option',{name:'Structural fitted response'});
 fireEvent.change(screen.getByLabelText('Spatial algorithm group'),{target:{value:'Integrated'}});
 fireEvent.change(screen.getByLabelText('Spatial algorithm'),{target:{value:'geographically_weighted_regression'}});
 expect(screen.getByRole('option',{name:'Leave-one-out prediction'})).toBeTruthy();
 expect(screen.queryByRole('option',{name:'Out-of-fold prediction'})).toBeNull();
});


it('recommends Qingdao UTM and preserves an explicit CRS override',async()=>{
 const geometry:GeoJSON.Polygon={type:'Polygon',coordinates:[[[120.07,36.35],[120.08,36.35],[120.08,36.36],[120.07,36.35]]]};
 mocked.catalog.mockResolvedValue({operations:[{id:'sample_polygon',group:'Vector',title:'Uniform polygon point sample',source:'vector',minimum:1,maximum:1,parameters:[]}]});
 mocked.run.mockResolvedValue({operation:'sample_polygon',receipt:{metrics:{study_area_m2:11530000}},features:{type:'FeatureCollection',features:[{type:'Feature',geometry:{type:'Point',coordinates:[120.075,36.355]},properties:{}}]},rows:[],columns:[],csv:''});
 render(<SpatialSciencePanel geometry={geometry} connected onPreview={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Open Spatial Analysis'}));
 await screen.findByRole('option',{name:'Uniform polygon point sample'});
 const epsg=screen.getByLabelText('Projected EPSG (metres)') as HTMLInputElement;
 expect(epsg.value).toBe('32651');
 fireEvent.click(screen.getByRole('button',{name:'Use current map geometry'}));
 fireEvent.change(epsg,{target:{value:'32650'}});
 expect(epsg.value).toBe('32650');
 fireEvent.click(screen.getByRole('button',{name:'Automatic projected EPSG'}));
 expect(epsg.value).toBe('32651');
 fireEvent.click(screen.getByRole('button',{name:'Run analysis'}));
 await screen.findByText('11.53 km²');
 expect(screen.queryByText('Records',{exact:true})).toBeNull();
 expect(mocked.run).toHaveBeenCalledWith(expect.objectContaining({epsg:32651}),expect.any(AbortSignal));
});
