import {describe,it,expect} from 'vitest';
import {terrainParametersForOperation,type TerrainParameterForm} from './terrainRunParameters';
const base:TerrainParameterForm={
 interval:'10',reference:'0',lon:'',lat:'',height:'1.7',target:'0',
 endLon:'',endLat:'',maxSlope:'30',minElevation:'-12000',
 maxElevation:'12000',maxTri:'100',streamCells:'100',
 azimuth:'315',altitude:'45',sectionSpacing:'50',sectionWidth:'20',
 fillSinks:true,considerCurvature:true,refractionCoeff:'0.13',
 comparisonId:'',observerPoints:[['',''],['','']],drape:false,
 textureImageId:null,gradientMethod:'horn',slopeClasses:'standard',
};
describe('scientific operation-specific input manifests',()=>{
 it('does not invent a zero-degree observer for a contour experiment',()=>{
  expect(terrainParametersForOperation('contours',base))
   .toEqual({contour_interval_m:10});
  expect(terrainParametersForOperation('profile',base))
   .toEqual({profile_samples:80});
  expect(terrainParametersForOperation('elevation',base)).toEqual({});
 });
 it('unrelated form fields never alter the result identity of a slope map',()=>{
  const updated={...base,lon:'20',lat:'50',azimuth:'99',reference:'1000'};
  expect(terrainParametersForOperation('slope_map',updated))
   .toEqual(terrainParametersForOperation('slope_map',base));
 });
 it('records real route, hydrology and visibility parameters without unrelated inputs',()=>{
  const filled={...base,lon:'-83.001',lat:'40.01',endLon:'-83.02',
   endLat:'40.015',streamCells:'25',observerPoints:[
    ['-83.001','40.01'],['-83.02','40.015']] as [string,string][]};
  const route=terrainParametersForOperation('least_cost',filled);
  expect(route).toEqual({observer_longitude:-83.001,observer_latitude:40.01,
   end_longitude:-83.02,end_latitude:40.015,max_slope_deg:30});
  expect(terrainParametersForOperation('stream_order',filled))
   .toEqual({fill_sinks:true,min_stream_cells:25});
  const viewshed=terrainParametersForOperation('viewshed_multi',filled);
  expect(viewshed.observer_points).toEqual([
   [-83.001,40.01],[-83.02,40.015]]);
  expect(viewshed).not.toHaveProperty('reference_elevation_m');
  filled.observerPoints[0][0]='-83.1';
  expect(viewshed.observer_points).toEqual([
   [-83.001,40.01],[-83.02,40.015]]);
 });
 it('model and classification choices affect only relevant scientific run IDs',()=>{
  const standard=terrainParametersForOperation('slope_map',base);
  expect(standard).toEqual({gradient_method:'horn',slope_classes:'standard'});
  const changed={...base,gradientMethod:'zevenbergen_thorne' as const,
   slopeClasses:'detailed' as const};
  expect(terrainParametersForOperation('slope_map',changed)).toEqual({
   gradient_method:'zevenbergen_thorne',slope_classes:'detailed'});
  expect(terrainParametersForOperation('aspect_map',changed)).toEqual({
   gradient_method:'zevenbergen_thorne'});
  expect(terrainParametersForOperation('contours',changed))
   .toEqual(terrainParametersForOperation('contours',base));
 });
 it('records curvature refraction only when curvature is enabled',()=>{
  expect(terrainParametersForOperation('visibility',{
   ...base,lon:'-83',lat:'40',considerCurvature:false
  })).not.toHaveProperty('refraction_coefficient');
 });
});
