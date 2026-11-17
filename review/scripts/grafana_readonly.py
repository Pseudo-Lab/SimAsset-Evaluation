"""Configure a read-only Grafana login in the owned local PostgreSQL cluster.

Credentials/provisioning are private local files, never source-controlled or printed.
"""
import json
import os
from pathlib import Path
import secrets

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from simasset_review.db import Settings


def main():
    s=Settings.load(); info=conninfo_to_dict(s.dsn)
    role='simasset_grafana_reader'; pw=secrets.token_urlsafe(24)
    with s.connect() as conn:
        found=conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone()
        statement='ALTER ROLE' if found else 'CREATE ROLE'
        conn.execute(sql.SQL(statement+' {} LOGIN PASSWORD {}').format(sql.Identifier(role),sql.Literal(pw)))
        conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(info['dbname']),sql.Identifier(role)))
        conn.execute(sql.SQL('GRANT USAGE ON SCHEMA review TO {}').format(sql.Identifier(role)))
        for view in ('v_run_metrics','v_current_judgments','v_test_coverage'):
            conn.execute(sql.SQL('GRANT SELECT ON review.{} TO {}').format(sql.Identifier(view),sql.Identifier(role)))
        conn.execute(sql.SQL('ALTER ROLE {} SET statement_timeout = {}').format(sql.Identifier(role),sql.Literal('5s')))
        conn.execute(sql.SQL('ALTER ROLE {} SET default_transaction_read_only = on').format(sql.Identifier(role)))
    with psycopg.connect(make_conninfo(s.dsn,user=role,password=pw)) as reader:
        count=reader.execute('SELECT count(*) FROM review.v_run_metrics').fetchone()[0]
        grants=reader.execute("SELECT has_table_privilege(current_user,'review.test_runs','INSERT'), has_table_privilege(current_user,'review.run_judgments','UPDATE')").fetchone()
        assert grants==(False,False)
    root=s.state/'grafana';(root/'provisioning/datasources').mkdir(parents=True,exist_ok=True)
    (root/'provisioning/dashboards').mkdir(parents=True,exist_ok=True)
    # JSON is valid YAML and avoids incorrectly escaping generated credentials.
    config={'apiVersion':1,'datasources':[{'name':'SimAsset local','uid':'simasset-local-postgres',
      'type':'grafana-postgresql-datasource','access':'proxy','url':f"{info['host']}:{info.get('port','5432')}",
      'user':role,'jsonData':{'database':info['dbname'],'sslmode':'disable','postgresVersion':1600,
                            'maxOpenConns':4,'maxIdleConns':2},'secureJsonData':{'password':pw},'editable':False}]}
    p=root/'provisioning/datasources/simasset.yaml';p.write_text(json.dumps(config,indent=2));os.chmod(p,0o600)
    dashboards=Path(__file__).resolve().parents[1]/'grafana'
    (root/'provisioning/dashboards/simasset.yaml').write_text(json.dumps({'apiVersion':1,'providers':[
      {'name':'SimAsset','folder':'SimAsset local','type':'file','disableDeletion':True,
       'options':{'path':str(dashboards)}}]},indent=2))
    admin=secrets.token_urlsafe(24)
    ini=root/'grafana.ini';ini.write_text(f'''[server]
http_addr = 127.0.0.1
http_port = 3015
[paths]
data = {root/'data'}
logs = {root/'logs'}
plugins = {root/'plugins'}
provisioning = {root/'provisioning'}
[security]
admin_user = local-review
admin_password = {admin}
[auth.anonymous]
enabled = false
[analytics]
reporting_enabled = false
check_for_updates = false
''');os.chmod(ini,0o600)
    credentials=root/'local-login.json';credentials.write_text(json.dumps({'user':'local-review','password':admin}));os.chmod(credentials,0o600)
    print(json.dumps({'views_readable':True,'metric_rows':count,'table_write_privileges':False,
                      'provisioning':str(p),'scope':'isolated-local-only'},ensure_ascii=False))


if __name__=='__main__': main()
