/** Scientific metadata comparison. Pixel counts are intentionally excluded:
 * two DEMs with different grids cannot compare cell counts directly. */
export function terrainMetricDifferences(
 current:Record<string,number>,reference:Record<string,number>
):Array<{key:string;current:number;reference:number;delta:number}>{
 const ignore=/(_cells$|^product_valid_cells$|^valid_|^covered_grid_area_|^cell_area_)/;
 return Object.entries(current).filter(([key,value])=>
   !ignore.test(key)&&Number.isFinite(value)&&Number.isFinite(reference[key])
 ).slice(0,12).map(([key,value])=>({
   key,current:value,reference:reference[key],delta:value-reference[key],
 }));
}
export function sameGeometryFootprint(a:GeoJSON.Geometry,b:GeoJSON.Geometry):boolean{
 // Exact vertex identity is intentionally strict; reprojected or edited inputs
 // must be flagged as nonidentical, not silently treated as a matched survey.
 return JSON.stringify(a)===JSON.stringify(b);
}
