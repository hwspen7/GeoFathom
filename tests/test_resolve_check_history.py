"""One-time cleanup requires green execution, exact targets and archived evidence."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from scripts.resolve_check_history import readiness,eligible,prepare,remove


def scenario():
    source=Path(__file__).resolve().parents[1]/'imagery/raster.py'
    plan={'schema':'geofathom-resolved-check-history-1','repository':'hwspen7/GeoFathom','branch':'main',
          'repair_parent_sha':'old-head','repair_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'required_workflows':['Checks','Tagged release'],'archive_log_runs':[],
          'targets':[{'id':11,'head_sha':'failed-old','branch':'main','name':'Checks'}]}
    old={'id':11,'head_sha':'failed-old','head_branch':'main','name':'Checks','conclusion':'failure'}
    future={**old,'id':99,'head_sha':'new-future'};calls=[];state={'green':True,'head':'repaired','old_failed':True,'remaining':900}
    def fetch(repo,path,method='GET'):
        calls.append((path,method));assert repo=='hwspen7/GeoFathom'
        if method=='DELETE':assert path=='actions/runs/11';return None,state['remaining']
        if path=='branches/main':return {'commit':{'sha':state['head']}},state['remaining']
        if path.startswith('commits/'):
            return {'parents':[{'sha':'old-head' if state['head']=='repaired' else 'later-parent'}]},state['remaining']
        if 'event=push' in path:
            return {'workflow_runs':[{'name':name,'status':'completed','conclusion':'success' if state['green'] else 'failure'} for name in plan['required_workflows']]},state['remaining']
        if 'status=failure' in path:return {'workflow_runs':[future,*([old] if state['old_failed'] else [])]},state['remaining']
        return {'workflow_runs':[]},state['remaining']
    return plan,fetch,calls,state


def test_history_cleanup_requires_green_current_main(tmp_path):
    plan,fetch,calls,state=scenario();state['green']=False
    result=prepare(plan,tmp_path,fetch,download_logs=False)
    assert not result['ready'] and 'passes' in result['reason']
    assert not any(method=='DELETE' for _,method in calls)
    state['green']=True;state['head']='later'
    assert readiness(plan,fetch)[0] is None


def test_history_cleanup_archives_before_exact_allowlisted_deletion(tmp_path,monkeypatch):
    plan,fetch,calls,state=scenario();result=prepare(plan,tmp_path,fetch,download_logs=False)
    assert result['ready'] and result['targets']==1
    archive=json.loads((tmp_path/'evidence.json').read_text());assert [r['id'] for r in archive['historical_runs']]==[11]
    monkeypatch.delenv('GEOFATHOM_ARCHIVE_UPLOADED',raising=False)
    with pytest.raises(ValueError,match='Archive upload'):remove(plan,tmp_path,fetch,interval=0)
    monkeypatch.setenv('GEOFATHOM_ARCHIVE_UPLOADED','1')
    result=remove(plan,tmp_path,fetch,interval=0)
    assert result['removed_failed_run_ids']==[11] and ('actions/runs/99','DELETE') not in calls


def test_history_cleanup_rechecks_resolved_targets_and_plan_integrity(tmp_path,monkeypatch):
    plan,fetch,calls,state=scenario();prepare(plan,tmp_path,fetch,download_logs=False)
    monkeypatch.setenv('GEOFATHOM_ARCHIVE_UPLOADED','1');state['old_failed']=False
    assert remove(plan,tmp_path,fetch,interval=0)['count']==0
    modified=copy.deepcopy(plan);modified['targets'][0]['head_sha']='different'
    with pytest.raises(ValueError,match='plan changed'):remove(modified,tmp_path,fetch,interval=0)
    assert not any(method=='DELETE' for _,method in calls)


def test_history_cleanup_defers_quota_and_rejects_run_identity_changes(tmp_path):
    plan,fetch,calls,state=scenario();state['remaining']=50
    assert not prepare(plan,tmp_path,fetch,download_logs=False)['ready']
    plan['targets'][0]['head_sha']='mismatched'
    with pytest.raises(ValueError,match='identity changed'):eligible(plan,fetch)
