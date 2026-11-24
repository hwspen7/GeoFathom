"""Bind actual results to the shared scientific figure catalog."""
import csv,io
import numpy as np

def csv_text(headers,rows):
    out=io.StringIO();writer=csv.writer(out);writer.writerow(headers);writer.writerows(rows);return out.getvalue()

def figure_sources(result,grids):
    kind=result['operation'];cols=set(result['columns']);data=result['csv'];metrics=result['receipt']['metrics'];figures=[]
    def add(name,recipe,bindings=None,table=None,raster=False):
        figures.append({'title':name,'recipe':recipe,'bindings':bindings or {},'csv':None if raster else (data if table is None else table),'raster':raster})
    def table(name,recipe,bindings):
        if set(bindings.values())<=cols and result['rows']:add(name,recipe,bindings)
    product=result['raster']
    if product:
        add('Scientific result map','raster_classes' if product['unit']=='class' else 'raster_continuous',raster=True)
        summary=product['summary']
        if product['unit']=='class':
            if summary.get('class_counts'):
                add('Class frequency (full valid grid)','basic_column',{'x':'class','y':'cell_count'},csv_text(['class','cell_count'],summary['class_counts']))
        else:
            add('Raster quantile profile (full valid grid)','basic_scatter',{'x':'quantile','y':'value'},csv_text(['quantile','value'],summary['quantiles']))
    if kind in {'global_moran','global_geary','join_count','bivariate_moran'}:
        table('Random-label permutation distribution','spatial_null_distribution',{'x':'null_statistic','y':'observed_statistic'})
    if kind=='directional_lag_scan':
        for field in ['semivariance','covariance','correlation']:
            if any(r[result['columns'].index(field)] is not None for r in result['rows']):
                table(field.capitalize()+' by direction','spatial_directional_lag',{'x':'distance_m','y':field,'group':'direction'})
    if kind.startswith('sample_'):
        if grids and grids[0].is_meter:
            table('Spatial sample distribution and weights','spatial_sample_design',{'x':'x','y':'y','z':'design_weight'})
        table('Sample-value distribution','basic_rank',{'y':'value'})
        table('Design weight distribution','basic_rank',{'y':'design_weight'})
    if kind=='sample_polygon' and result['features']:
        from pyproj import Transformer
        tx=Transformer.from_crs(4326,result['receipt']['crs'],always_xy=True)
        rows=[[*tx.transform(*f['geometry']['coordinates']),f['properties']['area_weight_m2']] for f in result['features']['features']]
        add('Polygon sample distribution','spatial_sample_design',{'x':'easting','y':'northing','z':'area_weight_m2'},csv_text(['easting','northing','area_weight_m2'],rows))
    if kind=='blocked_regression':
        table('Held-out observations versus prediction','spatial_oof_agreement',{'x':'observed','y':'prediction','group':'fold'})
        table('Held-out residual by fold','strip',{'y':'residual','group':'fold'})
        table('Residual versus easting','basic_scatter',{'x':'easting','y':'residual'})
        folds=metrics.get('folds',[])
        if folds and all(isinstance(f.get('rmse'),(int,float)) and 'fold' in f for f in folds):
            add('Fold RMSE','basic_column',{'x':'fold','y':'rmse'},csv_text(['fold','rmse'],[[f['fold'],f['rmse']] for f in folds]))
    if kind in {'zonal_statistics','zonal_quantiles'}:
        if len(result['rows'])<=50:
            table('Valid area by zone','spatial_zonal_coverage',{'x':'zone_index','y':'valid_area_m2','z':'zone_area_m2'})
            for field in ['weighted_mean','weighted_quantile']:
                if field in cols and any(r[result['columns'].index(field)] is not None for r in result['rows']):
                    table(field.replace('_',' ').capitalize()+' by zone','basic_column',{'x':'zone_index','y':field})
    if kind=='zonal_classes':
        rows=result['rows'];zones=sorted(set(r[0] for r in rows));classes=sorted(set(r[1] for r in rows))
        if len(zones)<=50 and 2<=len(classes)<=12:
            keys=['Class '+str(c) for c in classes];lookup={(r[0],r[1]):r[2] for r in rows}
            add('Class area by zone','stacked_bar',{'x':'zone_index','columns':keys},csv_text(['zone_index',*keys],[[z,*[lookup.get((z,c),0.) for c in classes]] for z in zones]))
    if kind in {'nearest_join','point_nearest_neighbor'}:
        table('Nearest-distance distribution','basic_rank',{'y':'distance_m'})
    if kind=='point_ellipse':table('Covariance ellipse boundary','basic_scatter',{'x':'easting','y':'northing'})
    if kind=='extract_points' and any(r[-1] is not None for r in result['rows']):table('Extracted observations','basic_scatter',{'x':'source_index','y':'value'})
    weights=metrics.get('normalized_weights')
    if weights and len(weights)==len(grids):
        add('Criterion weights','basic_column',{'x':'criterion','y':'weight'},csv_text(['criterion','weight'],[[f'Criterion {i+1}',w] for i,w in enumerate(weights)]))
    return figures
