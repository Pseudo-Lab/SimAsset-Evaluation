"""Exercise the shipped dashboard queries against real PostgreSQL fixtures."""
import json
from pathlib import Path

from conftest import edit_csv
from simasset_review.db import import_bundle, add_judgment


def dashboard_queries():
    dashboard=json.loads((Path(__file__).parents[1]/'grafana/dashboard.json').read_text())
    def flatten(panels):
        for panel in panels:
            yield panel
            yield from flatten(panel.get('panels',[]))
    return {p['id']:p['targets'][0]['rawSql'] for p in flatten(dashboard['panels']) if p.get('targets')}


def test_dashboard_counts_runs_and_keeps_versions_and_errors_separate(database,bundle,namespace):
    queries=dashboard_queries()
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


def test_overview_counts_runs_not_metrics_or_multiple_judgments(database,bundle,namespace):
    queries=dashboard_queries()
    with database.connect() as conn:
        before={key:conn.execute(queries[key]).fetchone() for key in (10,11,12,13)}
    asset='overview-'+namespace
    edit_csv(bundle/'summary.csv',lambda rows:[r.update(asset_id=asset) for r in rows])
    run=import_bundle(database,bundle,namespace,'fixture')['run_id']
    # Two criteria on one run must count as ONE reviewed run, not two assets.
    for criterion in ('stability','penetration'):
        add_judgment(database,run,{'reviewer':'Dashboard test','outcome':'inconclusive',
          'criterion_key':criterion,'protocol_version':'test-v1','rationale':'Visual regression fixture',
          'evidence_ids':[],'supersedes_judgment_id':None})
    with database.connect() as conn:
        after={key:conn.execute(queries[key]).fetchone() for key in (10,11,12,13)}
        for query in queries.values():
            conn.execute(query).fetchall()
    assert after[10]['runs']-before[10]['runs']==1
    assert after[11]['assets']-before[11]['assets']==1
    assert after[12]['errors']==before[12]['errors']
    assert after[13]['reviewed']-before[13]['reviewed']==1
