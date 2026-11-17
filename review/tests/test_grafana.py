"""Exercise the shipped dashboard queries against real PostgreSQL fixtures."""
import json
from pathlib import Path

from conftest import edit_csv
from simasset_review.db import import_bundle


def test_dashboard_counts_runs_and_keeps_versions_and_errors_separate(database,bundle,namespace):
    dashboard=json.loads((Path(__file__).parents[1]/'grafana/dashboard.json').read_text())
    queries={p['id']:p['targets'][0]['rawSql'] for p in dashboard['panels']}
    asset='grafana-'+namespace
    edit_csv(bundle/'summary.csv',lambda rows:[r.update(asset_id=asset) for r in rows])
    with database.connect() as conn:
        before=sum(row['runs'] for row in conn.execute(queries[1]).fetchall())
    for suffix in ('one','two'):
        assert import_bundle(database,bundle,namespace+'-'+suffix,'fixture')['status']=='imported'
    edit_csv(bundle/'summary.csv',lambda rows:[r.update(asset_sha256='b'*64) for r in rows])
    assert import_bundle(database,bundle,namespace+'-three','fixture')['status']=='imported'
    edit_csv(bundle/'summary.csv',lambda rows:[r.update(status='missing_inertial') for r in rows])
    (bundle/'timeseries.csv').unlink()
    assert import_bundle(database,bundle,namespace+'-four','fixture')['status']=='imported'
    with database.connect() as conn:
        after=sum(row['runs'] for row in conn.execute(queries[1]).fetchall())
        coverage=[row for row in conn.execute(queries[3]).fetchall() if row['asset']==asset]
    # Four runs with several metrics each must still count as four executions.
    assert after-before==4
    groups={(row['asset_version'],row['execution_status']):(row['runs'],row['batches']) for row in coverage}
    assert groups=={('a'*64,'completed'):(2,2),('b'*64,'completed'):(1,1),('b'*64,'error'):(1,1)}
