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
 viewshedWidth:string;routeModel:'surface'|'distance'|'gentle';meshSamples:string;
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
 return params;
}
