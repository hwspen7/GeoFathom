// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import type {ComponentProps} from 'react';
import TerrainWorkbench from './TerrainWorkbench';
import type {PersistedTerrainResult} from './terrainResultStore';

const store=vi.hoisted(()=>({loadTerrainResults:vi.fn()}));
vi.mock('./terrainResultStore',()=>store);
afterEach(()=>{cleanup();localStorage.clear();vi.restoreAllMocks();});

it('retains a selected scientific export outside the hidden Terrain module',async()=>{
 const source={id:'dem',name:'Survey DEM',width:2,height:2,bands:1,
  crs:'EPSG:32631',bbox:[0,0,.01,.01] as [number,number,number,number],
  corners:[[0,0],[.01,0],[.01,.01],[0,.01]] as [[number,number],[number,number],[number,number],[number,number]],
  preview_url:'',acquired_at:null,provenance:'Synthetic DEM',sha256:'a'.repeat(64)};
 const geometry:GeoJSON.Polygon={type:'Polygon',coordinates:[[[0,0],[.01,0],[.01,.01],[0,0]]]};
 const record:PersistedTerrainResult={id:'run-1',title:'Elevation map',operation:'elevation',
  source,geometry,inputKey:'stored',visible:false,createdAt:1,opacity:.5,resampling:'nearest',
  advanced:{operation:'elevation',source_crs:source.crs,valid_cells:4,missing_cells:0,
   cell_area_m2:100,metrics:{product_mean:120},warning:'Synthetic',features:[]}};
 store.loadTerrainResults.mockResolvedValue([record]);
 const host=document.createElement('div');
 const exportTarget=document.createElement('section');
 host.appendChild(exportTarget);document.body.appendChild(host);
 const props:ComponentProps<typeof TerrainWorkbench>={
  projectId:'project-1',geometry,raster:source,active:true,connected:false,
  viewport:[0,0,.01,.01],localImport:true,refreshToken:0,origin:null,picking:false,
  exportTarget,extentMode:false,onSelectRaster:vi.fn(),onDraw:vi.fn(),onPick:vi.fn(),
  onUseExtent:vi.fn(),onUseSelection:vi.fn(),onHover:vi.fn(),onPreview:vi.fn(),onSaved:vi.fn(),
 };
 const urls=vi.fn(()=> 'blob:scientific-export');
 Object.defineProperty(URL,'createObjectURL',{configurable:true,value:urls});
 Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()});
 const names:string[]=[];
 vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(function(this:HTMLAnchorElement){
  names.push(this.download);
 });
 try{
  const view=render(<div><TerrainWorkbench {...props}/></div>);
  // A single restored run is selected automatically; a selector is unnecessary.
  await within(exportTarget).findByRole('button',{name:'Terrain result JSON'});
  expect(screen.queryByRole('combobox',{name:'Choose terrain result'})).toBeNull();
  // This is the actual App transition: Terrain remains mounted but hidden
  // while its export target belongs to the independently visible Export page.
  view.rerender(<div hidden><TerrainWorkbench {...props} active={false}/></div>);
  const action=within(exportTarget).getByRole('button',{name:'Terrain result JSON'});
  expect(action.closest('[hidden]')).toBeNull();
  fireEvent.click(action);
  expect(urls).toHaveBeenCalledWith(expect.any(Blob));
  expect(names).toEqual(['terrain-elevation.json']);
 }finally{host.remove();}
});
