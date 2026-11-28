"""Exercise the shipped dashboard queries against real PostgreSQL fixtures."""
import json
import re
import importlib.util
from pathlib import Path

import pytest

from conftest import edit_csv
from simasset_review.db import import_bundle, add_judgment


def test_english_dashboard_is_current_and_preserves_data_queries():
    root=Path(__file__).parents[1]
    spec=importlib.util.spec_from_file_location('grafana_languages',root/'scripts/build_grafana_languages.py')
    generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)
    source=json.loads((root/'grafana/dashboard.json').read_text())
    english=json.loads((root/'grafana/dashboard-en.json').read_text())
    assert english==generator.english_dashboard(source)
    assert english['uid']!=source['uid']

    def data_fields(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in ('rawSql','datasource','transformations','matcher','gridPos'):
                    yield key,item
                else: yield from data_fields(item)
        elif isinstance(value,list):
            for item in value: yield from data_fields(item)
    assert list(data_fields(source))==list(data_fields(english))
    for dashboard,language in ((source,'ko'),(english,'en')):
        assert dashboard['links'][0]['url']==f'http://127.0.0.1:8765/?lang={language}'
        assert {link['title'] for link in dashboard['links']} >= {'한국어','English'}


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


def test_asset_compare_uses_protocol_units_rates_and_keeps_missing_values(database,bundle,namespace):
    dashboard=json.loads((Path(__file__).parents[1]/'grafana/asset-compare.json').read_text(encoding='utf-8'))
    variables={v['name']:v['query'] for v in dashboard['templating']['list']}
    queries={p['id']:p['targets'][0]['rawSql'] for p in dashboard['panels'] if p.get('targets')}
    # Grafana's reader role may only SELECT the granted views.
    for sql in [*variables.values(),*queries.values()]:
        assert set(re.findall(r'review\.(\w+)',sql))<={'v_run_metrics'}
    links=[link['url'] for panel in dashboard['panels'] for o in panel.get('fieldConfig',{}).get('overrides',[])
           for p in o['properties'] if p['id']=='links' for link in p['value']]
    assert links==['http://127.0.0.1:8765/?lang=ko#${__data.fields.run_id}']

    good,bad='compare-good-'+namespace,'compare-bad-'+namespace
    edit_csv(bundle/'summary.csv',lambda rows:[r.update(asset_id=good) for r in rows])
    import_bundle(database,bundle,namespace+'-good','fixture')
    def worse(rows):
        for r in rows:
            r.update(asset_id=bad)
            r.update(value={'peak_pen':'2.5','left_ramp':'0'}.get(r['metric'],r['value']))
    edit_csv(bundle/'summary.csv',worse)
    bad_run=import_bundle(database,bundle,namespace+'-bad','fixture')['run_id']

    def run(sql,metric,scale=''):
        sql=sql.replace('${test}','incline').replace('${metric}',metric).replace('${scale}',scale)
        with database.connect() as conn: return conn.execute(sql).fetchall()
    def selected(sql,metric):
        scale=str(next(iter(run(variables['scale'],metric)[0].values())))
        return {r['에셋']:r for r in run(sql,metric,scale) if r['에셋'] in (good,bad)}
    first=lambda sql,metric:next(iter(run(sql,metric)[0].values()))
    assert [first(variables['unit'],m) for m in ('peak_pen','left_ramp','accel_err_pct')]==['mm','1인 비율','%']

    # Stored SI values return in protocol units; 0/1 metrics become a rate, not a median.
    bars=selected(queries[2],'peak_pen')
    assert (bars[good]['대표값'],bars[bad]['대표값'])==(pytest.approx(1.25),pytest.approx(2.5))
    rates=selected(queries[2],'left_ramp')
    assert (rates[good]['대표값'],rates[bad]['대표값'])==(1,0)
    # A NaN result is counted as missing, never as 0.
    missing=selected(queries[3],'accel_err_pct')[good]
    assert (missing['실행'],missing['값 없음'],missing['최솟값'])==(1,1,None)
    far=run(queries[4],'peak_pen',str(first(variables['scale'],'peak_pen')))
    assert bad_run in [str(r['run_id']) for r in far]
