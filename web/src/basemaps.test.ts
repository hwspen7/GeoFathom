import {it,expect} from 'vitest';import {BASEMAPS,customBasemap} from './basemaps';
it('includes a genuine global satellite tile service',()=>{const s=BASEMAPS.find(b=>b.id==='sentinel');expect(s?.url).toContain('s2cloudless_3857');expect(s?.maxzoom).toBe(14);});
it('validates explicit licensed HTTPS sources',()=>{expect(customBasemap('https://tiles.example.com/{z}/{y}/{x}.png','Provider',19).maxzoom).toBe(19);expect(()=>customBasemap('http://tiles.example.com/{z}/{y}/{x}','Provider',19)).toThrow();expect(()=>customBasemap('https://tiles.example.com/','Provider',19)).toThrow();});
