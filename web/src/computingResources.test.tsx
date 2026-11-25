// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import ComputingResources from './ComputingResources';
import type {TerrainComputeStatus,TerrainComputePolicy} from './api';
const api=vi.hoisted(()=>({getTerrainComputeResources:vi.fn(),setTerrainComputeResources:vi.fn()}));
vi.mock('./api',()=>api);
const policy:TerrainComputePolicy={mode:'automatic',memory_percent:65,concurrent_tasks:1,tile_size:512,
 slope_cells:256000000,surface_cells:32000000,global_cells:8000000,visibility_cells:1048576,
 least_cost_cells:2097152,viewshed_distance_m:10000,ray_samples:100000000};
const snapshot:TerrainComputeStatus={policy,hardware:{total_bytes:32*1024**3,available_bytes:20*1024**3,logical_cpus:8,scratch_free_bytes:100*1024**3},
 effective:{memory_bytes:8*1024**3,concurrent_tasks:2,tile_size:1024,slope_cells:256000000,surface_cells:16000000,global_cells:8000000,visibility_cells:1048576,least_cost_cells:2097152,viewshed_distance_m:30000,ray_samples:200000000,native_slope_cells:8000000},
 active_tasks:0,queued_tasks:0,scope:'local_backend_process',terrain_gpu:'not_available',memory_protection:'estimated_admission_not_os_enforcement'};
beforeEach(()=>{vi.resetAllMocks();api.getTerrainComputeResources.mockResolvedValue(snapshot);});
afterEach(cleanup);
async function open(){
 const {container}=render(<ComputingResources/>);
 const details=container.querySelector('details')!;
 details.open=true;
 await waitFor(()=>expect(api.getTerrainComputeResources).toHaveBeenCalled());
 await screen.findByLabelText('Compute resource mode');
}
it('loads actual backend hardware and exposes manual ceilings only when selected',async()=>{
 await open();
 expect(screen.getByText(/8 logical cores/)).toBeTruthy();
 expect(screen.queryByLabelText('Compute memory percent')).toBeNull();
 expect(screen.getByRole('table',{name:'Effective terrain cell limits'}).textContent).toContain('16,000,000');
 fireEvent.change(screen.getByLabelText('Compute resource mode'),{target:{value:'manual'}});
 fireEvent.change(screen.getByLabelText('Compute memory percent'),{target:{value:'40'}});
 fireEvent.change(screen.getByLabelText('Compute tile size'),{target:{value:'128'}});
 fireEvent.change(screen.getByLabelText('Local surfaces cell ceiling'),{target:{value:'50000'}});
 const manual={...policy,mode:'manual' as const,memory_percent:40,tile_size:128 as const,surface_cells:50000};
 api.setTerrainComputeResources.mockResolvedValue({...snapshot,policy:manual,effective:{...snapshot.effective,surface_cells:50000,tile_size:128}});
 fireEvent.click(screen.getByRole('button',{name:'Apply resources'}));
 await waitFor(()=>expect(api.setTerrainComputeResources).toHaveBeenCalledWith(manual));
 expect((await screen.findByRole('status')).textContent).toContain('Resource settings saved.');
 expect(screen.getByRole('table',{name:'Effective terrain cell limits'}).textContent).toContain('50,000');
});
it('does not claim settings were saved when backend rejects an active-task change',async()=>{
 await open();
 fireEvent.change(screen.getByLabelText('Compute resource mode'),{target:{value:'manual'}});
 api.setTerrainComputeResources.mockRejectedValue(Error('Finish active tasks first.'));
 fireEvent.click(screen.getByRole('button',{name:'Apply resources'}));
 expect((await screen.findByRole('alert')).textContent).toContain('Finish active tasks first.');
 expect(screen.queryByRole('status')).toBeNull();
});
