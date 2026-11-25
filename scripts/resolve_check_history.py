"""One-time, owner-authorized failed-run cleanup after current acceptance passes.

Only the immutable plan's run IDs and SHAs may be removed. Source commits,
passing runs, branch refs and future failures are never rewritten or deleted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
import urllib.request

PLAN=Path(__file__).resolve().parents[1]/'docs/resolved-check-history-plan.json'
ADVERSE={'failure','timed_out','action_required','startup_failure','stale'}


def api(repo,path,method='GET'):
    if repo!='hwspen7/GeoFathom':raise ValueError('Unexpected cleanup repository.')
    token=os.environ.get('GH_TOKEN')
    if not token:raise ValueError('An explicitly scoped Actions token is required.')
    url='https://api.github.com/repos/'+repo+'/'+path
    request=urllib.request.Request(url,method=method,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(request,timeout=30) as response:
        remaining=int(response.headers.get('X-RateLimit-Remaining','0'))
        return (json.load(response) if method=='GET' else None),remaining


def readiness(plan,fetch=api):
    repo=plan['repository'];branch=plan['branch']
    if plan.get('schema')!='geofathom-resolved-check-history-1' or repo!='hwspen7/GeoFathom' or branch!='main':raise ValueError('Invalid fixed cleanup plan.')
    head,_=fetch(repo,'branches/'+branch);sha=head['commit']['sha']
    commit,_=fetch(repo,'commits/'+sha)
    if [p['sha'] for p in commit['parents']]!=[plan['repair_parent_sha']]:return None,'Inactive: main moved beyond the one-time repair commit.'
    source=Path(__file__).resolve().parents[1]/'imagery/raster.py'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=plan['repair_source_sha256']:raise ValueError('Repair source differs from the approved plan.')
    data,_=fetch(repo,'actions/runs?branch=main&event=push&head_sha='+sha+'&per_page=100')
    found={}
    for run in data['workflow_runs']:
        if run['name'] not in found:found[run['name']]=run
    for name in plan['required_workflows']:
        run=found.get(name)
        if not run or run['status']!='completed' or run['conclusion']!='success':return None,'Deferred until the current main workflow passes: '+name
    return sha,'All required main workflows passed.'


def eligible(plan,fetch=api):
    selected={t['id']:t for t in plan['targets']}
    if len(selected)!=len(plan['targets']):raise ValueError('Duplicate cleanup target.')
    result=[];remaining=0
    # Read a fresh list before deletion; do not rely on stale status snapshots.
    for status in ('failure','timed_out','action_required','startup_failure','stale','cancelled'):
        for page in range(1,100):
            data,remaining=fetch(plan['repository'],f'actions/runs?status={status}&per_page=100&page={page}')
            for run in data['workflow_runs']:
                target=selected.get(run['id'])
                if not target:continue
                if run['head_sha']!=target['head_sha'] or run['head_branch']!=target['branch'] or run['name']!=target['name']:
                    raise ValueError('Historical run identity changed: '+str(run['id']))
                # A cancelled run can contain an actual failed job; only the
                # explicitly observed failing Checks run has that exception.
                if run['conclusion'] in ADVERSE or run['id']==45548031609 and run['conclusion']=='cancelled':result.append(run)
            if len(data['workflow_runs'])<100:break
        else:raise ValueError('Historical run pagination exceeded its bound.')
    unique={r['id']:r for r in result}
    return [unique[uid] for uid in sorted(unique,reverse=True)],remaining


def prepare(plan,directory,fetch=api,download_logs=True):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    sha,reason=readiness(plan,fetch)
    if not sha:return {'ready':False,'reason':reason}
    runs,remaining=eligible(plan,fetch)
    if not runs:return {'ready':False,'reason':'The fixed historical targets have already been resolved.'}
    # Keep enough quota for all deletes, a final verification, and head guards.
    if remaining<len(runs)+100:return {'ready':False,'reason':'Cleanup deferred: insufficient API quota for the complete fixed batch.'}
    logs=[]
    for run in runs:
        if not download_logs or run['id'] not in plan['archive_log_runs']:continue
        path=directory/('run-'+str(run['id'])+'-logs.zip')
        with path.open('wb') as output:
            result=subprocess.run(['gh','api',f"/repos/{plan['repository']}/actions/runs/{run['id']}/logs"],stdout=output,stderr=subprocess.PIPE,check=False)
        if result.returncode:
            path.unlink(missing_ok=True);logs.append({'run_id':run['id'],'state':'unavailable','reason':result.stderr.decode(errors='replace')[:1000]})
        else:logs.append({'run_id':run['id'],'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    record={'schema':plan['schema'],'repository':plan['repository'],'verified_head_sha':sha,
        'plan_sha256':hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest(),'required_workflows':plan['required_workflows'],
        'historical_runs':runs,'logs':logs,'meaning':'Historical runs failed. Current green execution supersedes them; no historical result is relabeled as passing.'}
    (directory/'evidence.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    return {'ready':True,'reason':reason,'targets':len(runs),'head_sha':sha}


def remove(plan,directory,fetch=api,interval=1.):
    directory=Path(directory);record=json.loads((directory/'evidence.json').read_text())
    if os.environ.get('GEOFATHOM_ARCHIVE_UPLOADED')!='1':raise ValueError('Archive upload must succeed before historical deletion.')
    if record['plan_sha256']!=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest():raise ValueError('Cleanup plan changed after archival.')
    sha,reason=readiness(plan,fetch)
    if sha!=record['verified_head_sha']:raise ValueError('Current acceptance changed after archival: '+reason)
    live,_=eligible(plan,fetch);still_failed={r['id'] for r in live}
    allowed={t['id']:t for t in plan['targets']};removed=[]
    for index,run in enumerate(record['historical_runs']):
        target=allowed.get(run['id'])
        if not target or target['head_sha']!=run['head_sha'] or run['conclusion'] not in ADVERSE|{'cancelled'}:raise ValueError('Unapproved historical deletion target.')
        if run['id'] not in still_failed:continue
        if index%25==0:
            current,_=fetch(plan['repository'],'branches/main')
            if current['commit']['sha']!=sha:raise ValueError('Main moved during cleanup; remaining runs preserved.')
        try:fetch(plan['repository'],'actions/runs/'+str(run['id']),'DELETE')
        except HTTPError as e:
            if e.code!=404:raise
        removed.append(run['id'])
        if len(removed)%25==0:print('Archived historical failures removed:',len(removed),flush=True)
        if interval:time.sleep(interval)
    result={'verified_head_sha':sha,'removed_failed_run_ids':removed,'count':len(removed)}
    (directory/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',choices=['prepare','delete']);parser.add_argument('--plan',type=Path,default=PLAN);parser.add_argument('--directory',type=Path,default=Path('resolved-check-evidence'));args=parser.parse_args()
    plan=json.loads(args.plan.read_text());result=prepare(plan,args.directory) if args.stage=='prepare' else remove(plan,args.directory)
    if args.stage=='prepare' and os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as out:out.write('ready='+str(result['ready']).lower()+'\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
