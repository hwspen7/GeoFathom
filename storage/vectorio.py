"""Bounded, schema-preserving GIS interchange using GDAL and explicit codecs.

WGS84 is the editing store; output CRS belongs to the delivered dataset. Formats
with restricted attribute types carry a documented lossless companion encoding.
"""
import csv
import hashlib
import io
import json
import math
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pyogrio
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform
from geometry.measure import measure_geometry, GeometryError

class VectorIOError(ValueError):
    pass

MAX_BYTES = 128 * 1024 * 1024
MAX_FEATURES = 100_000
MAX_VERTICES = 4_000_000
_DRIVERS = {'.geojson':'GeoJSON','.json':'GeoJSON','.gpkg':'GPKG',
            '.kml':'KML','.gpx':'GPX','.zip':'ESRI Shapefile','.csv':'CSV'}
_ENCODING = {'utf-8','utf-8-sig','utf-16','cp1252','gb18030'}
_GF = 'https://geofathom.local/interchange/1'
ET.register_namespace('gf', _GF)

def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',',':'))

def _crs(value):
    from .crs import _epsg
    try:return CRS.from_user_input(_epsg(value))
    except ValueError as exc:raise VectorIOError('Use a supported horizontal 2D EPSG coordinate reference.') from exc

def _project(geometry, source, target):
    try:
        converter = Transformer.from_crs(_crs(source), _crs(target), always_xy=True, allow_ballpark=False)
        result = mapping(transform(lambda x,y,z=None: (*converter.transform(x,y,errcheck=True),z) if z is not None else converter.transform(x,y,errcheck=True), shape(geometry)))
        # JSON serialization rejects nonfinite projected ordinates as well as properties.
        dumps(result)
        return result
    except Exception as exc:
        raise VectorIOError('Geometry is outside the coordinate transformation domain.') from exc

def _properties(value):
    if not isinstance(value,dict) or len(dumps(value).encode()) > 100_000:
        raise VectorIOError('Properties must be a JSON object of at most 100 KB.')
    if any(not isinstance(k,str) or not k or len(k)>64 or any(ord(c)<32 for c in k) for k in value):
        raise VectorIOError('Field names must contain 1–64 printable characters.')
    return value

def field_schema(features):
    fields={};counts={}
    for feature in features:
        for key,value in feature.get('properties',{}).items():
            counts[key]=counts.get(key,0)+1
            types=fields.setdefault(key,set())
            types.add('null' if value is None else 'boolean' if isinstance(value,bool) else
                      'integer' if isinstance(value,int) else 'number' if isinstance(value,float) else
                      'string' if isinstance(value,str) else 'json')
    return [{'name':key,'types':sorted(types),'nullable':'null' in types or counts[key]<len(features)}
            for key,types in fields.items()]

def _input_file(root,name,blob):
    suffix=Path(name).suffix.lower()
    if suffix not in _DRIVERS: raise VectorIOError('Supported: GeoJSON, GPKG, KML, GPX, zipped SHP and CSV.')
    if not 0<len(blob)<=MAX_BYTES: raise VectorIOError('Vector file must be nonempty and at most 128 MB.')
    if suffix!='.zip':
        path=root/('dataset'+suffix);path.write_bytes(blob);return [path],None
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            entries=archive.infolist()
            if len(entries)>600 or sum(e.file_size for e in entries)>512*1024*1024:
                raise VectorIOError('Expanded Shapefile bundle exceeds 512 MB or 600 entries.')
            allowed={'.shp','.shx','.dbf','.prj','.cpg'}
            seen=set()
            for entry in entries:
                p=Path(entry.filename)
                if (p.name!=entry.filename or '\\' in entry.filename or entry.is_dir() or
                    p.name.startswith('.') or entry.flag_bits&1 or
                    (entry.external_attr>>16)&0o170000==0o120000 or
                    (p.suffix.lower() not in allowed and p.name!='geofathom.json') or
                    p.name.lower() in seen):
                    raise VectorIOError('Unsafe or unsupported Shapefile bundle member.')
                seen.add(p.name.lower())
                (root/p.name).write_bytes(archive.read(entry))
        paths=sorted(root.glob('*.shp'))+sorted(root.glob('*.SHP'))
        if not paths:raise VectorIOError('Shapefile .shp component is missing.')
        manifest_path=root/'geofathom.json'
        manifest=json.loads(manifest_path.read_text('utf-8')) if manifest_path.exists() else None
        if manifest:
            if manifest.get('schema')!='geofathom.shapefile.v1':raise VectorIOError('Unsupported Shapefile companion schema.')
            for filename,digest in manifest.get('checksums',{}).items():
                if Path(filename).name!=filename or not (root/filename).is_file() or hashlib.sha256((root/filename).read_bytes()).hexdigest()!=digest:
                    raise VectorIOError('Shapefile companion checksum mismatch.')
        return paths,manifest
    except (zipfile.BadZipFile,KeyError,json.JSONDecodeError) as exc:
        raise VectorIOError('Invalid Shapefile bundle.') from exc

def _xml_features(blob):
    if b'<!DOCTYPE' in blob.upper() or b'<!ENTITY' in blob.upper():raise VectorIOError('XML entities are unsupported.')
    root=ET.fromstring(blob)
    # Our lossless properties accompany standard KML/GPX geometry, never replace it.
    def local(node): return node.tag.rsplit('}',1)[-1]
    def coords(node):
        return [[float(v) for v in item.split(',')] for item in (node.text or '').split()]
    def kgeom(node):
        kind=local(node)
        if kind=='Point':return {'type':'Point','coordinates':coords(next(n for n in node.iter() if local(n)=='coordinates'))[0]}
        if kind=='LineString':return {'type':'LineString','coordinates':coords(next(n for n in node.iter() if local(n)=='coordinates'))}
        if kind=='Polygon':return {'type':'Polygon','coordinates':[coords(n) for n in node.iter() if local(n)=='coordinates']}
        if kind=='MultiGeometry':
            parts=[kgeom(n) for n in node if local(n) in {'Point','LineString','Polygon','MultiGeometry'}]
            types={p['type'] for p in parts}
            if len(types)!=1 or next(iter(types)) not in {'Point','LineString','Polygon'}:raise VectorIOError('Mixed KML collections require separate layers.')
            return {'type':'Multi'+parts[0]['type'],'coordinates':[p['coordinates'] for p in parts]}
        raise VectorIOError('Unsupported KML geometry.')
    for node in root.iter():
        if local(node) not in {'Placemark','wpt','trk','rte'}:continue
        encoded=node.find('.//{'+_GF+'}properties')
        if encoded is None:continue
        props=json.loads(encoded.text or '{}')
        kind=local(node)
        if kind=='Placemark':
            geom=kgeom(next(n for n in node if local(n) in {'Point','LineString','Polygon','MultiGeometry'}))
        elif kind=='wpt':geom={'type':'Point','coordinates':[float(node.attrib['lon']),float(node.attrib['lat'])]}
        else:
            segments=[[[float(p.attrib['lon']),float(p.attrib['lat'])] for p in segment if local(p) in {'trkpt','rtept'}]
                      for segment in node if local(segment)=='trkseg'] if kind=='trk' else [
                      [[float(p.attrib['lon']),float(p.attrib['lat'])] for p in node if local(p)=='rtept']]
            multiple=node.find('.//{'+_GF+'}geometry_type')
            geom={'type':'MultiLineString','coordinates':segments} if len(segments)>1 or (multiple is not None and multiple.text=='MultiLineString') else {'type':'LineString','coordinates':segments[0]}
        layer=node.find('.//{'+_GF+'}layer')
        yield {'type':'Feature','geometry':geom,'properties':props,'geofathom_layer':layer.text if layer is not None else ('GPX' if local(root)=='gpx' else 'KML')}

def _layer_catalog(paths,options):
    chosen=options.get('layers')
    layers=[]
    for path in paths:
        for name,kind in pyogrio.list_layers(path):
            if kind is None:continue
            key=str(name) if len(paths)==1 else path.stem+':'+str(name)
            info=pyogrio.read_info(path,layer=name)
            if info['driver'] not in set(_DRIVERS.values())|{'LIBKML'}:raise VectorIOError('Unsupported vector driver.')
            layers.append({'name':key,'source_crs':info.get('crs'),'feature_count':int(info.get('features',-1)),
                'geometry_type':kind,'fields':[{'name':str(n),'type':str(t)} for n,t in zip(info.get('fields',[]),info.get('dtypes',[])) if str(n)!='_gf_json'],
                '_path':path,'_layer':name})
    if chosen is not None and set(chosen)-{l['name'] for l in layers}:raise VectorIOError('Selected source layer does not exist.')
    return layers

def _raw_layers(paths,manifest,options):
    chosen=options.get('layers')
    for layer in _layer_catalog(paths,options):
        if chosen is not None and layer['name'] not in chosen:continue
        source=layer['source_crs'] or options.get('source_crs')
        if not source:raise VectorIOError('Source CRS is missing; specify its EPSG explicitly.')
        for offset in range(0,MAX_FEATURES+1,512):
            meta,fids,geoms,arrays=pyogrio.raw.read(layer['_path'],layer=layer['_layer'],skip_features=offset,
                max_features=512,return_fids=True,datetime_as_string=True,encoding=options.get('encoding','utf-8'))
            if not len(geoms):break
            companion=(manifest or {}).get('layers',{}).get(layer['_path'].stem,{})
            encoded_column=meta.get('layer_metadata',{}).get('GEOFATHOM_JSON') if meta.get('layer_metadata') else None
            # read_info exposes driver metadata even on GDAL versions where raw.read omits it.
            metadata=pyogrio.read_info(layer['_path'],layer=layer['_layer']).get('layer_metadata') or {}
            encoded_column=metadata.get('GEOFATHOM_JSON',encoded_column)
            native_rows={}
            field_map=json.loads(metadata.get('GEOFATHOM_FIELDS','{}'))
            if encoded_column and layer['_path'].suffix=='.gpkg' and field_map:
                def quote(value):return '"'+str(value).replace('"','""')+'"'
                fid=pyogrio.read_info(layer['_path'],layer=layer['_layer'])['fid_column']
                with sqlite3.connect(layer['_path'].resolve().as_uri()+'?mode=ro',uri=True) as sql:
                    sql.row_factory=sqlite3.Row
                    query='SELECT * FROM '+quote(layer['_layer'])+' WHERE '+quote(fid)+' IN ('+','.join('?' for _ in fids)+')'
                    native_rows={r[fid]:dict(r) for r in sql.execute(query,[int(v) for v in fids])}
            for i,wkb in enumerate(geoms):
                props={}
                for field,values in zip(meta.get('fields',[]),arrays):
                    value=values[i]
                    if isinstance(value,np.generic):value=value.item()
                    if isinstance(value,float) and not math.isfinite(value):value=None
                    props[str(field)]=value if value is None or isinstance(value,(str,int,float,bool)) else str(value)
                if encoded_column and encoded_column in props:
                    encoded=json.loads(props[encoded_column])
                    native=native_rows.get(int(fids[i]),props)
                    # Preserve exact originals only while native columns agree.
                    # External GIS edits take precedence over the typed companion.
                    for column,original in field_map.items():
                        value=native.get(column);previous=encoded.get(original)
                        expected=dumps(previous) if previous is not None and isinstance(value,str) and not isinstance(previous,str) else previous
                        if value!=expected:
                            if isinstance(previous,(dict,list)) and isinstance(value,str):
                                try:value=json.loads(value)
                                except ValueError:pass
                            encoded[original]=value
                    for column,value in props.items():
                        if column!=encoded_column and column not in field_map:encoded[column]=value
                    props=encoded
                elif companion:
                    rows=companion.get('properties',[])
                    if offset+i>=len(rows):raise VectorIOError('Shapefile companion row count mismatch.')
                    props=rows[offset+i]
                yield layer['name'],offset+i+1,source,{'type':'Feature','geometry':mapping(shapely.from_wkb(wkb)) if wkb is not None else None,'properties':props}
            if len(geoms)<512:break

def read_vector(name,blob,options=None,progress=None):
    options=options or {};progress=progress or (lambda _:None)
    if options.get('encoding','utf-8') not in _ENCODING:raise VectorIOError('Unsupported text encoding.')
    errors=[];entries=[];vertices=0;count=0;layer_names=set();source_crs=None
    with tempfile.TemporaryDirectory(prefix='geofathom-vector-') as tmp:
        paths,manifest=_input_file(Path(tmp),name,blob)
        suffix=Path(name).suffix.lower()
        def incoming():
            if suffix in {'.geojson','.json'}:
                obj=json.loads(blob.decode('utf-8-sig'),parse_constant=lambda x:(_ for _ in ()).throw(VectorIOError('Nonfinite JSON value.')))
                features=obj.get('features') if obj.get('type')=='FeatureCollection' else [obj] if obj.get('type')=='Feature' else None
                if not isinstance(features,list):raise VectorIOError('Expected a GeoJSON FeatureCollection.')
                legacy=obj.get('crs',{}).get('properties',{}).get('name') if isinstance(obj.get('crs'),dict) else None
                source=options.get('source_crs') or legacy or 'EPSG:4326'
                for i,feature in enumerate(features):
                    layer=str(feature.get('geofathom_layer','GeoJSON')) if isinstance(feature,dict) else 'GeoJSON'
                    if options.get('layers') is None or layer in options['layers']:yield layer,i+1,source,feature
            elif suffix=='.csv':
                text=blob.decode(options.get('encoding','utf-8-sig'))
                delimiter=options.get('delimiter',',')
                if delimiter not in {',',';','\t','|'}:raise VectorIOError('Unsupported CSV delimiter.')
                reader=csv.DictReader(io.StringIO(text),delimiter=delimiter)
                if not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames):raise VectorIOError('CSV headers must be present and unique.')
                _properties({key:None for key in reader.fieldnames})
                for i,row in enumerate(reader):
                    try:
                        geometry=mapping(shapely.from_wkt(row[options['geometry_field']])) if options.get('geometry_field') else {
                            'type':'Point','coordinates':[float(row[options.get('longitude_field','longitude')]),float(row[options.get('latitude_field','latitude')])]}
                    except (KeyError,ValueError,TypeError,shapely.errors.GEOSException):geometry=None
                    yield 'CSV',i+1,options.get('source_crs') or 'EPSG:4326',{'type':'Feature','geometry':geometry,'properties':row}
            elif suffix in {'.kml','.gpx'} and ('xmlns:gf="'+_GF+'"').encode() in blob:
                for i,feature in enumerate(_xml_features(blob)):
                    layer=feature['geofathom_layer']
                    if options.get('layers') is None or layer in options['layers']:yield layer,i+1,'EPSG:4326',feature
            else:yield from _raw_layers(paths,manifest,options)
        try:
            for layer,row,crs,feature in incoming():
                count+=1
                if count>MAX_FEATURES:raise VectorIOError('Import exceeds 100,000 features; subdivide the dataset.')
                if count%256==0:progress(min(.8,count/MAX_FEATURES*.8))
                try:
                    if not isinstance(feature,dict) or feature.get('type')!='Feature':raise VectorIOError('Expected a geographic feature.')
                    props=_properties({} if feature.get('properties') is None else feature['properties'])
                    mapping_options=options.get('field_map') or {}
                    if len(set(mapping_options.values()))!=len(mapping_options):raise VectorIOError('Field mapping has duplicate destinations.')
                    destinations=[mapping_options.get(k,k) for k in props]
                    if len(set(destinations))!=len(destinations):raise VectorIOError('Field mapping would overwrite an existing field.')
                    props={mapping_options.get(k,k):v for k,v in props.items()}
                    for key,kind in (options.get('field_types') or {}).items():
                        if key not in props or props[key] is None:continue
                        value=props[key]
                        if kind=='integer':
                            if isinstance(value,bool) or not re.fullmatch(r'[+-]?\d+',str(value)):raise VectorIOError('Invalid integer field: '+key)
                            props[key]=int(value)
                        elif kind=='number':props[key]=float(value)
                        elif kind=='boolean':
                            if str(value).lower() not in {'true','false','1','0'}:raise VectorIOError('Invalid boolean field: '+key)
                            props[key]=str(value).lower() in {'true','1'}
                        elif kind=='json':props[key]=json.loads(value) if isinstance(value,str) else value
                        elif kind=='string':props[key]=str(value)
                        else:raise VectorIOError('Unsupported field conversion.')
                    _properties(props)
                    geom=feature.get('geometry')
                    if not geom:raise VectorIOError('Feature has no geometry.')
                    geom=_project(geom,crs,'EPSG:4326') if _crs(crs)!=CRS.from_epsg(4326) else geom
                    measured=measure_geometry(geom);vertices+=measured['coordinate_count']
                    entries.append({'geometry':geom,'properties':props,'name':str(props.get('name') or props.get('Name') or f'Imported feature {row}')[:200],
                        'source':f'{_DRIVERS[suffix]} imported file; source CRS {crs}','source_layer':layer,'source_row':row})
                    layer_names.add(layer);source_crs=str(crs)
                except (GeometryError,VectorIOError,ValueError,TypeError) as exc:
                    errors.append({'layer':layer,'row':row,'message':str(exc)})
                    if len(errors)>1000:raise VectorIOError('More than 1,000 invalid rows; correct the source first.')
                if vertices>MAX_VERTICES:raise VectorIOError('Dataset exceeds four million vertices.')
        except (pyogrio.errors.DataSourceError,pyogrio.errors.DataLayerError,ValueError,ET.ParseError) as exc:
            raise VectorIOError(str(exc)) from exc
    if errors and options.get('error_policy','strict')!='skip':raise VectorIOError('Validation failed: '+dumps(errors[:20]))
    progress(.85)
    return {'features':entries,'source_crs':source_crs,'count':len(entries),'driver':_DRIVERS[suffix],
            'layers':sorted(layer_names),'schema':field_schema(entries),'errors':errors,'rejected':len(errors),'rows':count}

def inspect_vector(name,blob,options=None):
    options=options or {}
    with tempfile.TemporaryDirectory(prefix='geofathom-inspect-') as tmp:
        paths,manifest=_input_file(Path(tmp),name,blob)
        if paths[0].suffix.lower()=='.csv':
            reader=csv.DictReader(io.StringIO(blob.decode(options.get('encoding','utf-8-sig'))),delimiter=options.get('delimiter',','))
            fields=reader.fieldnames or []
            if not fields or len(set(fields))!=len(fields):raise VectorIOError('CSV headers must be present and unique.')
            _properties({f:None for f in fields})
            count=sum(1 for _ in reader)
            if count>MAX_FEATURES:raise VectorIOError('Import exceeds 100,000 features.')
            return {'layers':[{'name':'CSV','source_crs':options.get('source_crs') or 'EPSG:4326','feature_count':count,'fields':[{'name':f,'type':'string'} for f in fields],'geometry_type':'CSV coordinates'}]}
        custom_xml=Path(name).suffix.lower() in {'.kml','.gpx'} and ('xmlns:gf="'+_GF+'"').encode() in blob
        if paths[0].suffix.lower() not in {'.json','.geojson'} and not custom_xml:
            layers=_layer_catalog(paths,options)
            return {'layers':[{k:v for k,v in layer.items() if not k.startswith('_')} for layer in layers]}
    parsed=read_vector(name,blob,{**options,'error_policy':'skip'})
    return {'layers':[{'name':layer,'source_crs':parsed['source_crs'],'feature_count':sum(f['source_layer']==layer for f in parsed['features']),
             'fields':field_schema([f for f in parsed['features'] if f['source_layer']==layer]),'geometry_type':'Mixed'} for layer in parsed['layers']], 'errors':parsed['errors'][:20]}

def export_warnings(features,format_name,target_crs='EPSG:4326'):
    warnings=[];_crs(target_crs)
    if format_name not in {'geojson','gpkg','shapefile','kml','gpx','csv','report'}:raise VectorIOError('Unsupported vector export format.')
    if format_name=='csv':warnings.append('CSV represents null as empty text and nested values as JSON; choose GeoJSON or GPKG for exact attribute types.')
    if format_name in {'kml','gpx','geojson','report'} and _crs(target_crs)!=CRS.from_epsg(4326):
        raise VectorIOError('GeoJSON, KML, GPX and measurement reports require WGS84 (EPSG:4326). Choose GPKG, SHP or CSV for projected coordinates.')
    if format_name=='gpx' and any(f['geometry']['type'] not in {'Point','LineString','MultiLineString'} for f in features):
        raise VectorIOError('GPX supports points and lines only. Use another format for polygons.')
    if format_name=='shapefile':warnings.append('SHP uses short field aliases and separate geometry layers; keep geofathom.json for exact types, nulls and original names.')
    if any(t=='json' for f in field_schema(features) for t in f['types']):warnings.append('Nested attributes are JSON text in external GIS columns; GeoFathom restores their original JSON types.')
    return warnings

def _columns(features,short=False):
    fields=[f['name'] for f in field_schema(features)];used=set();names=[];arrays=[];masks=[]
    for index,field in enumerate(fields):
        name=('f'+str(index).zfill(8)) if short or field.lower() in {'fid','geom','geometry','_gf_json'} else field
        if name.lower() in used: name='field_'+str(index)
        used.add(name.lower());names.append(name)
        values=[f.get('properties',{}).get(field) for f in features];nonnull=[v for v in values if v is not None]
        mask=np.array([v is None for v in values],dtype=bool)
        if nonnull and all(type(v) is bool for v in nonnull):array=np.array([False if v is None else v for v in values],dtype=bool)
        elif nonnull and all(type(v) is int and -(2**63)<=v<2**63 for v in nonnull):array=np.array([0 if v is None else v for v in values],dtype=np.int64)
        elif nonnull and all(type(v) in {int,float} and not (type(v) is int and abs(v)>2**53) for v in nonnull):array=np.array([0 if v is None else v for v in values],dtype=np.float64)
        else:array=np.array([None if v is None else v if isinstance(v,str) else dumps(v) for v in values],dtype=object)
        arrays.append(array);masks.append(mask)
    return fields,names,arrays,masks

def write_vector(collection,format_name,target_crs='EPSG:4326',fields=None,precision=None,progress=None):
    progress=progress or (lambda _:None)
    features=collection.get('features',[])
    if not features:raise VectorIOError('There are no features to export.')
    if len(features)>MAX_FEATURES:raise VectorIOError('Export exceeds 100,000 features.')
    if precision is not None and (type(precision) is not int or not 0<=precision<=15):raise VectorIOError('Coordinate precision must be 0–15 decimals.')
    if fields is not None and (len(set(fields))!=len(fields) or set(fields)-{f['name'] for f in field_schema(features)}):raise VectorIOError('Requested export fields are duplicated or missing.')
    prepared=[];vertices=0
    for index,f in enumerate(features):
        if index%256==0:progress(index/max(1,len(features)))
        vertices+=measure_geometry(f['geometry'])['coordinate_count']
        if vertices>MAX_VERTICES:raise VectorIOError('Export exceeds four million vertices.')
        props=_properties({} if f.get('properties') is None else f['properties'])
        if fields is not None:props={k:v for k,v in props.items() if k in fields}
        geom=_project(f['geometry'],'EPSG:4326',target_crs) if _crs(target_crs)!=CRS.from_epsg(4326) else f['geometry']
        if precision is not None:
            def rounded(obj):return [rounded(v) for v in obj] if isinstance(obj,(list,tuple)) else round(obj,precision) if isinstance(obj,(int,float)) else obj
            geom={**geom,'coordinates':rounded(geom['coordinates'])}
            if not shape(geom).is_valid or shape(geom).is_empty:raise VectorIOError('Selected precision collapses or invalidates a geometry; increase precision.')
        prepared.append({'type':'Feature','geometry':geom,'properties':props,**({'geofathom_layer':f['geofathom_layer']} if f.get('geofathom_layer') else {})})
    export_warnings(features,format_name,target_crs)
    if format_name=='report':
        return dumps({'schema':'geofathom.export-report.v2','feature_count':len(features),
            'coordinate_system':'EPSG:4326','measurements':[{'id':f.get('id'),'name':f.get('properties',{}).get('name','Unnamed'),
            'geometry_type':f['geometry']['type'],**measure_geometry(f['geometry']),'properties':p['properties']} for f,p in zip(features,prepared)]}).encode(),'application/json','geofathom-report.json'
    if format_name=='geojson':return dumps({'type':'FeatureCollection','features':prepared}).encode(),'application/geo+json','geofathom.geojson'
    if format_name=='csv':
        keys=[f['name'] for f in field_schema(prepared)]
        if {'geometry_wkt','crs'}&set(keys):raise VectorIOError('Rename attributes geometry_wkt or crs before CSV export; these names describe the output geometry.')
        out=io.StringIO();writer=csv.writer(out)
        writer.writerow([*keys,'geometry_wkt','crs'])
        for f in prepared:
            values=[]
            for key in keys:
                value=f['properties'].get(key)
                value=dumps(value) if isinstance(value,(dict,list)) else '' if value is None else value
                if isinstance(value,str) and re.match(r'^[\s\ufeff]*[=+\-@]',value):value="'"+value
                values.append(value)
            writer.writerow([*values,shape(f['geometry']).wkt,target_crs])
        return ('\ufeff'+out.getvalue()).encode(),'text/csv;charset=utf-8','geofathom.csv'
    if format_name in {'kml','gpx'}:
        root=ET.Element('kml',xmlns='http://www.opengis.net/kml/2.2') if format_name=='kml' else ET.Element('gpx',version='1.1',creator='GeoFathom',xmlns='http://www.topografix.com/GPX/1/1')
        document=ET.SubElement(root,'Document') if format_name=='kml' else root
        def coordinates(coords):return ' '.join(','.join(str(v) for v in p) for p in coords)
        def kgeom(parent,geo):
            kind=geo['type'];coords=geo['coordinates']
            if kind.startswith('Multi'):
                group=ET.SubElement(parent,'MultiGeometry')
                for part in coords:kgeom(group,{'type':kind[5:],'coordinates':part})
            elif kind=='Point':ET.SubElement(ET.SubElement(parent,'Point'),'coordinates').text=coordinates([coords])
            elif kind=='LineString':ET.SubElement(ET.SubElement(parent,'LineString'),'coordinates').text=coordinates(coords)
            elif kind=='Polygon':
                node=ET.SubElement(parent,'Polygon')
                for i,ring in enumerate(coords):ET.SubElement(ET.SubElement(ET.SubElement(node,'outerBoundaryIs' if i==0 else 'innerBoundaryIs'),'LinearRing'),'coordinates').text=coordinates(ring)
            else:raise VectorIOError('Unsupported KML geometry.')
        for f in prepared:
            geom=f['geometry'];props=f['properties']
            if format_name=='kml':
                node=ET.SubElement(document,'Placemark');ext=ET.SubElement(node,'ExtendedData')
                for key,value in props.items():ET.SubElement(ET.SubElement(ext,'Data',name=key),'value').text=value if isinstance(value,str) else dumps(value)
            elif geom['type']=='Point':
                node=ET.SubElement(document,'wpt',lon=str(geom['coordinates'][0]),lat=str(geom['coordinates'][1]));ext=ET.SubElement(node,'extensions')
            else:
                node=ET.SubElement(document,'trk')
                for path in [geom['coordinates']] if geom['type']=='LineString' else geom['coordinates']:
                    segment=ET.SubElement(node,'trkseg')
                    for point in path:ET.SubElement(segment,'trkpt',lon=str(point[0]),lat=str(point[1]))
                ext=ET.SubElement(node,'extensions');ET.SubElement(ext,'{'+_GF+'}geometry_type').text=geom['type']
            name_node=ET.Element('name');name_node.text=str(props.get('name','Feature'));node.insert(0,name_node)
            desc_node=ET.Element('description' if format_name=='kml' else 'desc');desc_node.text=str(props.get('source',''));node.insert(1,desc_node)
            if format_name=='kml':kgeom(node,geom)
            if f.get('geofathom_layer'):ET.SubElement(ext,'{'+_GF+'}layer').text=f['geofathom_layer']
            ET.SubElement(ext,'{'+_GF+'}properties').text=dumps(props)
            if format_name=='gpx' and geom['type']!='Point':node.remove(ext);node.insert(2,ext)
        return ET.tostring(root,encoding='utf-8',xml_declaration=True),'application/vnd.google-earth.kml+xml' if format_name=='kml' else 'application/gpx+xml','geofathom.'+format_name
    if format_name not in {'gpkg','shapefile'}:raise VectorIOError('Unsupported vector export format.')
    groups={}
    for f in prepared:
        family=f['geometry']['type'] if f['geometry']['type'] in {'Point','MultiPoint'} else f['geometry']['type'].replace('Multi','')
        groups.setdefault((f.get('geofathom_layer','features'),family),[]).append(f)
    with tempfile.TemporaryDirectory(prefix='geofathom-export-') as temp:
        root=Path(temp);output=root/'geofathom.gpkg';manifest={'schema':'geofathom.shapefile.v1','layers':{},'checksums':{}}
        for index,((source_layer,family),items) in enumerate(groups.items()):
            layer=(re.sub(r'[^a-zA-Z0-9_]','_',str(source_layer))[:40] or 'features')+'_'+family.lower()+'_'+str(index);short=format_name=='shapefile'
            original,names,arrays,masks=_columns(items,short)
            if not short:
                names.append('_gf_json');arrays.append(np.array([dumps(f['properties']) for f in items],dtype=object));masks.append(np.zeros(len(items),dtype=bool))
            target=root/(layer+'.shp') if short else output
            pyogrio.raw.write(target,np.array([shapely.to_wkb(shape(f['geometry'])) for f in items],dtype=object),arrays,names,
                field_mask=masks,driver='ESRI Shapefile' if short else 'GPKG',layer=layer,crs=target_crs,encoding='UTF-8',
                geometry_type='Unknown' if not short else ('Multi'+family if any(f['geometry']['type'].startswith('Multi') for f in items) and family not in {'Point','MultiPoint'} else family),
                layer_metadata=None if short else {'GEOFATHOM_JSON':'_gf_json','GEOFATHOM_FIELDS':dumps(dict(zip(names[:-1],original)))})
            if short:manifest['layers'][layer]={'fields':dict(zip(names,original)),'properties':[f['properties'] for f in items]}
        if format_name=='gpkg':return output.read_bytes(),'application/geopackage+sqlite3','geofathom.gpkg'
        out=io.BytesIO()
        for path in root.iterdir():manifest['checksums'][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in root.iterdir():archive.write(path,path.name)
            archive.writestr('geofathom.json',dumps(manifest))
        return out.getvalue(),'application/zip','geofathom-shapefile.zip'
