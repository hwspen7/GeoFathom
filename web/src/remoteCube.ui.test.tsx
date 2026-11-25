// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import RemoteCubeBuilder from './RemoteCubeBuilder';
import {queueRemoteCubeJob} from './api';

vi.mock('./api',()=>({queueRemoteCubeJob:vi.fn(),registerRemoteJobImagery:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it('queues the chosen image identities and actual dated acquisitions',async()=>{
 const onJob=vi.fn(),user=userEvent.setup();
 render(<RemoteCubeBuilder projectId="project" bands={{red:{image_id:'image-red',band:2,encoding:'metadata',scale:1,offset:0,unit:'reflectance'}}} quality={[]} job={null} onJob={onJob} onCube={vi.fn()}/>);
 await user.type(screen.getByLabelText('Sensor or harmonized product'),'Sentinel-2 L2A');
 await user.type(screen.getByLabelText('Acquisition datetime'),'2024-01-01T10:00:00Z');
 await user.click(screen.getByRole('button',{name:'Add bound acquisition'}));
 await user.type(screen.getByLabelText('Acquisition datetime'),'2024-01-03T10:00:00Z');
 await user.click(screen.getByRole('button',{name:'Add bound acquisition'}));
 vi.mocked(queueRemoteCubeJob).mockResolvedValue({id:'job'} as never);
 await user.click(screen.getByRole('button',{name:'Build disk time cube'}));
 await waitFor(()=>expect(onJob).toHaveBeenCalledWith({id:'job'}));
 const body=vi.mocked(queueRemoteCubeJob).mock.calls[0][1];
 expect(body.target_image_id).toBe('image-red');
 expect(body.acquisitions).toMatchObject([{datetime:'2024-01-01T10:00:00Z',bands:{red:{image_id:'image-red',band:2}}},{datetime:'2024-01-03T10:00:00Z'}]);
});
it('requires a timezone before adding an acquisition',async()=>{
 const user=userEvent.setup();
 render(<RemoteCubeBuilder bands={{red:{image_id:'image',band:1,encoding:'raw',scale:1,offset:0,unit:''}}} quality={[]} job={null} onJob={vi.fn()} onCube={vi.fn()}/>);
 await user.type(screen.getByLabelText('Sensor or harmonized product'),'Sensor');
 await user.type(screen.getByLabelText('Acquisition datetime'),'2024-01-01T10:00:00');
 await user.click(screen.getByRole('button',{name:'Add bound acquisition'}));
 expect(screen.getByRole('alert').textContent).toContain('timezone');
 expect(screen.queryByRole('listitem')).toBeNull();
});
