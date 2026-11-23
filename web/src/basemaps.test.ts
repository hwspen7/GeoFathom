import {it,expect} from 'vitest';
import {BASEMAPS,BASEMAP_GROUPS,basemapAvailable,preferredSatellite,customBasemap} from './basemaps';
it('exposes 12 distinct user-selectable map styles organized by physical purpose',()=>{
 expect(BASEMAPS).toHaveLength(12);
 expect(new Set(BASEMAPS.map(b=>b.id)).size).toBe(12);
 expect(BASEMAP_GROUPS.map(g=>g.category)).toEqual(['street','imagery','terrain','other']);
 expect(BASEMAPS.filter(b=>b.category==='imagery').length).toBeGreaterThanOrEqual(4);
 expect(BASEMAPS.filter(b=>b.category==='terrain').length).toBeGreaterThanOrEqual(3);
 for(const b of BASEMAPS){expect(b.note.length).toBeGreaterThan(10);expect(b.coverage).toMatch(/global|usa|configured/);}
});
it('offers higher-native-resolution imagery globally without pretending Sentinel is high definition',()=>{
 const world=BASEMAPS.find(b=>b.id==='imagery')!;
 const sentinel=BASEMAPS.find(b=>b.id==='sentinel')!;
 expect(world.url).toContain('/World_Imagery/MapServer/tile/');
 expect(world.maxzoom).toBeGreaterThanOrEqual(19);
 expect(sentinel.url).toContain('s2cloudless_3857');
 expect(sentinel.maxzoom).toBe(14);
 expect(preferredSatellite([-123,48,-122,50],false)).toBe('imagery');
 expect(preferredSatellite([-83,39,-82,40],false)).toBe('satellite');
});
it('preserves provider attributions, HTTPS URLs and regional coverage disclosures',()=>{
 for(const map of BASEMAPS.filter(x=>x.url)){
  expect(map.url).toMatch(/^https:\/\//);expect(map.attribution?.length).toBeGreaterThan(5);
  expect(map.maxzoom).toBeGreaterThanOrEqual(8);
 }
 expect(BASEMAPS.find(x=>x.id==='satellite')?.coverage).toBe('usa');
 expect(basemapAvailable(BASEMAPS.find(x=>x.id==='custom')!,null)).toBe(false);
 expect(basemapAvailable(BASEMAPS.find(x=>x.id==='custom')!,{url:'https://x',attribution:'x',maxzoom:19})).toBe(true);
});
it('validates explicit licensed HTTPS sources',()=>{
 expect(customBasemap('https://tiles.example.com/{z}/{y}/{x}.png','Provider',19).maxzoom).toBe(19);
 expect(()=>customBasemap('http://tiles.example.com/{z}/{y}/{x}','Provider',19)).toThrow();
 expect(()=>customBasemap('https://tiles.example.com/','Provider',19)).toThrow();
});
