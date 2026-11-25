import {describe,it,expect} from 'vitest';
import {terrainParametersForOperation,type TerrainParameterForm} from './terrainRunParameters';

const defaultForm:TerrainParameterForm={
 interval:'10',reference:'0',lon:'-83',lat:'40',height:'1.7',target:'0',
 endLon:'-83.1',endLat:'40.1',maxSlope:'30',minElevation:'100',maxElevation:'140',
 maxTri:'10',streamCells:'5',mfdExponent:'1.1',azimuth:'315',altitude:'45',
 sectionSpacing:'50',sectionWidth:'20',fillSinks:true,considerCurvature:true,
 refractionCoeff:'0.13',comparisonId:'',observerPoints:[['-83','40'],['-83.01','40.01']],
 drape:false,textureImageId:null,gradientMethod:'horn',slopeClasses:'standard',
 neighborhoodRadius:'1',viewshedDistance:'0',viewshedAzimuth:'0',viewshedWidth:'360',
 routeModel:'surface',meshSamples:'256',streamOrderScheme:'strahler',hillshadeMode:'single',
 flowRoutingMethod:'d8',depressionMethod:'fill',curvatureMethod:'finite_difference',
 curvatureRadius:'2',designEastGrade:'0',designNorthGrade:'0',designMaxGrade:'0.3',
 elevationSigma:'0',optimizeObservers:'0',dsmImageId:'',meshLod:false,
 suitabilityModel:'binary',suitabilitySlopeWeight:'0.5',suitabilityTriWeight:'0.25',
 suitabilityElevationWeight:'0.25'
};
describe('P1 method-specific scientific manifests',()=>{
 it('distinguishes D-infinity and breach, retaining unrelated operation identity',()=>{
  const changed={...defaultForm,flowRoutingMethod:'dinf' as const,depressionMethod:'breach' as const};
  expect(terrainParametersForOperation('flow_accumulation',changed)).toMatchObject({
   fill_sinks:true,flow_routing_method:'dinf',depression_method:'breach'
  });
  expect(terrainParametersForOperation('contours',changed))
   .toEqual(terrainParametersForOperation('contours',defaultForm));
  const noCondition={...changed,fillSinks:false};
  expect(terrainParametersForOperation('flow_accumulation',noCondition)).not.toHaveProperty('depression_method');
 });
 it('records quadratic polynomial window and never changes slope map run identity',()=>{
  const changed={...defaultForm,curvatureMethod:'quadratic' as const,curvatureRadius:'4'};
  expect(terrainParametersForOperation('curvature',changed)).toEqual({
   curvature_method:'quadratic',curvature_radius_cells:4
  });
  expect(terrainParametersForOperation('slope_map',changed))
   .toEqual(terrainParametersForOperation('slope_map',defaultForm));
 });
 it('records DSM & site optimization without introducing foreign visibility inputs',()=>{
  const changed={...defaultForm,dsmImageId:'dsm-1',optimizeObservers:'2'};
  expect(terrainParametersForOperation('visibility',changed)).toMatchObject({
   dsm_image_id:'dsm-1'
  });
  expect(terrainParametersForOperation('visibility',changed)).not.toHaveProperty('optimize_observers');
  expect(terrainParametersForOperation('viewshed_multi',changed)).toMatchObject({
   dsm_image_id:'dsm-1',optimize_observers:2
  });
 });
 it('records explicit design assumptions and mesh LOD separately',()=>{
  const changed={...defaultForm,reference:'110',designEastGrade:'0.01',
   designNorthGrade:'-0.02',designMaxGrade:'0.15',elevationSigma:'0.5',meshLod:true};
  expect(terrainParametersForOperation('volume',changed)).toEqual({
   reference_elevation_m:110,design_east_grade:.01,design_north_grade:-.02,
   design_max_grade:.15,elevation_sigma_m:.5
  });
  expect(terrainParametersForOperation('mesh',changed)).toMatchObject({
   mesh_lod:true
  });
  expect(terrainParametersForOperation('volume',defaultForm))
   .toEqual({reference_elevation_m:0});
 });
 it('weighted suitability records scoring criteria and binary legacy stays unchanged',()=>{
  const changed={...defaultForm,suitabilityModel:'weighted' as const,
   suitabilitySlopeWeight:'3',suitabilityTriWeight:'2',suitabilityElevationWeight:'1'};
  expect(terrainParametersForOperation('suitability',changed)).toMatchObject({
   suitability_model:'weighted',suitability_weights:[3,2,1]
  });
  expect(terrainParametersForOperation('suitability',defaultForm)).not.toHaveProperty('suitability_model');
 });
});
