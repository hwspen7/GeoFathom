"""Checksummed portable projects; restoration only targets a new empty project."""
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

from imagery.store import image_file,describe,store_upload
from geometry.measure import measure_geometry
from .vectorio import dumps,VectorIOError,_properties
from .exchange import snapshot
from .database import _connect,_required_project,_record_feature,_now,StorageError
from .workspace import _schema,_default
from .cartography import _ensure_table,_validate,default_style
from .crs import _epsg,_table

LIMIT=512*1024*1024

def build_package(project_id,rasters=None):
    data=snapshot(project_id,include_history=True)
    data['schema']='geofathom.project.v1';data['rasters']=[]
    files={};total=0
    for selected in rasters or []:
        identifier=selected['id']
        path=image_file(identifier);binary=path.read_bytes();total+=len(binary)
        if total>LIMIT:raise VectorIOError('Referenced rasters exceed the 512 MB package budget.')
        name='rasters/'+identifier+'.tif';files[name]=binary
        data['rasters'].append({'id':identifier,'path':name,'kind':selected.get('kind','image'),
            'name':describe(identifier)['name'],'provenance':describe(identifier).get('provenance')})
    files['project.json']=dumps(data).encode()
    total+=len(files['project.json'])
    if total>LIMIT:raise VectorIOError('Portable project exceeds 512 MB.')
    manifest={'schema':'geofathom.package.v1','files':{name:{'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)} for name,b in files.items()}}
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',dumps(manifest))
        for name,binary in files.items():archive.writestr(name,binary)
    return output.getvalue()

def restore_package(project_id,binary):
    staged=[];stored=[]
    try:
        with zipfile.ZipFile(io.BytesIO(binary)) as archive:
            entries=archive.infolist();names=[e.filename for e in entries]
            if len(entries)>103 or len(set(names))!=len(names) or sum(e.file_size for e in entries)>LIMIT:raise VectorIOError('Package exceeds bounds or has duplicate entries.')
            for e in entries:
                if e.flag_bits&1 or e.is_dir() or (e.external_attr>>16)&0o170000==0o120000:raise VectorIOError('Unsafe project archive member.')
                if e.filename not in {'manifest.json','project.json'}:
                    parts=Path(e.filename).parts
                    if len(parts)!=2 or parts[0]!='rasters' or parts[1].startswith('.') or '\\' in e.filename or Path(parts[1]).suffix!='.tif':raise VectorIOError('Unsafe project archive path.')
            manifest=json.loads(archive.read('manifest.json'))
            if manifest.get('schema')!='geofathom.package.v1' or set(manifest.get('files',{}))!={'project.json',*(n for n in names if n.startswith('rasters/'))}:raise VectorIOError('Package manifest is incomplete or unsupported.')
            for name,meta in manifest['files'].items():
                data=archive.read(name)
                if len(data)!=meta['bytes'] or hashlib.sha256(data).hexdigest()!=meta['sha256']:raise VectorIOError('Package checksum mismatch: '+name)
            data=json.loads(archive.read('project.json'))
            if data.get('schema')!='geofathom.project.v1':raise VectorIOError('Unsupported project schema.')
            layers=data.get('layers',[]);features=data.get('features',[]);revisions=data.get('revisions',[])
            if not 1<=len(layers)<=100 or len(features)>100000 or len(revisions)>100000:raise VectorIOError('Project object count exceeds limits.')
            layer_ids={l['id'] for l in layers}
            if len(layer_ids)!=len(layers):raise VectorIOError('Duplicate layer IDs.')
            for layer in layers:
                if not isinstance(layer['name'],str) or not 1<=len(layer['name'])<=100:raise VectorIOError('Invalid layer name.')
                if not __import__('re').fullmatch('#[0-9A-Fa-f]{6}',layer['color']):raise VectorIOError('Invalid layer color.')
                _validate(layer['style'],default_style())
            feature_ids={f['id'] for f in features}
            if len(feature_ids)!=len(features):raise VectorIOError('Duplicate feature IDs.')
            vertices=0
            for feature in features:
                if feature['layer_id'] not in layer_ids:raise VectorIOError('Feature references an unknown layer.')
                _properties(feature['properties']);vertices+=measure_geometry(feature['geometry'])['coordinate_count']
            if vertices>4_000_000:raise VectorIOError('Package exceeds the geometry vertex budget.')
            version_keys=set()
            for revision in revisions:
                key=(revision['feature_id'],revision['revision'])
                if key in version_keys or key[0] not in feature_ids or type(key[1]) is not int or key[1]<0:raise VectorIOError('Invalid feature revision history.')
                version_keys.add(key);_properties(json.loads(revision['properties']));vertices+=measure_geometry(json.loads(revision['geometry']))['coordinate_count']
                if vertices>4_000_000:raise VectorIOError('Package history exceeds the geometry vertex budget.')
            epsg=_epsg(data.get('crs',{}).get('epsg','EPSG:4326'))
            # Validate target before touching the raster catalog.
            with _connect() as c:
                _required_project(c,project_id);_schema(c)
                if c.execute('SELECT count(*) FROM features WHERE project_id=?',(project_id,)).fetchone()[0] or c.execute('SELECT count(*) FROM geo_layers WHERE project_id=?',(project_id,)).fetchone()[0]>1:
                    raise StorageError('Restore into a new empty project; existing work is never replaced.')
            rasters=data.get('rasters',[])
            if len(rasters)>100 or len({r['id'] for r in rasters})!=len(rasters) or {r['path'] for r in rasters}!={n for n in manifest['files'] if n.startswith('rasters/')}:raise VectorIOError('Raster references are duplicated or incomplete.')
            with tempfile.TemporaryDirectory(prefix='geofathom-restore-') as tmp:
                for raster in data.get('rasters',[]):
                    if raster['path'] not in manifest['files'] or raster.get('kind') not in {'dem','image'}:raise VectorIOError('Invalid raster reference.')
                    path=Path(tmp)/(str(uuid4())+'.tif');path.write_bytes(archive.read(raster['path']))
                    asset=store_upload(path,raster['name'],raster.get('provenance'))
                    stored.append(asset['id']);staged.append({'old_id':raster['id'],'asset':asset,'kind':raster['kind']})
        raster_map={r['old_id']:r['asset']['id'] for r in staged}
        def relink(obj):
            if isinstance(obj,dict):return {k:raster_map.get(v,v) if isinstance(v,str) and (k.endswith('image_id') or k in {'image_id','dem_id','source_id'}) else relink(v) for k,v in obj.items()}
            if isinstance(obj,list):return [relink(v) for v in obj]
            return obj
        with _connect() as c:
            _schema(c);_ensure_table(c);_table(c);c.execute('BEGIN IMMEDIATE');_required_project(c,project_id)
            if c.execute('SELECT count(*) FROM features WHERE project_id=?',(project_id,)).fetchone()[0] or c.execute('SELECT count(*) FROM geo_layers WHERE project_id=?',(project_id,)).fetchone()[0]>1:raise StorageError('Target project changed during restore.')
            default=_default(c,project_id);layer_map={};feature_map={}
            for i,layer in enumerate(layers):
                identifier=default if i==0 else str(uuid4());layer_map[layer['id']]=identifier
                values=(layer['name'],layer['color'],int(layer['visible']),int(layer['locked']),int(layer['z_index']))
                if i==0:c.execute('UPDATE geo_layers SET name=?,color=?,visible=?,locked=?,z_index=? WHERE id=?',(*values,identifier))
                else:c.execute('INSERT INTO geo_layers VALUES(?,?,?,?,?,?,?,?)',(identifier,project_id,*values,_now()))
                c.execute('INSERT OR REPLACE INTO geo_layer_cartography VALUES(?,?,?)',(identifier,dumps(layer['style']),int(layer.get('style_revision',0))))
            for feature in features:
                props=relink(feature.get('geofathom_record',{}).get('properties',feature['properties']))
                record=_record_feature(c,project_id,feature['geometry'],str(feature.get('geofathom_record',{}).get('name') or props.get('name') or 'Restored feature')[:200],str(feature.get('geofathom_record',{}).get('source') or props.get('source') or 'Project package')[:200],props)
                feature_map[feature['id']]=record['id']
                c.execute('INSERT INTO geo_layer_members VALUES(?,?,?)',(project_id,record['id'],layer_map[feature['layer_id']]))
            for r in revisions:
                c.execute('INSERT INTO geo_feature_revisions VALUES(?,?,?,?,?,?,?)',(feature_map[r['feature_id']],r['revision'],r['name'],r['geometry'],dumps(relink(json.loads(r['properties']))),r['source'],r['created_at']))
            c.execute('INSERT OR REPLACE INTO project_crs VALUES(?,?,?,?)',(project_id,epsg,int(data.get('crs',{}).get('grid_visible',0)),int(data.get('crs',{}).get('revision',0))))
            c.execute('UPDATE projects SET description=?,updated_at=? WHERE id=?',(str(data['project'].get('description',''))[:1000],_now(),project_id))
        return {'created':len(features),'layers':len(layers),'rasters':staged,'schema':'geofathom.project.v1'}
    except Exception as error:
        for identifier in stored:
            path=image_file(identifier);path.unlink(missing_ok=True);path.with_suffix('.json').unlink(missing_ok=True)
        if isinstance(error,(KeyError,TypeError,IndexError,AttributeError,zipfile.BadZipFile,json.JSONDecodeError)):raise VectorIOError('Malformed project package.') from error
        raise
