import {afterEach,describe,expect,it,vi} from 'vitest';
import {rememberProject,restoreProject,storedProject} from './projectSelection';

afterEach(()=>vi.unstubAllGlobals());

describe('tab-scoped project identity',()=>{
  it('keeps the selected project despite a newer project at the head of the list',()=>{
    expect(restoreProject([{id:'new'},{id:'old'}],'old')).toBe('old');
  });
  it('falls back only when the remembered project is no longer available',()=>{
    expect(restoreProject([{id:'new'}],'removed')).toBe('new');
    expect(restoreProject([],'removed')).toBe('');
  });
  it('stores and clears a project for the current tab',()=>{
    const data=new Map<string,string>();
    vi.stubGlobal('window',{sessionStorage:{
      getItem:(key:string)=>data.get(key)??null,
      setItem:(key:string,value:string)=>data.set(key,value),
      removeItem:(key:string)=>data.delete(key),
    }});
    rememberProject('project-a');
    expect(storedProject()).toBe('project-a');
    rememberProject('');
    expect(storedProject()).toBe('');
  });
  it('works when storage access is blocked',()=>{
    vi.stubGlobal('window',{get sessionStorage(){throw new Error('blocked');}});
    expect(()=>rememberProject('project-a')).not.toThrow();
    expect(storedProject()).toBe('');
  });
});
