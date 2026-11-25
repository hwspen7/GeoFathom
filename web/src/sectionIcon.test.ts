import {describe,it,expect} from 'vitest';
import {SECTION_ICONS} from './SectionIcon';

describe('workspace section icon vocabulary',()=>{
 it('assigns a different glyph to every distinct section',()=>{
  const icons=Object.values(SECTION_ICONS);
  expect(new Set(icons).size).toBe(icons.length);
  expect(icons.every(Boolean)).toBe(true);
 });
});
