import {expect,it} from 'vitest';
import {parseSweep,parseParameter,researchBase} from './terrainResearch';
import type {PersistedTerrainResult} from './terrainResultStore';
it('rejects blank, repeated, infinite and oversized parameter sweeps',()=>{
 for(const raw of ['',',1','1,','1,1','1,Infinity','1,2,3,4,5,6,7,8,9'])expect(()=>parseSweep(raw)).toThrow();
 expect(parseSweep('-1,0,2.5')).toEqual([-1,0,2.5]);
});
it('preserves typed scenario controls',()=>{
 expect(parseParameter('true')).toBe(true);expect(parseParameter('false')).toBe(false);
 expect(parseParameter('1, 2, 3')).toEqual([1,2,3]);expect(parseParameter('zevenbergen_thorne')).toBe('zevenbergen_thorne');
 expect(()=>parseParameter('1,,3')).toThrow();expect(()=>parseParameter('')).toThrow();
});
it('maps historical receipts and preserves complete request snapshots',()=>{
 const geometry={type:'Polygon',coordinates:[]} as GeoJSON.Polygon;
 const record={operation:'cutfill_map',source:{id:'dem'},geometry,parameters:{reference_elevation_m:123,design_east_grade:.1}} as unknown as PersistedTerrainResult;
 expect(researchBase(record)).toMatchObject({image_id:'dem',operation:'cutfill_map',reference:123,design_east_grade:.1});
 record.researchInput={image_id:'original',geometry,operation:'hillshade',azimuth:42};
 const copy=researchBase(record);copy.azimuth=99;
 expect(record.researchInput.azimuth).toBe(42);
});
