from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import shutil
import unicodedata
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from simasset_review.api import create_app
from simasset_review.db import import_bundle, get_run, list_runs, Settings
from conftest import edit_csv, edit_meta


def test_actual_postgres_import_units_and_duplicate(database,bundle,namespace):
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in bundle.iterdir()}
    result=import_bundle(database,bundle,namespace,'fixture')
    assert result['status']=='imported'
    detail=get_run(database,UUID(result['run_id']))
    metrics={m['metric_name']:m for m in detail['metrics']}
    assert metrics['peak_pen']['metric_value']==pytest.approx(.00125)
    assert metrics['peak_pen']['unit']=='m' and metrics['peak_pen']['raw_value']=='1.25'
    assert metrics['theta_tip_pred_deg']['metric_value']==pytest.approx(math.pi/4)
    assert metrics['accel_err_pct']['metric_value'] is None
    assert metrics['accel_err_pct']['valid'] is False
    assert metrics['motion_mode']['metric_text']=='sliding'
    assert detail['raw_meta']['perturb']['tilt_deg']==.3
    assert 'perturb' not in detail['config']
    assert import_bundle(database,bundle,namespace,'fixture')['status']=='duplicate'
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in bundle.iterdir()}


def test_conflicting_id_never_overwrites(database,bundle,namespace):
    first=import_bundle(database,bundle,namespace,'fixture')
    edit_csv(bundle/'summary.csv',lambda rows: rows[1].update(value='99'))
    second=import_bundle(database,bundle,namespace,'fixture')
    assert second['status']=='conflict'
    assert second['existing_bundle']!=second['incoming_bundle']
    assert (database.state/'objects'/second['incoming_bundle']/'summary.csv').exists()
    saved=get_run(database,UUID(first['run_id']))
    assert next(m for m in saved['metrics'] if m['metric_name']=='peak_pen')['raw_value']=='1.25'


def test_parallel_import_is_idempotent(database,bundle,namespace):
    with ThreadPoolExecutor(max_workers=4) as pool:
        result=list(pool.map(lambda _:import_bundle(database,bundle,namespace,'fixture'),range(4)))
    assert sorted(x['status'] for x in result)==['duplicate']*3+['imported']
    assert len({x['run_id'] for x in result})==1


@pytest.mark.parametrize('change,code',[
    (lambda p:(p/'meta.json').unlink(),'missing_file'),
    (lambda p:(p/'timeseries.csv').unlink(),'missing_file'),
    (lambda p:edit_csv(p/'summary.csv',lambda rows:rows[1].update(unit='cm')),'metric_or_unit'),
    (lambda p:edit_csv(p/'summary.csv',lambda rows:rows[1].update(value='inf')),'invalid_number'),
    (lambda p:edit_csv(p/'summary.csv',lambda rows:rows[1].update(run_id='other')),'mixed_run'),
    (lambda p:edit_csv(p/'summary.csv',lambda rows:rows.append(rows[0])),'duplicate_metric'),
    (lambda p:edit_csv(p/'summary.csv',lambda rows:[r.update(status='maybe') for r in rows]),'identity_or_status'),
    (lambda p:edit_csv(p/'summary.csv',lambda rows:rows[-1].update(value='2')),'invalid_boolean'),
    (lambda p:edit_meta(p/'meta.json',lambda m:m.update(seed=3)),'metadata_mismatch'),
    (lambda p:edit_meta(p/'meta.json',lambda m:m.update(timeseries_units={})),'timeseries_units'),
    (lambda p:(p/'meta.json').write_text('{"a":NaN}'),'invalid_json'),
    (lambda p:(p/'linked.txt').symlink_to(p/'meta.json'),'symlink'),
])
def test_rejects_incomplete_or_ambiguous_inputs(database,bundle,namespace,change,code):
    change(bundle)
    result=import_bundle(database,bundle,namespace,'fixture')
    assert result['status']=='invalid' and result['code']==code
    with database.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM test_runs WHERE source_namespace=%s',(namespace,)).fetchone()['n']==0
        assert conn.execute('SELECT status FROM import_attempts WHERE source_namespace=%s',(namespace,)).fetchone()['status']=='invalid'


@pytest.mark.parametrize('status',['missing_inertial','missing_inertia','error','not_applicable'])
def test_expected_no_trajectory_statuses(database,bundle,namespace,status):
    (bundle/'timeseries.csv').unlink()
    edit_csv(bundle/'summary.csv',lambda rows:[r.update(status=status) for r in rows])
    result=import_bundle(database,bundle,namespace,'fixture')
    assert result['status']=='imported'
    detail=get_run(database,UUID(result['run_id']))
    assert detail['source_status']==status and detail['execution_status'] in ('skipped','error')


def test_source_namespace_and_version_separation(database,bundle,namespace):
    first=import_bundle(database,bundle,namespace,'fixture')
    other=import_bundle(database,bundle,namespace+'-other','fixture')
    assert other['run_id']!=first['run_id']
    edit_csv(bundle/'summary.csv',lambda rows:[r.update(run_id='new-run',asset_sha256='b'*64) for r in rows])
    edit_meta(bundle/'meta.json',lambda m:m.update(run_id='new-run'))
    next_run=import_bundle(database,bundle,namespace,'fixture')
    assert next_run['status']=='imported'
    assert get_run(database,UUID(next_run['run_id']))['asset_version']=='b'*64


def test_new_names_are_nfc(database,bundle,namespace):
    (bundle/unicodedata.normalize('NFD','관찰.txt')).write_text('원본 이름을 보존한 사본')
    result=import_bundle(database,bundle,namespace,'fixture')
    detail=get_run(database,UUID(result['run_id']))
    assert all(unicodedata.is_normalized('NFC',f['filename']) for f in detail['artifacts'])


def test_append_only_judgment_and_stale_write(database,bundle,namespace):
    result=import_bundle(database,bundle,namespace,'fixture'); rid=result['run_id']
    with TestClient(create_app(database)) as client:
        detail=client.get('/api/runs/'+rid).json()
        payload={'outcome':'inconclusive','reviewer':'테스트 검토자','criterion_key':'penetration',
                 'protocol_version':'draft-1','rationale':'짧은 관입 봉우리를 확인합니다.',
                 'evidence_ids':[detail['artifacts'][0]['artifact_id']]}
        first=client.post(f'/api/runs/{rid}/judgments',json=payload)
        assert first.status_code==201
        assert client.post(f'/api/runs/{rid}/judgments',json=payload).status_code==409
        payload.update(outcome='fail',rationale='그래프와 원본 값을 확인했습니다.',
                       supersedes_judgment_id=first.json()['judgment_id'])
        assert client.post(f'/api/runs/{rid}/judgments',json=payload).status_code==201
        history=client.get('/api/runs/'+rid).json()['judgments']
        assert len(history)==2 and sum(x['current'] for x in history)==1
        assert {x['outcome'] for x in history}=={'fail','inconclusive'}
        payload.update(evidence_ids=[str(uuid4())],supersedes_judgment_id=history[0]['judgment_id'])
        assert client.post(f'/api/runs/{rid}/judgments',json=payload).status_code==409
        assert client.post(f'/api/runs/{rid}/judgments',json=payload,headers={'origin':'https://example.org'}).status_code==403
        payload['reviewer']=' '
        assert client.post(f'/api/runs/{rid}/judgments',json=payload).status_code==422
    with database.connect() as conn:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute('UPDATE run_judgments SET rationale=%s WHERE run_id=%s',('overwrite',rid))


def test_artifact_integrity_and_series(database,bundle,namespace):
    result=import_bundle(database,bundle,namespace,'fixture');rid=result['run_id']
    with TestClient(create_app(database)) as client:
        series=client.get(f'/api/runs/{rid}/series').json()
        assert max(p['max_pen'] for p in series['points'])==1.25
        assert series['units']['max_pen']=='mm'
        detail=client.get('/api/runs/'+rid).json()
        artifact=next(a for a in detail['artifacts'] if a['filename']=='timeseries.csv')
        assert client.get('/api/artifacts/'+artifact['artifact_id']).status_code==200
        # This fixture snapshot belongs to the temporary test DB, never production data.
        snapshot=database.state/'objects'/detail['bundle_sha256']/'timeseries.csv'
        snapshot.write_text('tampered')
        assert client.get('/api/artifacts/'+artifact['artifact_id']).status_code==409
        assert client.get('/api/runs/'+str(uuid4())).status_code==404


def test_database_scope_guard(monkeypatch,tmp_path):
    monkeypatch.setenv('SIMASSET_STATE_DIR',str(tmp_path))
    for dsn in ('postgresql://u@production.example/simasset_review', 'postgresql://u@127.0.0.1/team'):
        monkeypatch.setenv('SIMASSET_DATABASE_URL',dsn)
        with pytest.raises(RuntimeError): Settings.load()


def test_run_list_paginates_without_losing_or_repeating_results(database,bundle,namespace):
    asset='paged-'+namespace
    edit_csv(bundle/'summary.csv',lambda rows:[r.update(asset_id=asset) for r in rows])
    first=import_bundle(database,bundle,namespace,'fixture')
    # Populate only the disposable test DB; identical sort timestamps exercise the UUID tie-break.
    with database.connect() as conn:
        conn.execute('''INSERT INTO test_runs
          (run_id,case_id,source_namespace,source_run_id,bundle_sha256,origin,seed,
           simulator,engine_version,execution_status,source_status,raw_meta,source_manifest,warnings,imported_at)
          SELECT gen_random_uuid(),case_id,source_namespace,source_run_id||'-'||n,
           bundle_sha256,origin,seed,simulator,engine_version,execution_status,source_status,
           raw_meta,source_manifest,warnings,imported_at
          FROM test_runs CROSS JOIN generate_series(1,1004) AS n WHERE run_id=%s''',
          (first['run_id'],))
    with TestClient(create_app(database)) as client:
        one=client.get('/api/runs',params={'asset':asset}).json()
        two=client.get('/api/runs',params={'asset':asset,'offset':1000}).json()
        assert len(one)==1000 and len(two)==5
        assert len({row['run_id'] for row in one+two})==1005
        assert client.get('/api/runs',params={'asset':asset,'offset':2000}).json()==[]
        assert client.get('/api/runs?offset=-1').status_code==422
