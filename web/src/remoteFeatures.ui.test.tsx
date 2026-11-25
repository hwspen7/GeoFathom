// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import RemoteFeatureBuilder from './RemoteFeatureBuilder';

afterEach(cleanup);
it('builds a typed terrain feature independently of the selected optical method',async()=>{
 const user=userEvent.setup(),change=vi.fn();
 render(<RemoteFeatureBuilder assets={[{id:'terrain',name:'Slope map'}]} bound={null} onChange={change}/>);
 await user.click(screen.getByText('Multi-source model features'));
 await user.click(screen.getByLabelText('Build a custom feature set'));
 await user.click(screen.getByRole('button',{name:'Add model feature'}));
 await user.clear(screen.getByLabelText('Feature 1 name'));await user.type(screen.getByLabelText('Feature 1 name'),'slope');
 await user.selectOptions(screen.getByLabelText('Feature 1 imagery'),'terrain');
 await user.selectOptions(screen.getByLabelText('Feature 1 quantity'),'slope');
 await waitFor(()=>expect(change).toHaveBeenLastCalledWith({slope:expect.objectContaining({image_id:'terrain',quantity:'slope',band:1})}));
});
