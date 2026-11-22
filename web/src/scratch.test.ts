import {it,expect} from 'vitest';
import {localMeasurement,localShape,OFFLINE_METHOD} from './scratch';
it('finishes an independent local rectangle and labels it as estimated',()=>{
 const result=localShape('rectangle',[[0,0],[.001,.001]])!;
 expect(result.geometry.type).toBe('Polygon');expect(result.measurement.area_m2).toBeGreaterThan(12000);
 expect(result.measurement.method).toBe(OFFLINE_METHOD);
});
it('rejects a crossing local polygon rather than pretending it is validated',()=>{
 expect(()=>localMeasurement({type:'Polygon',coordinates:[[[0,0],[1,1],[0,1],[1,0],[0,0]]]})).toThrow(/intersect/);
});
it('does not invent offline support for network tracing',()=>expect(localShape('trace-along',[[0,0],[1,1]])).toBeNull());
it('rejects an invalid zero-width rectangle',()=>expect(()=>localShape('rectangle',[[0,0],[0,1]])).toThrow());
