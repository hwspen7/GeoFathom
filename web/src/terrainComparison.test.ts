import {describe,it,expect} from 'vitest';
import {terrainMetricDifferences,sameGeometryFootprint} from './terrainComparison';
describe('analysis source/version comparability',()=>{
 it('compares physical statistics, not pixel counts from different grids',()=>{
  const diff=terrainMetricDifferences({product_mean:5.17,product_valid_cells:701250}, {product_mean:4.93,product_valid_cells:40000});
  expect(diff).toHaveLength(1);
  expect(diff[0].key).toBe('product_mean');
  expect(diff[0].delta).toBeCloseTo(.24);
 });
 it('flags geometry changes even when comparing the same named campus',()=>{
  const first:GeoJSON.LineString={type:'LineString',coordinates:[[0,0],[1,1]]};
  expect(sameGeometryFootprint(first,structuredClone(first))).toBe(true);
  expect(sameGeometryFootprint(first,{...first,coordinates:[[0,0],[2,2]]})).toBe(false);
 });
});
