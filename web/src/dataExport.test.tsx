// @vitest-environment jsdom
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import DataWorkbench from './DataWorkbench';
import ExportWorkbench from './ExportWorkbench';
import type {NetworkPolygonization,NetworkFace} from './api';
import type {ScratchFeature} from './scratch';

const api=vi.hoisted(()=>({
 importVectorFile:vi.fn(),uploadImagery:vi.fn(),saveFeatureBatch:vi.fn(),
 exportVectorFile:vi.fn(),exportProject:vi.fn(),downloadMapPDF:vi.fn(),
 downloadDatasetExport:vi.fn(),preflightDatasetExport:vi.fn(),startDatasetExport:vi.fn(),
 getGISJob:vi.fn(),cancelGISJob:vi.fn(),downloadExchangeJob:vi.fn(),downloadProjectPackage:vi.fn(),
 inspectDatasetFiles:vi.fn(),inspectDatasetOptions:vi.fn(),discardDatasetUpload:vi.fn(),startDatasetImport:vi.fn(),restoreProjectPackage:vi.fn(),
 bufferGeometry:vi.fn(),applyOverlay:vi.fn(),transformProjectCoordinates:vi.fn(),
}));
vi.mock('./api',()=>api);
vi.mock('./DataServicesPanel',()=>({
 default:({view}:{view:string})=><div data-testid="data-source-panel">{view}</div>,
}));
vi.mock('./ApiAccessPanel',()=>({
 default:()=><div data-testid="data-api-access">API access</div>,
}));

const geometry:GeoJSON.Polygon={type:'Polygon',
 coordinates:[[[0,0],[.01,0],[.01,.01],[0,.01],[0,0]]]};
const measured={
 geometry_type:'Polygon',area_m2:1234000,area_km2:1.234,
 perimeter_m:4400,length_m:null,bounds:[0,0,.01,.01],
 coordinate_count:5,method:'WGS84 ellipsoid',note:'',
};
const face:NetworkFace={
 id:'area-1',name:'Area 1',geometry,measurement:measured,
 label_anchor:[.005,.005],
 properties:{source_type:'polygonized_network',area_m2:1234000,
  perimeter_m:4400,snap_tolerance_m:1},
};
const polygonized:NetworkPolygonization={
 faces:[face],count:1,area_m2:1234000,dangles:0,cuts:0,
 invalid_rings:0,source_segments:4,tolerance_m:1,
 method:'GEOS',warning:'Only enclosed areas have area',
};
beforeEach(()=>{
 vi.resetAllMocks();
 api.importVectorFile.mockResolvedValue({created:1});
 api.uploadImagery.mockResolvedValue({id:'dem',name:'DEM'});
 api.saveFeatureBatch.mockResolvedValue({created:1,results:[]});
 api.exportVectorFile.mockResolvedValue(undefined);
 api.downloadDatasetExport.mockResolvedValue(undefined);
 api.preflightDatasetExport.mockResolvedValue({count:620,schema:[{name:"name"},{name:"category"}],geometry_types:["Point"],warnings:[],target_crs:"EPSG:4326"});
 api.discardDatasetUpload.mockResolvedValue(undefined);
 api.cancelGISJob.mockResolvedValue({id:"job",status:"cancelled",progress:100});
 api.exportProject.mockResolvedValue({type:'FeatureCollection',features:[{
  type:'Feature',geometry,properties:{name:'Area'}}]});
 api.downloadMapPDF.mockResolvedValue(undefined);
 api.bufferGeometry.mockResolvedValue({geometry,measurement:measured});
 api.applyOverlay.mockResolvedValue({geometry,measurement:measured});
 api.transformProjectCoordinates.mockResolvedValue({
  source:'EPSG:4326',target:'EPSG:3857',coordinates:[[111319.49,111325.14]],units:'meter',
 });
 Object.defineProperty(URL,'createObjectURL',{configurable:true,value:vi.fn(()=> 'blob:geofathom-test')});
 Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()});
});
afterEach(cleanup);

function dataProps(){
 return {
  projectId:'project-1',workspace:null,viewport:[0,0,1,1] as [number,number,number,number],
  geometry,network:polygonized,networkNotice:'One face',sourceCount:2,connected:true,
  onRebuild:vi.fn(async()=>{}),onStoreAreas:vi.fn(),
  onRefresh:vi.fn(),onTiles:vi.fn(),onPreview:vi.fn(),onPage:vi.fn(),
  onRasterAdded:vi.fn(),onOpenLayers:vi.fn(),
  vectorSources:[{id:'other',name:'Parcel B',geometry:{
   type:'Polygon' as const,coordinates:[[[.02,.02],[.03,.02],[.03,.03],[.02,.02]]],
  }}],
  onDerived:vi.fn(),
 };
}
function exportProps(){
 return {
  projectId:'project-1',workspace:{layers:[],features:[],total:0},
  selected:geometry,measurement:measured,
  scratch:[{id:'local-1',name:'Draft',geometry,measurement:measured,
   visible:true} as ScratchFeature],faces:[face],terrainRasters:[],
  viewport:[0,0,1,1] as [number,number,number,number],
 };
}
describe('Data and Export independent fixed workbenches',()=>{
 it('imports a validated vector dataset and refreshes its owning project',async()=>{
  const props=dataProps();
  render(<DataWorkbench {...props}/>);
  fireEvent.click(screen.getByRole('button',{name:'Import'}));
  const dataset=new File(['{}'],'parcels.geojson',{type:'application/geo+json'});
  fireEvent.change(screen.getByLabelText('Import dataset file'),{target:{files:[dataset]}});
  fireEvent.click(screen.getByRole('button',{name:'Import & validate'}));
  await waitFor(()=>expect(api.importVectorFile).toHaveBeenCalledWith('project-1',dataset,undefined));
  expect(props.onRefresh).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/Imported 1 validated features/)).toBeTruthy();
 });
 it('recomputes noded areas with user-selected tolerance and keeps faces independently',async()=>{
  const props=dataProps();
  render(<DataWorkbench {...props}/>);
  fireEvent.change(screen.getByLabelText('Network snap tolerance'),{target:{value:'2.5'}});
  fireEvent.click(screen.getByRole('button',{name:'Detect enclosed areas'}));
  await waitFor(()=>expect(props.onRebuild).toHaveBeenCalledWith(2.5,.01));
  expect(screen.getAllByText(/1.23 km²/).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button',{name:'Keep areas locally'}));
  expect(props.onStoreAreas).toHaveBeenCalledWith([face]);
  fireEvent.click(screen.getByRole('button',{name:'Save areas to project'}));
  await waitFor(()=>expect(api.saveFeatureBatch).toHaveBeenCalled());
  expect(api.saveFeatureBatch.mock.calls[0][1][0].properties.source_type).toBe('polygonized_network');
 });
 it('system tools select indexed database, jobs and access without duplicate pages',()=>{
  render(<DataWorkbench {...dataProps()}/>);
  fireEvent.click(screen.getByRole('button',{name:'System'}));
  expect(screen.getByTestId('data-source-panel').textContent).toBe('database');
  fireEvent.change(screen.getByLabelText('Data system operation'),{target:{value:'jobs'}});
  expect(screen.getByTestId('data-source-panel').textContent).toBe('jobs');
 });
 it('Data performs real polygon union and saves a detached derived geometry',async()=>{
  const props=dataProps();
  render(<DataWorkbench {...props}/>);
  fireEvent.click(screen.getByRole('button',{name:'Process'}));
  fireEvent.change(screen.getByLabelText('Processing reference feature'),{target:{value:'other'}});
  fireEvent.click(screen.getByRole('button',{name:'Run union'}));
  await waitFor(()=>expect(api.applyOverlay).toHaveBeenCalled());
  expect(props.onDerived).toHaveBeenCalledWith(geometry,measured,'union derived feature');
 });
 it('Data transforms source coordinates through project CRS service',async()=>{
  render(<DataWorkbench {...dataProps()}/>);
  fireEvent.click(screen.getByRole('button',{name:'Process'}));
  fireEvent.change(screen.getByLabelText('Data processing operation'),{target:{value:'reproject'}});
  fireEvent.change(screen.getByLabelText('Source longitude'),{target:{value:'1'}});
  fireEvent.change(screen.getByLabelText('Source latitude'),{target:{value:'1'}});
  fireEvent.click(screen.getByRole('button',{name:'Run reproject'}));
  await waitFor(()=>expect(api.transformProjectCoordinates).toHaveBeenCalledWith(
   'project-1',[[1,1]],'EPSG:3857'));
 });
 it('exports selection GeoJSON and detected-area measurements CSV',async()=>{
  render(<ExportWorkbench {...exportProps()}/>);
  fireEvent.click(screen.getByRole('button',{name:'Export GEOJSON'}));
  await waitFor(()=>expect(api.downloadDatasetExport).toHaveBeenCalledWith(
   "project-1",expect.objectContaining({format:"geojson",collection:expect.objectContaining({features:expect.any(Array)})}),expect.any(AbortSignal)));
  fireEvent.change(screen.getByLabelText('Export scope'),{target:{value:'areas'}});
  fireEvent.change(screen.getByLabelText('Export format'),{target:{value:'csv'}});
  fireEvent.click(screen.getByRole('button',{name:'Export CSV'}));
  await waitFor(()=>expect(api.downloadDatasetExport).toHaveBeenCalledTimes(2));
  expect(api.downloadDatasetExport.mock.calls[1][1]).toMatchObject({format:"csv",include_measurements:true,collection:{features:[{properties:{name:"Area 1"}}]}});
 });
 it('project GeoPackage uses server OGR export and map PDF uses project print engine',async()=>{
  const props=exportProps();
  props.workspace={layers:[],features:[{id:'f1',geometry,name:'Feature'} as never],total:1};
  render(<ExportWorkbench {...props}/>);
  fireEvent.change(screen.getByLabelText('Export scope'),{target:{value:'project'}});
  fireEvent.change(screen.getByLabelText('Export format'),{target:{value:'gpkg'}});
  fireEvent.click(screen.getByRole('button',{name:'Export GPKG'}));
  await waitFor(()=>expect(api.downloadDatasetExport).toHaveBeenCalledWith('project-1',expect.objectContaining({format:'gpkg'}),expect.any(AbortSignal)));
  expect(api.downloadDatasetExport.mock.calls[0][1].collection).toBeUndefined();
  fireEvent.change(screen.getByLabelText('Export format'),{target:{value:'pdf'}});
  fireEvent.click(screen.getByRole('button',{name:'Export PDF'}));
  await waitFor(()=>expect(api.downloadMapPDF).toHaveBeenCalled());
  expect(api.downloadMapPDF.mock.calls[0][1]).toMatchObject({
   title:'GeoFathom survey',paper:'a4',show_grid:true,show_legend:true,
  });
 });
 it('disables unusable formats and does not generate fake GeoTIFFs',()=>{
  const props=exportProps();
  render(<ExportWorkbench {...props}/>);
  fireEvent.change(screen.getByLabelText('Export format'),{target:{value:'geotiff'}});
  expect((screen.getByRole('button',{name:'Export GEOTIFF'}) as HTMLButtonElement).disabled).toBe(true);
 });
});

describe('comprehensive dataset delivery',()=>{
 it('exports every project record and selected attributes independently of the loaded page',async()=>{
  const props=exportProps();props.workspace.total=620;render(<ExportWorkbench {...props}/>);
  fireEvent.change(screen.getByLabelText('Export scope'),{target:{value:'project'}});
  expect(screen.getByText('620')).toBeTruthy();fireEvent.click(screen.getByRole('button',{name:'Inspect export'}));
  await waitFor(()=>expect(screen.getByText(/620 features/)).toBeTruthy());
  fireEvent.change(screen.getByLabelText('Export setup'),{target:{value:'fields'}});
  const select=screen.getByLabelText('Export attribute fields') as HTMLSelectElement;
  Array.from(select.options).forEach(o=>o.selected=o.value==='category');fireEvent.change(select);
  expect(screen.getByLabelText('Export attribute fields')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Export GEOJSON'}));
  await waitFor(()=>expect(api.downloadDatasetExport).toHaveBeenCalled());
  expect(api.downloadDatasetExport.mock.calls[0][1]).toEqual({format:'geojson',target_crs:'EPSG:4326',include_measurements:false,fields:['category']});
 });
 it('ignores stale export preflight after switching project A–B–A',async()=>{
  let resolve!:(value:unknown)=>void;api.preflightDatasetExport.mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));
  const props=exportProps();const view=render(<ExportWorkbench {...props}/>);
  fireEvent.click(screen.getByRole('button',{name:'Inspect export'}));
  view.rerender(<ExportWorkbench {...props} projectId="project-2"/>);view.rerender(<ExportWorkbench {...props}/>);
  resolve({count:999,schema:[],geometry_types:['Point'],warnings:[],target_crs:'EPSG:4326'});
  await waitFor(()=>expect(screen.queryByText(/999 features/)).toBeNull());
 });
 it('inspects batch files and submits explicit source layers',async()=>{
  api.inspectDatasetFiles.mockResolvedValue({upload_id:'upload',files:[{id:'file',name:'many.gpkg',bytes:20,layers:[
   {name:'roads',feature_count:620,source_crs:'EPSG:3857',fields:[{name:'height',type:'number'}]},
   {name:'sites',feature_count:3,source_crs:'EPSG:4326',fields:[]},
  ]}]});
  api.startDatasetImport.mockResolvedValue({id:'job',status:'completed',progress:100,result:{created:620,rejected:0}});
  render(<DataWorkbench {...dataProps()}/>);
  fireEvent.click(screen.getByRole('button',{name:'Import'}));fireEvent.click(screen.getByRole('button',{name:'Advanced import'}));
  fireEvent.change(screen.getByLabelText('Batch dataset files'),{target:{files:[new File(['x'],'many.gpkg')]}});
  await waitFor(()=>expect(screen.getByText('many.gpkg')).toBeTruthy());
  const layers=screen.getByLabelText('Source layers') as HTMLSelectElement;
  Array.from(layers.options).forEach(o=>o.selected=o.value==='roads');fireEvent.change(layers);
  fireEvent.click(screen.getByRole('button',{name:'Import batch'}));
  await waitFor(()=>expect(api.startDatasetImport).toHaveBeenCalledWith('project-1','upload',[{id:'file',options:{layers:['roads']}}],''));
 });
 it('discards an inspected upload returned after switching A–B–A',async()=>{
  let resolve!:(value:unknown)=>void;api.inspectDatasetFiles.mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));
  const props=dataProps();const view=render(<DataWorkbench {...props}/>);
  fireEvent.click(screen.getByRole('button',{name:'Import'}));fireEvent.click(screen.getByRole('button',{name:'Advanced import'}));
  fireEvent.change(screen.getByLabelText('Batch dataset files'),{target:{files:[new File(['x'],'late.gpkg')]}});
  view.rerender(<DataWorkbench {...props} projectId="project-2"/>);view.rerender(<DataWorkbench {...props}/>);
  resolve({upload_id:'late-upload',files:[{id:'late',name:'late.gpkg',layers:[]}]});
  await waitFor(()=>expect(api.discardDatasetUpload).toHaveBeenCalledWith('project-1','late-upload'));
  expect(screen.queryByText('late.gpkg')).toBeNull();expect(props.onRefresh).not.toHaveBeenCalled();
 });
});

it('quick import cannot refresh or show success after project A–B–A',async()=>{
 let resolve!:(value:unknown)=>void;api.importVectorFile.mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));
 const props=dataProps();const view=render(<DataWorkbench {...props}/>);
 fireEvent.click(screen.getByRole('button',{name:'Import'}));
 fireEvent.change(screen.getByLabelText('Import dataset file'),{target:{files:[new File(['{}'],'late.geojson')]}});
 fireEvent.click(screen.getByRole('button',{name:'Import & validate'}));
 view.rerender(<DataWorkbench {...props} projectId="project-2"/>);view.rerender(<DataWorkbench {...props}/>);
 resolve({created:99});await new Promise(r=>setTimeout(r,0));
 expect(props.onRefresh).not.toHaveBeenCalled();expect(screen.queryByText(/Imported 99/)).toBeNull();
});
