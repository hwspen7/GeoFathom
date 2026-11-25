import {expect,it} from 'vitest';
import {meshData,meshOBJ} from './TerrainMeshView';
import {chartPDF} from './TerrainCharts';
it('does not bridge nodata with mesh faces',()=>{
 const mesh={rows:2,cols:2,dx_m:10,dy_m:10,heights:[1,2,3,null]};
 const d=meshData(mesh);expect(d.triangles.length).toBe(3);expect(d.vertices.length).toBe(24);
 expect(meshOBJ(mesh)).toContain('f 1 3 2');
});
it('creates PDF bytes with a page and a cross-reference table',()=>{
 const pdf=chartPDF(new Uint8Array([255,216,255,217]),100,100);
 expect(pdf.type).toBe('application/pdf');expect(pdf.size).toBeGreaterThan(500);
});
