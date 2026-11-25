// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import RemoteSampleManager from './RemoteSampleManager';
import {remoteSampleRequest} from './api';
vi.mock('./api',()=>({remoteSampleRequest:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it('edits annotation review into a new immutable sample revision',async()=>{
 const body={name:'Samples',target_image_id:'target',classes:[{id:1,name:'Water',description:''},{id:2,name:'Forest',description:''}],annotations:[{id:'point',geometry:{type:'Point',coordinates:[-83,40]},class_id:1,split:'train',review:'pending',reviewer:'',source:'Published reference annotation'}],training_reference_buffer_m:100};
 vi.mocked(remoteSampleRequest).mockImplementation(async(_project,path='',payload)=>path==='/revision'?{id:'revision',sha256:'original',body}:payload?{id:'new',sha256:'new-checksum',body:payload}:{revisions:[{id:'revision',name:'Samples'}]} as never);
 const user=userEvent.setup();render(<RemoteSampleManager projectId="project" assets={[{id:'target',name:'Grid'}]} features={null} quality={[]} parameters={{}} onLabels={vi.fn()}/>);
 await waitFor(()=>expect(screen.getByRole('option',{name:'Samples · revision'})).toBeTruthy());
 await user.selectOptions(screen.getByLabelText('Saved sample revision'),'revision');await user.click(screen.getByRole('button',{name:'Load sample revision'}));
 await waitFor(()=>expect(screen.getByLabelText('Sample point review')).toBeTruthy());
 await user.selectOptions(screen.getByLabelText('Sample point review'),'accepted');await user.type(screen.getByLabelText('Sample point reviewer'),'Reviewer');
 await user.click(screen.getByRole('button',{name:'Save immutable sample revision'}));
 expect(remoteSampleRequest).toHaveBeenCalledWith('project','',expect.objectContaining({annotations:[expect.objectContaining({review:'accepted',reviewer:'Reviewer',geometry:body.annotations[0].geometry})]}));
});
