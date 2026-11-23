/** Operation-specific, immutable numerical input manifest.
 *
 * A contour experiment must not say that its observer is at (0,0) merely
 * because an unrelated blank form input was coerced with Number('').
 * Only parameters affecting THIS operation are recorded and used to
 * invalidate a live result after an edit.
 */
import type {TerrainRunParameters} from './terrainRunRegistry';

export interface TerrainParameterForm {
 interval:string;reference:string;lon:string;lat:string;
 height:string;target:string;endLon:string;endLat:string;
 maxSlope:string;minElevation:string;maxElevation:string;maxTri:string;
 streamCells:string;azimuth:string;altitude:string;mfdExponent:string;
 sectionSpacing:string;sectionWidth:string;fillSinks:boolean;
 considerCurvature:boolean;refractionCoeff:string;comparisonId:string;
 observerPoints:[string,string][];drape:boolean;textureImageId:string|null;
 gradientMethod:'horn'|'zevenbergen_thorne';slopeClasses:'standard'|'detailed'|'broad';
 neighborhoodRadius:string;viewshedDistance:string;viewshedAzimuth:string;
 viewshedWidth:string;routeModel:'surface'|'distance'|'gentle';meshSamples:string;streamOrderScheme:'strahler'|'shreve';hillshadeMode:'single'|'four_direction';
 flowRoutingMethod?:'d8'|'dinf';depressionMethod?:'fill'|'breach';
 curvatureMethod?:'finite_difference'|'quadratic';curvatureRadius?:string;
 designEastGrade?:string;designNorthGrade?:string;designMaxGrade?:string;elevationSigma?:string;
 optimizeObservers?:string;dsmImageId?:string;meshLod?:boolean;
}

export function terrainParametersForOperation(
 operation:string|null,form:TerrainParameterForm,
):TerrainRunParameters{
 if(!operation)return {};
 const params:TerrainRunParameters={};
 switch(operation){
  case 'profile':
   // The Terrain profile endpoint samples 80 equal-geodesic-distance stations.
   params.profile_samples=80;
   break;
  case 'contours':
   params.contour_interval_m=Number(form.interval);
   break;
  case 'volume':
  case 'cutfill_map':
   params.reference_elevation_m=Number(form.reference);
   break;
  case 'visibility':
   params.observer_longitude=Number(form.lon);
   params.observer_latitude=Number(form.lat);
   params.observer_height_m=Number(form.height);
   params.target_height_m=Number(form.target);
   params.consider_curvature=form.considerCurvature;
   params.maximum_distance_m=Number(form.viewshedDistance);
   params.view_azimuth_deg=Number(form.viewshedAzimuth);
   params.view_width_deg=Number(form.viewshedWidth);
   if(form.considerCurvature)
    params.refraction_coefficient=Number(form.refractionCoeff);
   break;
  case 'viewshed_multi':
   params.observer_points=form.observerPoints.map(([lon,lat])=>
    [Number(lon),Number(lat)]);
   params.observer_height_m=Number(form.height);
   params.target_height_m=Number(form.target);
   params.consider_curvature=form.considerCurvature;
   params.maximum_distance_m=Number(form.viewshedDistance);
   params.view_azimuth_deg=Number(form.viewshedAzimuth);
   params.view_width_deg=Number(form.viewshedWidth);
   if(form.considerCurvature)
    params.refraction_coefficient=Number(form.refractionCoeff);
   break;
  case 'least_cost':
   params.observer_longitude=Number(form.lon);
   params.observer_latitude=Number(form.lat);
   params.end_longitude=Number(form.endLon);
   params.end_latitude=Number(form.endLat);
   params.max_slope_deg=Number(form.maxSlope);
   params.route_model=form.routeModel;
   break;
  case 'watershed':
   params.observer_longitude=Number(form.lon);
   params.observer_latitude=Number(form.lat);
   params.fill_sinks=form.fillSinks;
   break;
  case 'flow_direction':
  case 'flow_accumulation':
   params.fill_sinks=form.fillSinks;
   break;
  case 'flow_accumulation_mfd':
   params.fill_sinks=form.fillSinks;
   params.mfd_exponent=Number(form.mfdExponent);
   break;
  case 'streams':
  case 'stream_order':
   if(operation==='stream_order')params.stream_order_scheme=form.streamOrderScheme;
   params.fill_sinks=form.fillSinks;
   params.min_stream_cells=Number(form.streamCells);
   break;
  case 'suitability':
   params.max_slope_deg=Number(form.maxSlope);
   params.min_elevation_m=Number(form.minElevation);
   params.max_elevation_m=Number(form.maxElevation);
   params.max_tri_m=Number(form.maxTri);
   break;
  case 'hillshade':
   params.hillshade_mode=form.hillshadeMode;
   params.azimuth_deg=Number(form.azimuth);
   params.altitude_deg=Number(form.altitude);
   break;
  case 'cross_sections':
   params.section_spacing_m=Number(form.sectionSpacing);
   params.section_half_width_m=Number(form.sectionWidth);
   break;
  case 'dem_difference':
   params.comparison_image_id=form.comparisonId||null;
   break;
  case 'mesh':
   params.mesh_samples=Number(form.meshSamples);
   params.drape=form.drape;
   if(form.drape&&form.textureImageId)
    params.texture_image_id=form.textureImageId;
   break;
  default:
   // Defaults / source geometry fully determine these products:
   // slope, elevation, aspect, derivatives, distribution and so forth.
   break;
 }
 if(operation==='tri'||operation==='tpi')
  params.neighborhood_radius_cells=Number(form.neighborhoodRadius);
 // Method selections are scientific inputs, not display-only settings.
 if(['slope','slope_map','aspect_map','hillshade','suitability',
     'plan_curvature','profile_curvature'].includes(operation))
  params.gradient_method=form.gradientMethod;
 if(operation==='slope_map')params.slope_classes=form.slopeClasses;
 // P1 method controls are attached only to the analyses they actually change.
 if(operation==='flow_accumulation'&&form.flowRoutingMethod==='dinf')params.flow_routing_method='dinf';
 if(['flow_direction','flow_accumulation','flow_accumulation_mfd','streams','stream_order','watershed'].includes(operation)
    &&form.fillSinks&&form.depressionMethod==='breach')params.depression_method='breach';
 if(['curvature','plan_curvature','profile_curvature'].includes(operation)&&form.curvatureMethod==='quadratic'){
  params.curvature_method='quadratic';
  params.curvature_radius_cells=Number(form.curvatureRadius??'2');
 }
 if(['volume','cutfill_map'].includes(operation)){
  if(form.designEastGrade&&Number(form.designEastGrade)!==0)params.design_east_grade=Number(form.designEastGrade);
  if(form.designNorthGrade&&Number(form.designNorthGrade)!==0)params.design_north_grade=Number(form.designNorthGrade);
  if(form.designMaxGrade&&Number(form.designMaxGrade)!==.3)params.design_max_grade=Number(form.designMaxGrade);
  if(form.elevationSigma&&Number(form.elevationSigma)!==0)params.elevation_sigma_m=Number(form.elevationSigma);
 }
 if(['visibility','viewshed_multi'].includes(operation)&&form.dsmImageId)
  params.dsm_image_id=form.dsmImageId;
 if(operation==='viewshed_multi'&&form.optimizeObservers&&Number(form.optimizeObservers)>0)
  params.optimize_observers=Number(form.optimizeObservers);
 if(operation==='mesh'&&form.meshLod)params.mesh_lod=true;
 return params;
}
