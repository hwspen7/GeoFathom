// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import type {ComponentProps} from 'react';
import TerrainWorkbench,{TerrainResultPicker} from './TerrainWorkbench';
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
  expect(screen.queryByRole('button',{name:'Choose terrain result'})).toBeNull();
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


it('pages terrain history eight at a time and selects older results',()=>{
 const records=Array.from({length:19},(_,i)=>({id:'run-'+i,title:'Result '+i,createdAt:i*1000})) as PersistedTerrainResult[];
 const select=vi.fn();
 render(<TerrainResultPicker records={records} selectedId="run-18" onSelect={select}/>);
 fireEvent.click(screen.getByRole('button',{name:'Choose terrain result'}));
 const menu=within(screen.getByRole('group',{name:'Terrain result history'}));
 expect(menu.getAllByRole('button',{name:/^Result /})).toHaveLength(8);
 fireEvent.click(menu.getByRole('button',{name:'Next result page'}));
 expect(menu.getAllByRole('button',{name:/^Result /})).toHaveLength(8);
 fireEvent.click(menu.getByRole('button',{name:'Next result page'}));
 expect(menu.getAllByRole('button',{name:/^Result /})).toHaveLength(3);
 fireEvent.click(menu.getByRole('button',{name:/^Result 0 ·/}));
 expect(select).toHaveBeenCalledWith('run-0');
 expect(screen.queryByRole('group',{name:'Terrain result history'})).toBeNull();
});

it('keeps pagination open when the focused control becomes disabled at either boundary',()=>{
 const records=Array.from({length:9},(_,i)=>({id:'run-'+i,title:'Result '+i,createdAt:i*1000})) as PersistedTerrainResult[];
 const select=vi.fn();
 render(<TerrainResultPicker records={[...records].reverse()} selectedId="run-8" onSelect={select}/>);
 const trigger=screen.getByRole('button',{name:'Choose terrain result'});
 fireEvent.click(trigger);
 const menu=within(screen.getByRole('group',{name:'Terrain result history'}));
 expect(menu.getAllByRole('button',{name:/^Result /})[0].textContent).toMatch(/^Result 8 ·/);
 const next=menu.getByRole('button',{name:'Next result page'});
 next.focus();fireEvent.click(next);
 expect(document.activeElement).toBe(trigger);
 expect((next as HTMLButtonElement).disabled).toBe(true);
 expect(menu.getAllByRole('button',{name:/^Result /})).toHaveLength(1);
 const previous=menu.getByRole('button',{name:'Previous result page'});
 previous.focus();fireEvent.click(previous);
 expect(document.activeElement).toBe(trigger);
 expect((previous as HTMLButtonElement).disabled).toBe(true);
 expect(menu.getAllByRole('button',{name:/^Result /})).toHaveLength(8);
 fireEvent.keyDown(trigger,{key:'Escape'});
 expect(screen.queryByRole('group',{name:'Terrain result history'})).toBeNull();
 expect(select).not.toHaveBeenCalled();
});
