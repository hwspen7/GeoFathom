// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import RemoteModelExperiments from './RemoteModelExperiments';
import {queueRemoteExperiment} from './api';
vi.mock('./api',()=>({queueRemoteExperiment:vi.fn(),downloadRemoteDiskJob:vi.fn()}));
vi.mock('./ScientificFigureStudio',()=>({default:()=>null}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it('queues a named feature ablation with shared validation parameters',async()=>{
 vi.mocked(queueRemoteExperiment).mockResolvedValue({id:'batch'} as never);
 const f={image_id:'image',band:1,encoding:'metadata',scale:1,offset:0,unit:'reflectance'},user=userEvent.setup(),onJob=vi.fn();
 render(<RemoteModelExperiments projectId="project" features={{red:f,nir:f}} quality={[]} labels="labels" parameters={{block_m:100,folds:3}} job={null} onJob={onJob}/>);
 await user.click(screen.getByRole('button',{name:'Add experiment variant'}));await user.click(screen.getByRole('checkbox',{name:'All-feature RF baseline: nir'}));
 await user.click(screen.getByRole('button',{name:'Run controlled experiments'}));await waitFor(()=>expect(onJob).toHaveBeenCalledWith({id:'batch'}));
 expect(queueRemoteExperiment).toHaveBeenCalledWith('project',expect.objectContaining({parameters:{block_m:100,folds:3},labels:{image_id:'labels',band:1},variants:[expect.objectContaining({roles:['red'],trees:64})]}));
});
