import csv
import json
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from simasset_review.api import create_app
from simasset_review.bundle import FIELDS, PROBE_FIELDS, PROBE_PROFILE
from simasset_review.db import import_bundle, get_run, list_runs
from conftest import edit_csv, edit_meta


@pytest.fixture
def probe(bundle):
    edit_meta(bundle/'meta.json', lambda m: m.update(
        run_id='probe-cube-file-decomposed-s0', test='probe', condition='decomposed'))
    with (bundle/'summary.csv').open('w', newline='') as f:
        writer = csv.writer(f); writer.writerow(FIELDS)
        for name, value, unit in [('probe_pass', 0, 'bool'), ('probe_depth', 0, 'mm'),
                                  ('probe_floor_gap', 87, 'mm'), ('probe_depth_ratio', 0, '%')]:
            writer.writerow(['probe-cube-file-decomposed-s0', 'cube', 'a'*64, 'probe',
                             'file', 'decomposed', 0, 'ok', name, value, unit])
    with (bundle/'timeseries_probe.csv').open('w', newline='') as f:
        writer = csv.writer(f); writer.writerow(PROBE_FIELDS)
        writer.writerow([0]+['']*9)
        writer.writerow([.002, 0, 0, 110, 0, 0, 110, -10, 1, 20])
        writer.writerow([.004, 0, 0, 100, 0, 0, 100, 0, 1, 0])
    return bundle


def test_probe_units_no_automatic_human_verdict_and_blank_prefix(database, probe, namespace):
    result = import_bundle(database, probe, namespace, 'fixture')
    assert result['status'] == 'imported'
    detail = get_run(database, UUID(result['run_id']))
    assert detail['protocol_version'] == PROBE_PROFILE
    assert detail['source_status'] == 'ok' and detail['execution_status'] == 'completed'
    assert detail['judgments'] == []  # probe_pass=0 is a measurement, not a human fail.
    assert next(r for r in list_runs(database) if str(r['run_id']) == result['run_id'])['condition'] == 'decomposed'
    metrics = {x['metric_name']: x for x in detail['metrics']}
    assert metrics['probe_floor_gap']['metric_value'] == pytest.approx(.087)
    assert metrics['probe_floor_gap']['raw_value'] == '87'
    with TestClient(create_app(database)) as client:
        series = client.get('/api/runs/'+result['run_id']+'/series?channel=probe').json()
        assert len(series['points']) == 3
        assert series['points'][0]['depth_mm'] is None
        assert series['points'][1]['depth_mm'] == -10
        assert series['units']['depth_mm'] == 'mm'
        assert client.get('/api/runs/'+result['run_id']+'/series?channel=other').status_code == 422


def modify_series(path, fn):
    with path.open(newline='') as f: rows = list(csv.DictReader(f))
    fn(rows)
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=PROBE_FIELDS); w.writeheader(); w.writerows(rows)


@pytest.mark.parametrize('edit,code', [
    (lambda p: (p/'timeseries_probe.csv').unlink(), 'missing_file'),
    (lambda p: modify_series(p/'timeseries_probe.csv', lambda r: r.pop()), 'probe_alignment'),
    (lambda p: modify_series(p/'timeseries_probe.csv', lambda r: r[1].update(t='.003')), 'probe_alignment'),
    (lambda p: modify_series(p/'timeseries_probe.csv', lambda r: r[1].update(inside_opening='2')), 'probe_observation'),
    (lambda p: modify_series(p/'timeseries_probe.csv', lambda r: r[1].update(ball_speed_mm_s='-1')), 'probe_observation'),
    (lambda p: modify_series(p/'timeseries_probe.csv', lambda r: r[2].update(depth_mm='')), 'probe_observation'),
    (lambda p: edit_csv(p/'summary.csv', lambda r: r[2].update(unit='cm')), 'metric_or_unit'),
    (lambda p: edit_csv(p/'summary.csv', lambda r: [x.update(asset_sha256='') for x in r]), 'asset_hash'),
])
def test_probe_rejects_inconsistent_output(database, probe, namespace, edit, code):
    edit(probe)
    result = import_bundle(database, probe, namespace, 'fixture')
    assert result['status'] == 'invalid' and result['code'] == code


@pytest.mark.parametrize('status', ['not_applicable', 'missing_inertial', 'error'])
def test_probe_without_hash_preserves_unknown_version(database, probe, namespace, status):
    (probe/'timeseries.csv').unlink(); (probe/'timeseries_probe.csv').unlink()
    edit_csv(probe/'summary.csv', lambda rows: [r.update(asset_sha256='', status=status) for r in rows])
    first = import_bundle(database, probe, namespace, 'fixture')
    assert first['status'] == 'imported'
    detail = get_run(database, UUID(first['run_id']))
    assert detail['asset_version'] is None
    assert any('미기록' in warning for warning in detail['warnings'])
    assert detail['judgments'] == []
    assert detail['execution_status'] == ('skipped' if status == 'not_applicable' else 'error')
    assert any(str(row['run_id']) == first['run_id'] for row in list_runs(database, version='__missing__'))
    assert import_bundle(database, probe, namespace, 'fixture')['status'] == 'duplicate'
    edit_csv(probe/'summary.csv', lambda rows: [r.update(run_id='second') for r in rows])
    edit_meta(probe/'meta.json', lambda m: m.update(run_id='second'))
    second = import_bundle(database, probe, namespace, 'fixture')
    with database.connect() as conn:
        assert conn.execute('''SELECT count(DISTINCT variant_id) n FROM test_runs
          JOIN test_cases USING(case_id) WHERE source_namespace=%s''', (namespace,)).fetchone()['n'] == 2
    assert second['status'] == 'imported'


@pytest.mark.parametrize('removed', [None, 'timeseries_probe.csv', 'timeseries.csv'])
def test_skipped_probe_rejects_stale_trajectory(database, probe, namespace, removed):
    if removed:
        (probe/removed).unlink()
    edit_csv(probe/'summary.csv', lambda rows: [r.update(status='not_applicable') for r in rows])
    result = import_bundle(database, probe, namespace, 'fixture')
    assert result['status'] == 'invalid' and result['code'] == 'unexpected_trajectory'
