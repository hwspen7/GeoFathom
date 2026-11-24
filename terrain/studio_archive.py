"""Self-contained research figure archives; original data and render are hashed."""
import csv,hashlib,io,json,zipfile

def digest(data):return hashlib.sha256(data).hexdigest()

def build_archive(payload,format,input_record,metadata,table,provenance):
    def j(value):return json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,indent=2).encode('utf-8')
    entries={'figure.'+format:payload,'reproduction.json':j({'schema':'geofathom-studio-reproduction-1','input':input_record,'provenance':provenance}),
             'metadata.json':j(metadata)}
    def csv_bytes(rows):
        s=io.StringIO(newline='');csv.writer(s).writerows(rows);return s.getvalue().encode('utf-8')
    if table:entries['figure-data.csv']=csv_bytes(table)
    for i,p in enumerate(metadata.get('panels',[])):
        if p.get('table'):entries[f'panel-{i+1}-data.csv']=csv_bytes(p['table'])
    manifest={'schema':'geofathom-figure-archive-1','format':format,'files':{name:{'sha256':digest(value),'bytes':len(value)} for name,value in entries.items()},
              'note':'Hashes verify packaged bytes, not independent scientific validity. Source CSV/GeoTIFF bytes and settings are embedded in reproduction.json.'}
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=4) as z:
        for name,value in entries.items():z.writestr(name,value)
        z.writestr('manifest.json',j(manifest))
    return buf.getvalue(),manifest
