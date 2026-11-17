from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .bundle import PROFILE, METRICS, STATUSES, InvalidBundle, digest, uid, snapshot, parse, media_type


@dataclass
class Settings:
    state: Path
    dsn: str = field(repr=False)

    @classmethod
    def load(cls):
        state = Path(os.environ.get('SIMASSET_STATE_DIR', '.state')).resolve()
        config = json.loads((state/'config.json').read_text()) if (state/'config.json').exists() else {}
        dsn = os.environ.get('SIMASSET_DATABASE_URL', config.get('database_url', ''))
        if not dsn:
            raise RuntimeError('먼저 python scripts/local_db.py start를 실행해주세요.')
        conn = conninfo_to_dict(dsn)
        if conn.get('host') not in ('127.0.0.1', 'localhost', '::1'):
            raise RuntimeError('이 시제품은 로컬 개발 DB만 허용합니다.')
        if not conn.get('dbname', '').startswith('simasset_review'):
            raise RuntimeError('simasset_review 전용 DB를 사용해주세요.')
        return cls(state, dsn)

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row, options='-c search_path=review,public')


def initialize(settings: Settings):
    with settings.connect() as conn:
        conn.execute(Path(__file__).with_name('schema.sql').read_text())


def attempt(conn, source, namespace, sha, run, status, details):
    conn.execute('''INSERT INTO import_attempts(attempt_id,source_path,source_namespace,
        bundle_sha256,run_id,status,diagnostics) VALUES(%s,%s,%s,%s,%s,%s,%s)''',
        (uuid4(), str(source), namespace, sha, run, status, Jsonb(details)))


def import_bundle(settings: Settings, source: Path, namespace: str, origin: str):
    if origin not in ('fixture', 'local_reproduction', 'team_shared') or not namespace.strip() or len(namespace)>128:
        raise ValueError('namespace와 origin을 명시해주세요.')
    sha = None
    try:
        path, sha, manifest = snapshot(source, settings.state/'objects')
        b = parse(path, sha, manifest)
    except (InvalidBundle, OSError) as e:
        diagnostic = {'code': e.code if isinstance(e, InvalidBundle) else 'file_io', 'message': str(e)}
        with settings.connect() as conn:
            attempt(conn, source, namespace, sha, None, 'invalid', diagnostic)
        return {'status':'invalid', 'bundle_sha256':sha, **diagnostic}
    run = uid('run', namespace, b.source_id)
    with settings.connect() as conn:
        # Serialize the identity check and inserts across concurrent CLI processes.
        lock = int.from_bytes(run.bytes[:8], 'big', signed=True)
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (lock,))
        old = conn.execute('SELECT * FROM test_runs WHERE source_namespace=%s AND source_run_id=%s',
                           (namespace, b.source_id)).fetchone()
        if old:
            same = old['bundle_sha256']==sha and old['origin']==origin
            status = 'duplicate' if same else 'conflict'
            message = '이미 저장한 동일 결과입니다.' if same else '동일 원본 ID의 내용 또는 출처 분류가 다릅니다. 기존 실행은 보존했습니다.'
            details = {'message':message, 'existing_bundle':old['bundle_sha256'], 'incoming_bundle':sha}
            attempt(conn, source, namespace, sha, old['run_id'], status, details)
            return {'status':status, 'run_id':str(old['run_id']), **details}
        asset = uid('asset', namespace, b.asset_id)
        variant = uid('variant', asset, b.asset_hash)
        protocol = uid('protocol', b.test, PROFILE)
        config_hash = digest(b.config)
        case = uid('case', variant, protocol, config_hash)
        conn.execute('INSERT INTO assets VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                     (asset, namespace, b.asset_id, b.asset_id))
        conn.execute('INSERT INTO asset_variants VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                     (variant, asset, b.asset_hash, Jsonb({}), Jsonb({'type':'unknown',
                      'note':'원본 에셋 해시는 출력 파일의 선언값입니다. 실제 적용 물성은 실행 config/raw_meta에 보존합니다.'})))
        conn.execute('INSERT INTO test_protocols VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                     (protocol, b.test, PROFILE, Jsonb(METRICS)))
        conn.execute('INSERT INTO test_cases VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                     (case, variant, protocol, config_hash, Jsonb(b.config)))
        conn.execute('''INSERT INTO test_runs(run_id,case_id,source_namespace,source_run_id,
          bundle_sha256,origin,seed,repeat_index,simulator,engine_version,harness_commit,
          execution_status,source_status,status_reason,raw_meta,source_manifest,warnings)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
          (run,case,namespace,b.source_id,sha,origin,b.seed,None,'MuJoCo',b.meta['mujoco'],
           b.meta.get('git_commit') or None,STATUSES[b.status],b.status,b.meta.get('error'),
           Jsonb(b.meta),Jsonb(manifest),Jsonb(b.warnings)))
        for m in b.metrics:
            mid = uid('metric',protocol,m['name'],PROFILE)
            conn.execute('INSERT INTO metric_definitions VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (mid,protocol,m['name'],m['unit'],PROFILE))
            conn.execute('INSERT INTO run_metrics VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                         (run,mid,m['value'],m['text'],m['valid'],m['reason'],m['raw_value'],m['raw_unit']))
        for f in manifest:
            kind,mime = media_type(f['path'])
            conn.execute('INSERT INTO run_artifacts VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                         (uid('artifact',run,f['path']),run,kind,f['path'],str(path/f['path']),
                          f['sha256'],f['bytes'],mime))
        attempt(conn,source,namespace,sha,run,'imported',{'warnings':b.warnings})
    return {'status':'imported','run_id':str(run),'metrics':len(b.metrics),'warnings':b.warnings}


def list_runs(settings, asset='', test='', version='', origin='', offset=0):
    with settings.connect() as conn:
        return conn.execute('''SELECT r.run_id,r.source_run_id,r.origin,r.seed,r.source_status,
         r.execution_status,r.engine_version,r.imported_at,av.content_hash AS asset_version,
         a.display_name AS asset,p.test_type,p.protocol_version,
         (SELECT count(*) FROM v_current_judgments j WHERE j.run_id=r.run_id) AS judgments,
         (SELECT count(*) FROM run_artifacts ar WHERE ar.run_id=r.run_id AND ar.artifact_type='video') AS videos
         FROM test_runs r JOIN test_cases c USING(case_id) JOIN asset_variants av USING(variant_id)
         JOIN assets a USING(asset_id) JOIN test_protocols p USING(protocol_id)
         WHERE (%s='' OR a.display_name=%s) AND (%s='' OR p.test_type=%s)
          AND (%s='' OR av.content_hash=%s) AND (%s='' OR r.origin=%s)
         ORDER BY a.display_name,r.seed,r.imported_at,r.run_id LIMIT 1000 OFFSET %s''',
         (asset,asset,test,test,version,version,origin,origin,offset)).fetchall()


def get_run(settings, run_id):
    with settings.connect() as conn:
        run = conn.execute('''SELECT r.*,a.display_name AS asset,av.content_hash AS asset_version,
          c.config,p.test_type,p.protocol_version FROM test_runs r JOIN test_cases c USING(case_id)
          JOIN asset_variants av USING(variant_id) JOIN assets a USING(asset_id)
          JOIN test_protocols p USING(protocol_id) WHERE run_id=%s''',(run_id,)).fetchone()
        if not run: return None
        run['metrics'] = conn.execute('''SELECT d.metric_id,d.metric_name,d.unit,m.metric_value,m.metric_text,
          m.valid,m.invalid_reason,m.raw_value,m.raw_unit FROM run_metrics m
          JOIN metric_definitions d USING(metric_id) WHERE run_id=%s ORDER BY d.metric_name''',(run_id,)).fetchall()
        run['artifacts'] = conn.execute('''SELECT artifact_id,artifact_type,filename,sha256,size_bytes,mime_type
           FROM run_artifacts WHERE run_id=%s ORDER BY filename''',(run_id,)).fetchall()
        run['judgments'] = conn.execute('''SELECT j.*, NOT EXISTS(SELECT 1 FROM run_judgments n
          WHERE n.supersedes_judgment_id=j.judgment_id) AS current
          FROM run_judgments j WHERE run_id=%s ORDER BY reviewed_at DESC''',(run_id,)).fetchall()
        return run


def add_judgment(settings, run_id, data):
    with settings.connect() as conn:
        if not conn.execute('SELECT 1 FROM test_runs WHERE run_id=%s',(run_id,)).fetchone():
            raise KeyError('실행이 없습니다.')
        # One current chain for a reviewer/criterion/rubric. Concurrent stale writes conflict.
        key = uid('judgment-lock',run_id,data['reviewer'],data['criterion_key'],data['protocol_version'])
        conn.execute('SELECT pg_advisory_xact_lock(%s)',(int.from_bytes(key.bytes[:8],'big',signed=True),))
        current = conn.execute('''SELECT judgment_id FROM v_current_judgments WHERE run_id=%s
          AND reviewer=%s AND criterion_key=%s AND protocol_version=%s''',
          (run_id,data['reviewer'],data['criterion_key'],data['protocol_version'])).fetchone()
        previous = data.get('supersedes_judgment_id')
        if (str(current['judgment_id']) if current else None) != (str(previous) if previous else None):
            raise ValueError('판정이 이미 변경됐습니다. 최신 내용을 다시 읽고 수정해주세요.')
        for evidence in data['evidence_ids']:
            valid = conn.execute('SELECT 1 FROM run_artifacts WHERE artifact_id=%s AND run_id=%s',
                                  (evidence,run_id)).fetchone()
            if not valid:
                raise ValueError('다른 실행의 근거 또는 존재하지 않는 근거입니다.')
        jid=uuid4()
        conn.execute('''INSERT INTO run_judgments(judgment_id,run_id,outcome,reviewer,criterion_key,
          protocol_version,rationale,evidence_ids,supersedes_judgment_id)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
          (jid,run_id,data['outcome'],data['reviewer'],data['criterion_key'],data['protocol_version'],
           data['rationale'],Jsonb([str(x) for x in data['evidence_ids']]),previous))
        return {'judgment_id':str(jid)}
