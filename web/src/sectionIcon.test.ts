import {describe,it,expect} from 'vitest';
import {SECTION_ICONS} from './SectionIcon';

describe('workspace section icon vocabulary',()=>{
 it('assigns a different glyph to every distinct section',()=>{
  const icons=Object.values(SECTION_ICONS);
  const entries=Object.entries(SECTION_ICONS);
  const duplicates=entries.flatMap(([key,icon],i)=>entries.slice(i+1).filter(([,other])=>icon===other).map(([other])=>key+' / '+other));
  expect(duplicates).toEqual([]);
  expect(icons.every(Boolean)).toBe(true);
 });
});
