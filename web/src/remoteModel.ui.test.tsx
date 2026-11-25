// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import RemoteModelPanel from './RemoteModelPanel';
import {getGISJobs,queueRemoteModelJob} from './api';

vi.mock('./api',()=>({getGISJobs:vi.fn(),getGISJob:vi.fn(),queueRemoteModelJob:vi.fn(),queueRemoteEvaluationJob:vi.fn()}));
vi.mock('./ScientificFigureStudio',()=>({default:()=>null}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it('trains with selected label imagery and explicit buffered spatial validation',async()=>{
 vi.mocked(getGISJobs).mockResolvedValue({jobs:[]});vi.mocked(queueRemoteModelJob).mockResolvedValue({id:'trained'} as never);
 const user=userEvent.setup(),onJob=vi.fn();
 render(<RemoteModelPanel projectId="project" features={{red:{image_id:'red-image',band:2,encoding:'raw',scale:1,offset:0,unit:'reflectance'}}} quality={[]} assets={[{id:'labels',name:'Independent samples'}]} job={null} onJob={onJob}/>);
 await user.selectOptions(screen.getByLabelText('Training label raster'),'labels');
 await user.clear(screen.getByLabelText('Validation block width (m)'));await user.type(screen.getByLabelText('Validation block width (m)'),'40');
 await user.click(screen.getByRole('button',{name:'Train and save random forest'}));
 await waitFor(()=>expect(onJob).toHaveBeenCalledWith({id:'trained'}));
 expect(queueRemoteModelJob).toHaveBeenCalledWith('project',expect.objectContaining({labels:{image_id:'labels',band:1},parameters:{block_m:40,folds:5,buffer_blocks:1},features:{red:expect.objectContaining({image_id:'red-image',band:2})}}),true);
});
