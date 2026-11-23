import {describe,it,expect} from 'vitest';
import {WORKSPACE_MODULES,searchWorkspaceCommands,type WorkspaceCommand} from './WorkspaceChrome';
const go=()=>{};
const commands:WorkspaceCommand[]=[
 {id:'terrain',group:'Modules',label:'Terrain',description:'Elevation and hydrology',shortcut:'T',run:go},
 {id:'slope',group:'Terrain',label:'Slope map',description:'Degrees',run:go},
 {id:'save',group:'File',label:'Save feature',shortcut:'Ctrl S',run:go,disabled:true},
];
describe('shared Onshape-style workspace command registry',()=>{
 it('has unique stable module IDs, with Terrain and all current modules represented',()=>{
  expect(WORKSPACE_MODULES).toHaveLength(8);
  expect(new Set(WORKSPACE_MODULES.map(m=>m.id)).size).toBe(8);
  expect(WORKSPACE_MODULES.some(m=>m.id==='tools-terrain')).toBe(true);
 });
 it('filters command titles, groups, keywords and shortcuts without removing disabled actions',()=>{
  expect(searchWorkspaceCommands(commands,'terrain').map(c=>c.id)).toEqual(['terrain','slope']);
  expect(searchWorkspaceCommands(commands,'slope degrees').map(c=>c.id)).toEqual(['slope']);
  expect(searchWorkspaceCommands(commands,'ctrl s')[0].id).toBe('save');
  expect(searchWorkspaceCommands(commands,'unknown')).toHaveLength(0);
  expect(searchWorkspaceCommands(commands,'')).toHaveLength(3);
 });
});
