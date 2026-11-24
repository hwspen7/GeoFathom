"""Project-scoped dataset staging, atomic imports and scoped export snapshots."""
import hashlib
import json
import shutil
import time
from pathlib import Path
from uuid import UUID,uuid4

from shapely.geometry import shape,box
from shapely.ops import unary_union
from geometry.measure import measure_geometry
from .database import _connect,_required_project,_record_feature,_now,database_path,StorageError
from .workspace import _schema,_default,_layer
from .vectorio import MAX_FEATURES,MAX_BYTES,VectorIOError,read_vector,inspect_vector,field_schema,dumps,write_vector,export_warnings,prepare_vector

def stage_root(project_id):
    return database_path().parent/'exchange'/hashlib.sha256(project_id.encode()).hexdigest()

def cleanup_exchange(project_id):
    """Expire abandoned uploads after one day and downloads after seven days."""
    root=stage_root(project_id)
    if not root.exists():return
    active=set()
    with _connect() as c:
        exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gis_jobs'").fetchone()
        if exists:
            for row in c.execute("SELECT payload FROM gis_jobs WHERE project_id=? AND kind='vector_import' AND status IN ('queued','running')",(project_id,)):
                active.add(json.loads(row['payload']).get('upload_id'))
    now=time.time()
    for path in root.iterdir():
        if path.is_dir() and path.name!='artifacts' and path.name not in active and now-path.stat().st_mtime>86400:shutil.rmtree(path,ignore_errors=True)
    artifacts=root/'artifacts'
    if artifacts.exists():
        for path in artifacts.iterdir():
            if now-path.stat().st_mtime>7*86400:path.unlink(missing_ok=True)

def exchange_size(project_id):
    root=stage_root(project_id)
    return sum(path.stat().st_size for path in root.rglob('*') if path.is_file()) if root.exists() else 0

def stage_path(project_id,identifier):
    try:
        if str(UUID(identifier))!=identifier:raise ValueError()
    except (ValueError,TypeError) as exc:raise VectorIOError('Invalid upload identifier.') from exc
    return stage_root(project_id)/identifier

def discard_stage(project_id,identifier):
    shutil.rmtree(stage_path(project_id,identifier),ignore_errors=True)

def staged_manifest(project_id,identifier):
    with _connect() as c:_required_project(c,project_id)
    path=stage_path(project_id,identifier)
    if not (path/'manifest.json').is_file():raise VectorIOError('Uploaded batch is missing or expired; inspect the files again.')
    return path,json.loads((path/'manifest.json').read_text('utf-8'))

def inspect_staged(project_id,identifier):
    path,manifest=staged_manifest(project_id,identifier)
    result=[]
    for file in manifest['files']:
        try:
            preview=inspect_vector(file['name'],(path/file['id']).read_bytes(),file.get('options'))
            result.append({**file,**preview})
        except Exception as exc:result.append({**file,'layers':[],'error':str(exc)})
    return {'upload_id':identifier,'files':result,'limits':{'file_bytes':MAX_BYTES,'features':MAX_FEATURES,'files':20}}

def commit_import(project_id,plans,target_layer=None,separate_layers=True,cancelled=None,finalize=None):
    """Every file/layer in a batch is committed in one transaction or rolled back."""
    total=sum(len(p['features']) for p in plans)
    if not 1<=total<=MAX_FEATURES:raise VectorIOError('Import requires 1–100,000 valid features per batch.')
    with _connect() as c:
        _schema(c);c.execute('BEGIN IMMEDIATE');_required_project(c,project_id)
        default=_default(c,project_id)
        if (target_layer or not separate_layers) and _layer(c,project_id,target_layer or default)['locked']:raise StorageError('The target layer is locked.')
        assignments={};created=[];counts=[];vertices=0
        for plan in plans:
            file_count=0
            for item in plan['features']:
                if len(created)%256==0 or len(created)==total-1:
                    if cancelled:cancelled()
                    from jobs.queue import _ACTIVE_JOB,_ACTIVE_OWNER
                    uid=_ACTIVE_JOB.get()
                    if uid:
                        import time
                        from jobs.leases import LEASE_SECONDS
                        c.execute('UPDATE gis_jobs SET lease_expires=? WHERE id=? AND lease_owner=?',(time.time()+LEASE_SECONDS,uid,_ACTIVE_OWNER.get()))
                        c.execute('UPDATE gis_job_slots SET expires=? WHERE owner=?',(time.time()+LEASE_SECONDS,_ACTIVE_OWNER.get()))
                key=(plan.get('file_id',plan['name']),item.get('source_layer','Imported'))
                if target_layer:layer=target_layer
                elif not separate_layers:layer=default
                else:
                    if key not in assignments:
                        if c.execute('SELECT count(*) FROM geo_layers WHERE project_id=?',(project_id,)).fetchone()[0]>=100:raise StorageError('A project supports at most 100 layers.')
                        layer=str(uuid4());assignments[key]=layer
                        name=(Path(plan['name']).stem+' · '+str(key[1]))[:100]
                        c.execute('INSERT INTO geo_layers VALUES(?,?,?,?,?,?,?,?)',(layer,project_id,name,'#2563eb',1,0,c.execute('SELECT COALESCE(MAX(z_index),0)+1 FROM geo_layers WHERE project_id=?',(project_id,)).fetchone()[0],_now()))
                    layer=assignments[key]
                record=_record_feature(c,project_id,item['geometry'],item['name'],item['source'],item['properties'])
                vertices+=record['measurement']['coordinate_count']
                if vertices>4_000_000:raise VectorIOError('Batch exceeds four million vertices.')
                c.execute('INSERT INTO geo_layer_members VALUES(?,?,?)',(project_id,record['id'],layer))
                created.append(record['id']);file_count+=1
            counts.append({'name':plan['name'],'created':file_count,'rejected':plan.get('rejected',len(plan.get('errors',[]))),
                'errors':plan.get('errors',[]),'schema':plan.get('schema',[])})
        if cancelled:cancelled()
        c.execute('UPDATE projects SET updated_at=? WHERE id=?',(_now(),project_id))
        result={'created':len(created),'layer_ids':list(assignments.values()),'files':counts,'committed':True,
                'feature_ids':created[:200],'rejected':sum(v['rejected'] for v in counts)}
        if finalize:result=finalize(result,c)
    return result

def execute_import(project_id,payload,progress,cancelled):
    identifier=payload['upload_id'];path,manifest=staged_manifest(project_id,identifier)
    try:
        selections={f['id']:f for f in payload.get('files',[])}
        if set(selections)-{f['id'] for f in manifest['files']}:raise VectorIOError('Selected file is not part of this upload.')
        plans=[];files=[f for f in manifest['files'] if not selections or f['id'] in selections]
        for index,file in enumerate(files):
            cancelled();options=selections.get(file['id'],{}).get('options',{})
            parsed=read_vector(file['name'],(path/file['id']).read_bytes(),options,
                progress=lambda fraction:progress((index+fraction)/len(files)*.85))
            plans.append({**parsed,'name':file['name'],'file_id':file['id']})
        progress(.9)
        def finalize(result,c):
            report=put_artifact(project_id,dumps(result).encode(),'geofathom-import-report.json','application/json',cleanup=False)
            outcome={**result,'report_id':report,'files':[{k:v for k,v in f.items() if k not in {'errors','schema'}} for f in result['files']]}
            from jobs.queue import _ACTIVE_JOB,_ACTIVE_OWNER
            uid=_ACTIVE_JOB.get()
            if uid:
                serialized=dumps(outcome)
                c.execute('INSERT OR REPLACE INTO gis_job_results VALUES(?,?,?)',(uid,serialized,len(serialized.encode())))
                updated=c.execute("""UPDATE gis_jobs SET status='completed',progress=100,result=NULL,
                    lease_owner=NULL,lease_expires=NULL,updated_at=? WHERE id=? AND lease_owner=? AND status='running'""",(_now(),uid,_ACTIVE_OWNER.get()))
                if updated.rowcount!=1:raise StorageError('Import worker lost its lease before commit.')
                from jobs.leases import release_slot
                release_slot(c,_ACTIVE_OWNER.get())
            return outcome
        return commit_import(project_id,plans,payload.get('layer_id'),payload.get('separate_layers',True),cancelled,finalize)
    finally:discard_stage(project_id,identifier)

def snapshot(project_id,layer_ids=None,feature_ids=None,viewport=None,include_history=False):
    """Read the entire chosen dataset, not the workspace's 200-row UI page."""
    wanted_layers=set(layer_ids or []);wanted_features=set(feature_ids or [])
    with _connect() as c:
        _schema(c)
        from .cartography import _ensure_table,default_style
        _ensure_table(c)
        c.execute('BEGIN');project=dict(_required_project(c,project_id))
        default=_default(c,project_id)
        layers=[dict(r) for r in c.execute('SELECT * FROM geo_layers WHERE project_id=? ORDER BY z_index,id',(project_id,))]
        if wanted_layers-{l['id'] for l in layers}:raise VectorIOError('Selected layer does not belong to the project.')
        rows=c.execute('SELECT f.*,COALESCE(m.layer_id,?) AS layer_id FROM features f LEFT JOIN geo_layer_members m ON m.feature_id=f.id WHERE f.project_id=? ORDER BY f.created_at,f.id',(default,project_id))
        features=[];found=set();layer_names={l['id']:l['name'] for l in layers}
        area=None
        if viewport:
            if len(viewport)!=4 or not(-180<=viewport[0]<=180 and -180<=viewport[2]<=180 and -90<=viewport[1]<viewport[3]<=90):raise VectorIOError('Invalid geographic export extent.')
            w,s,e,n=viewport;area=box(w,s,e,n) if w<e else unary_union([box(w,s,180,n),box(-180,s,e,n)])
        for row in rows:
            if wanted_layers and row['layer_id'] not in wanted_layers:continue
            if wanted_features and row['id'] not in wanted_features:continue
            found.add(row['id']);geom=json.loads(row['geometry'])
            if area is not None and not shape(geom).intersects(area):continue
            props=json.loads(row['properties']);props.setdefault('name',row['name']);props.setdefault('source',row['source'])
            features.append({'type':'Feature','id':row['id'],'geometry':geom,'properties':props,
                'geofathom_layer':layer_names[row['layer_id']],'layer_id':row['layer_id'],
                'geofathom_record':{'name':row['name'],'source':row['source'],'properties':json.loads(row['properties'])}})
            if len(features)>MAX_FEATURES:raise VectorIOError('Export exceeds 100,000 features; select fewer layers.')
        if wanted_features-found:raise VectorIOError('Selected feature does not belong to the requested project/layers.')
        for layer in layers:
            style=c.execute('SELECT settings,revision FROM geo_layer_cartography WHERE layer_id=?',(layer['id'],)).fetchone()
            layer['style']=json.loads(style['settings']) if style else default_style()
            layer['style_revision']=style['revision'] if style else 0
        from .crs import _table
        _table(c)
        crs_row=c.execute('SELECT * FROM project_crs WHERE project_id=?',(project_id,)).fetchone()
        crs=dict(crs_row) if crs_row else {'epsg':'EPSG:4326','grid_visible':0,'revision':0}
        revisions=[dict(r) for r in c.execute('SELECT r.* FROM geo_feature_revisions r JOIN features f ON f.id=r.feature_id WHERE f.project_id=? LIMIT 100001',(project_id,))] if include_history else []
        if len(revisions)>100000:raise VectorIOError('Project revision history exceeds the portable package budget.')
    return {'type':'FeatureCollection','features':features,'project':project,'layers':layers,'crs':crs,'revisions':revisions}

def export_collection(project_id,options):
    inline=options.get('collection')
    if inline is not None:
        with _connect() as c:_required_project(c,project_id)
        if inline.get('type')!='FeatureCollection' or not isinstance(inline.get('features'),list):raise VectorIOError('Expected a FeatureCollection.')
        collection=inline
    else:collection=snapshot(project_id,options.get('layer_ids'),options.get('feature_ids'),options.get('viewport'))
    if not collection['features']:raise VectorIOError('The export scope is empty.')
    if options.get('include_measurements'):
        for feature in collection['features']:
            feature['properties']=dict(feature.get('properties') or {})
            for key,value in measure_geometry(feature['geometry']).items():
                if key in {'area_m2','perimeter_m','length_m','method'}:feature['properties'].setdefault('measurement_method' if key=='method' else key,value)
    return collection

def preflight(project_id,options):
    collection=export_collection(project_id,options)
    prepared=prepare_vector(collection,options.get('target_crs','EPSG:4326'),options.get('fields'),options.get('precision'))
    fields=options.get('fields')
    if fields is not None and (len(set(fields))!=len(fields) or set(fields)-{f['name'] for f in field_schema(collection['features'])}):raise VectorIOError('Requested export fields are duplicated or missing.')
    return {'count':len(collection['features']),'schema':field_schema(collection['features']),
        'geometry_types':sorted({f['geometry']['type'] for f in collection['features']}),
        'warnings':export_warnings(prepared,options['format'],options.get('target_crs','EPSG:4326')),
        'target_crs':options.get('target_crs','EPSG:4326')}

def perform_export(project_id,options):
    collection=export_collection(project_id,options)
    return write_vector(collection,options['format'],options.get('target_crs','EPSG:4326'),options.get('fields'),options.get('precision'))

def artifact_root(project_id):
    path=stage_root(project_id)/'artifacts';path.mkdir(parents=True,exist_ok=True);return path

def put_artifact(project_id,payload,name,media,cleanup=True):
    if cleanup:cleanup_exchange(project_id)
    if exchange_size(project_id)+len(payload)>2*1024**3:raise VectorIOError('Project exchange storage exceeds 2 GB; remove old downloads or uploads before continuing.')
    identifier=str(uuid4());root=artifact_root(project_id)
    if len(payload)>512*1024*1024:raise VectorIOError('Output exceeds the 512 MB delivery budget; narrow the scope.')
    (root/identifier).write_bytes(payload)
    (root/(identifier+'.json')).write_text(dumps({'name':name,'media':media,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}),'utf-8')
    return identifier

def get_artifact(project_id,identifier):
    stage_path(project_id,identifier)  # Validate the opaque ID; no client path is accepted.
    root=artifact_root(project_id);path=root/identifier
    if not path.is_file():raise VectorIOError('Output artifact was not found.')
    meta=json.loads((root/(identifier+'.json')).read_text('utf-8'))
    return path,meta

def execute_export(project_id,payload,progress,cancelled):
    cancelled();progress(.1)
    collection=export_collection(project_id,payload);progress(.25)
    binary,media,name=write_vector(collection,payload['format'],payload.get('target_crs','EPSG:4326'),payload.get('fields'),payload.get('precision'),progress=lambda f:progress(.25+.65*f))
    cancelled();identifier=put_artifact(project_id,binary,name,media)
    return {'artifact_id':identifier,'name':name,'bytes':len(binary),'count':len(collection['features']),
            'warnings':export_warnings(collection['features'],payload['format'],payload.get('target_crs','EPSG:4326'))}
