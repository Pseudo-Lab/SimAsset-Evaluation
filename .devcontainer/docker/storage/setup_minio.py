"""Create the project bucket and a bucket-scoped shared account on an existing MinIO server.

Admin only, once. Put the server's admin keys in MINIO_ACCESS_KEY / MINIO_SECRET_KEY
of the project env file, then run:

    .devcontainer/docker/storage/setup-minio.sh

Only the MINIO_* lines of the env file are read (same quoting rules as compose).

1. Create MINIO_BUCKET (if missing) and turn on versioning, so overwrites and
   deletions by the shared key stay recoverable.
2. Add policy <bucket>-rw: list/read/write/delete inside that bucket only.
   Permanent version deletion (s3:DeleteObjectVersion) is denied explicitly and
   other buckets are not granted.
3. Add user MINIO_TEAM_USER with a random secret and attach only that policy.
4. Check the new key: bucket read/write/delete work; listing all buckets, other
   buckets and permanent version deletion are denied.
5. Only after every check passes, replace MINIO_ACCESS_KEY / MINIO_SECRET_KEY in
   the project env file with the new key. On failure the new user is removed and
   the env file is left unchanged.

Secret values are never printed.
"""
from __future__ import annotations

import io
import json
import os
import secrets
import sys
import time
from pathlib import Path

from minio import Minio
from minio.credentials import StaticProvider
from minio.error import S3Error
from minio.minioadmin import MinioAdmin
from minio.versioningconfig import ENABLED, VersioningConfig

ENV_FILE = Path(os.environ.get('PROJECT_ENV_FILE', '/workspace/.env'))
TEST_PREFIX = '_setup-check/'
KEYS = ('MINIO_ENDPOINT', 'MINIO_ACCESS_KEY', 'MINIO_SECRET_KEY', 'MINIO_BUCKET')


def read_minio_settings(path: Path) -> dict:
    """KEY=VALUE lines like compose: '#' comments, optional matching quotes."""
    found = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = (part.strip() for part in line.split('=', 1))
        if name not in KEYS:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        else:
            value = value.split(' #', 1)[0].strip()
        found[name] = value
    missing = [k for k in KEYS if not found.get(k)]
    if missing:
        sys.exit(f'{path.name}에 값이 없습니다: {", ".join(missing)}')
    return found


def endpoint():
    raw = os.environ['MINIO_ENDPOINT'].strip().rstrip('/')
    secure = raw.startswith('https://')
    return raw.removeprefix('https://').removeprefix('http://'), secure


def policy_for(bucket: str) -> dict:
    return {'Version': '2012-10-17', 'Statement': [
        {'Effect': 'Allow',
         'Action': ['s3:GetBucketLocation', 's3:ListBucket', 's3:ListBucketMultipartUploads',
                    's3:ListBucketVersions'],
         'Resource': [f'arn:aws:s3:::{bucket}']},
        {'Effect': 'Allow',
         'Action': ['s3:GetObject', 's3:GetObjectVersion', 's3:PutObject', 's3:DeleteObject',
                    's3:AbortMultipartUpload', 's3:ListMultipartUploadParts'],
         'Resource': [f'arn:aws:s3:::{bucket}/*']},
        # MinIO (2024-12) lets s3:DeleteObject also remove a specific version permanently
        # unless DeleteObjectVersion is denied explicitly. Plain deletes still add a delete marker.
        {'Effect': 'Deny', 'Action': ['s3:DeleteObjectVersion'],
         'Resource': [f'arn:aws:s3:::{bucket}/*']},
    ]}


def step(message):
    print(f'· {message}', flush=True)


def denied(action) -> bool:
    try:
        action()
    except S3Error as e:
        return e.code in ('AccessDenied', 'AllAccessDisabled') or e.response.status == 403
    return False


def verify(host, secure, bucket, access, secret, other_bucket):
    team = Minio(host, access, secret, secure=secure)
    # A fresh user can take a moment to propagate on the server.
    for _ in range(10):
        try:
            team.bucket_exists(bucket)
            break
        except S3Error:
            time.sleep(1)
    key = f'{TEST_PREFIX}{int(time.time())}.txt'
    body = b'simasset storage check\n'
    put = team.put_object(bucket, key, io.BytesIO(body), len(body))
    got = team.get_object(bucket, key)
    try:
        assert got.read() == body, 'read back differs'
    finally:
        got.close(); got.release_conn()
    step('새 키: 버킷 목록·쓰기·읽기 확인')
    assert any(o.object_name == key for o in team.list_objects(bucket, prefix=TEST_PREFIX)), 'listing failed'
    assert denied(lambda: team.remove_object(bucket, key, version_id=put.version_id)), \
        'permanent version deletion was allowed'
    team.remove_object(bucket, key)  # versioned: adds a delete marker only
    step('새 키: 삭제는 되고(복구 가능), 버전 영구 삭제는 거절 확인')
    # MinIO answers ListBuckets with only the buckets this key may use.
    visible = sorted(b.name for b in team.list_buckets())
    assert set(visible) <= {bucket}, f'other buckets are visible: {visible}'
    if other_bucket:
        assert denied(lambda: next(iter(team.list_objects(other_bucket)), None)), 'another bucket was readable'
    step('새 키: 다른 버킷은 목록에 안 보이고 접근도 거절 확인')
    return key


def purge(admin_client, bucket, prefix):
    for o in admin_client.list_objects(bucket, prefix=prefix, include_version=True):
        admin_client.remove_object(bucket, o.object_name, version_id=o.version_id)


def write_env(access, secret):
    text = ENV_FILE.read_text(encoding='utf-8')
    values = {'MINIO_ACCESS_KEY': access, 'MINIO_SECRET_KEY': secret}
    lines, seen = [], set()
    for line in text.splitlines(keepends=True):
        name = line.split('=', 1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else None
        if name in values:
            line = f'{name}={values[name]}\n'
            seen.add(name)
        lines.append(line)
    for name, value in values.items():
        if name not in seen:
            if lines and not lines[-1].endswith('\n'):
                lines[-1] += '\n'
            lines.append(f'{name}={value}\n')
    mode = ENV_FILE.stat().st_mode & 0o777
    temp = ENV_FILE.with_name(ENV_FILE.name + '.tmp-minio')
    temp.write_text(''.join(lines), encoding='utf-8')
    os.chmod(temp, mode)
    os.replace(temp, ENV_FILE)


def main():
    if not ENV_FILE.is_file():
        sys.exit(f'프로젝트 설정 파일이 없습니다: {ENV_FILE}')
    os.environ.update(read_minio_settings(ENV_FILE))
    host, secure = endpoint()
    bucket = os.environ['MINIO_BUCKET'].strip()
    team_user = (os.environ.get('MINIO_TEAM_USER') or f'{bucket}-team').strip()
    policy_name = f'{bucket}-rw'
    admin_key, admin_secret = os.environ['MINIO_ACCESS_KEY'], os.environ['MINIO_SECRET_KEY']

    admin = MinioAdmin(endpoint=host, credentials=StaticProvider(admin_key, admin_secret), secure=secure)
    s3 = Minio(host, admin_key, admin_secret, secure=secure)
    try:
        users = json.loads(admin.user_list())
    except Exception as e:  # noqa: BLE001 - report without credentials
        sys.exit(f'관리자 권한으로 접속하지 못했습니다. 현재 키가 관리자 키인지 확인해주세요. ({type(e).__name__})')
    if team_user in users and os.environ.get('MINIO_ROTATE') != '1':
        sys.exit(f'사용자 {team_user}가 이미 있습니다. 키를 새로 만들려면 MINIO_ROTATE=1로 다시 실행하세요.')
    others = [b.name for b in s3.list_buckets() if b.name != bucket]

    if not s3.bucket_exists(bucket):
        s3.make_bucket(bucket)
        step(f'버킷 {bucket} 생성')
    else:
        step(f'버킷 {bucket} 이미 있음')
    s3.set_bucket_versioning(bucket, VersioningConfig(ENABLED))
    step('버전 관리 켜기')
    admin.policy_add(policy_name, policy=policy_for(bucket))
    step(f'정책 {policy_name} 등록')

    secret = secrets.token_urlsafe(30)  # 40 characters, MinIO's maximum
    admin.user_add(team_user, secret)
    admin.attach_policy([policy_name], user=team_user)
    step(f'사용자 {team_user} 생성, 정책 {policy_name}만 연결')

    try:
        verify(host, secure, bucket, team_user, secret, others[0] if others else None)
    except (AssertionError, S3Error) as e:
        admin.user_remove(team_user)
        sys.exit(f'새 키 확인 실패로 사용자 {team_user}를 지웠습니다. 설정 파일은 바꾸지 않았습니다. ({e})')
    finally:
        purge(s3, bucket, TEST_PREFIX)

    write_env(team_user, secret)
    step(f'{ENV_FILE.name}의 MINIO_ACCESS_KEY, MINIO_SECRET_KEY를 {team_user} 키로 교체 (값은 출력하지 않음)')
    print('완료')


if __name__ == '__main__':
    main()
