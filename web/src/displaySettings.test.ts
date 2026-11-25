import {it,expect} from 'vitest';import {areaText,distanceText,mapPalette} from './displaySettings';import {preferredSatellite} from './basemaps';
it('formats large areas and distances in usable units',()=>{expect(areaText(29852126.55)).toBe('29.8521 km²');expect(distanceText(26232.5)).toBe('26.233 km');expect(areaText(10000,'m2')).toBe('10,000 m²');});
it('chooses different contrasts and actual American high resolution imagery',()=>{
 expect(mapPalette('street','auto').selected).not.toBe(mapPalette('satellite','auto').selected);
 expect(preferredSatellite([-83,39,-82,40],false)).toBe('satellite');
 expect(preferredSatellite([121,31,122,32],false)).toBe('imagery');
 expect(preferredSatellite([121,31,122,32],true)).toBe('custom');
});
