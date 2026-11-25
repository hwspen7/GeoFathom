// @vitest-environment jsdom
import {afterEach,describe,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import WorkspaceDockResizer,{readDockWidth} from './WorkspaceDockResizer';
afterEach(()=>{cleanup();localStorage.clear();});
describe('accessible research workspace dock widths',()=>{
 it('accepts only sane stored panel widths',()=>{
  localStorage.setItem('geofathom-dock-width:project','420');
  expect(readDockWidth('project',265)).toBe(420);
  localStorage.setItem('geofathom-dock-width:project','100000');
  expect(readDockWidth('project',265)).toBe(265);
  localStorage.setItem('geofathom-dock-width:project','abc');
  expect(readDockWidth('project',265)).toBe(265);
 });
 it('supports keyboard resizing without requiring pointer devices',()=>{
  const onChange=vi.fn();
  render(<WorkspaceDockResizer side="left" width={265} onChange={onChange}/>);
  const grip=screen.getByRole('separator',{name:'Resize operations'});
  fireEvent.keyDown(grip,{key:'ArrowRight'});
  expect(onChange).toHaveBeenCalledWith(285);
  fireEvent.keyDown(grip,{key:'Home'});
  expect(onChange).toHaveBeenLastCalledWith(200);
  fireEvent.keyDown(grip,{key:'End'});
  expect(onChange).toHaveBeenLastCalledWith(540);
 });
});
