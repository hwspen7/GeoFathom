// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import RemoteExperimentControls from './RemoteExperimentControls';
import {repeatScientificJob,type GISJob} from './api';

vi.mock('./api',()=>({repeatScientificJob:vi.fn(),getScientificJobRecipe:vi.fn()}));
vi.mock('./figureExport',()=>({saveFigureBlob:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it('keeps software changes opt-in when repeating a verified experiment',async()=>{
 const user=userEvent.setup(),onJob=vi.fn();vi.mocked(repeatScientificJob).mockResolvedValue({id:'repeat'} as GISJob);
 render(<RemoteExperimentControls projectId="project" job={{id:'original',status:'completed',result:{reproducibility:{}}} as GISJob} onJob={onJob}/>);
 await user.click(screen.getByRole('button',{name:'Repeat with verified inputs'}));
 await waitFor(()=>expect(onJob).toHaveBeenCalled());
 expect(repeatScientificJob).toHaveBeenLastCalledWith('project','original',false);
 await user.click(screen.getByLabelText('Allow changes in algorithm software'));
 await user.click(screen.getByRole('button',{name:'Repeat with verified inputs'}));
 await waitFor(()=>expect(repeatScientificJob).toHaveBeenLastCalledWith('project','original',true));
});
