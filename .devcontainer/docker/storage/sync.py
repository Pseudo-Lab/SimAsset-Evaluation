"""Sync the local results folder (review/evidence) with the project MinIO bucket.

    push [--prefix P] [--dry-run]   upload files whose SHA-256 differs from the bucket copy
    pull [--prefix P] [--dry-run]   download files that are missing or differ, verified by SHA-256
    list [--prefix P]               summarize what the bucket holds
    verify [--prefix P]             compare stored bytes (server MD5 ETag) with local files
    remove PATH...                  hide exact bucket paths (older versions stay)

Object key = path relative to the results folder (POSIX, NFC). Every object carries its
SHA-256 as user metadata (x-amz-meta-sha256). After a push, manifest.json at the bucket
root lists every object with size and SHA-256; the bucket keeps earlier manifests as
versions. ZIP archives are never uploaded. push and pull never delete anything; only
remove with exact paths does, and versioning keeps the data recoverable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
import tempfile
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_minio import endpoint, read_minio_settings  # noqa: E402

from minio import Minio  # noqa: E402

DATA = Path(os.environ.get('STORAGE_DATA', '/data'))
SETTINGS = Path(os.environ.get('STORAGE_SETTINGS', '/config/project-settings'))
MANIFEST = 'manifest.json'
SKIP_DIRS = {'__pycache__', '.git'}
SKIP_NAMES = {'.DS_Store', 'Thumbs.db'}
# Archives are not stored in the bucket; share the extracted folders instead.
SKIP_SUFFIXES = ('.zip',)
WORKERS = 8


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def remote_sha(obj) -> str | None:
    for key, value in (obj.metadata or {}).items():
        if key.lower() in ('x-amz-meta-sha256', 'sha256'):
            return value
    return None


def human(n: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.1f} {unit}' if unit != 'B' else f'{int(n)} B'
        n /= 1024


def local_files(prefix: str):
    files = {}
    for p in sorted(DATA.rglob('*')):
        rel_parts = p.relative_to(DATA).parts
        if (any(part in SKIP_DIRS for part in rel_parts) or p.name in SKIP_NAMES
                or p.name.lower().endswith(SKIP_SUFFIXES)):
            continue
        if p.is_symlink():
            print(f'  건너뜀 (심볼릭 링크): {p.relative_to(DATA)}')
            continue
        if not p.is_file():
            continue
        key = unicodedata.normalize('NFC', p.relative_to(DATA).as_posix())
        if key == MANIFEST or not key.startswith(prefix):
            continue
        files[key] = p
    return files


def remote_objects(client, bucket, prefix):
    return {o.object_name: o for o in client.list_objects(bucket, prefix=prefix or None, recursive=True,
                                                         include_user_meta=True)
            if not o.is_dir and o.object_name != MANIFEST}


def run_parallel(jobs, label):
    done, failed, total = 0, [], len(jobs)
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(job): key for key, job in jobs}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:  # noqa: BLE001 - report and continue with the rest
                failed.append((futures[future], f'{type(e).__name__}: {e}'))
            done += 1
            if done % 250 == 0 or done == total:
                print(f'  {label} {done}/{total}', flush=True)
    return failed


def write_manifest(client, bucket):
    objects = remote_objects(client, bucket, '')
    entries = [{'path': k, 'bytes': o.size, 'sha256': remote_sha(o)} for k, o in sorted(objects.items())]
    body = json.dumps({'schema_version': 1, 'bucket': bucket,
                       'generated_at': datetime.now(timezone.utc).isoformat(),
                       'object_count': len(entries), 'total_bytes': sum(e['bytes'] for e in entries),
                       'objects': entries}, ensure_ascii=False, indent=1).encode()
    client.put_object(bucket, MANIFEST, BytesIO(body), len(body), content_type='application/json')
    return len(entries), sum(e['bytes'] for e in entries)


def push(client, bucket, prefix, dry_run):
    local = local_files(prefix)
    print(f'로컬 {len(local)}개 파일의 SHA-256 계산 중…', flush=True)
    with ThreadPoolExecutor(WORKERS) as pool:
        hashes = dict(zip(local, pool.map(sha256_of, local.values())))
    remote = remote_objects(client, bucket, prefix)
    todo = [k for k in local if k not in remote or remote_sha(remote[k]) != hashes[k]]
    size = sum(local[k].stat().st_size for k in todo)
    print(f'올릴 파일 {len(todo)}개 ({human(size)}), 이미 같은 파일 {len(local) - len(todo)}개')
    if dry_run or not todo:
        return 0
    start = time.time()

    def upload(key):
        content_type = mimetypes.guess_type(key)[0] or 'application/octet-stream'
        client.fput_object(bucket, key, str(local[key]), content_type=content_type,
                           metadata={'sha256': hashes[key]})

    failed = run_parallel([(k, (lambda k=k: upload(k))) for k in todo], '업로드')
    elapsed = time.time() - start
    print(f'업로드 {len(todo) - len(failed)}개, {human(size)}, {elapsed:.0f}초 ({human(size / max(elapsed, 1e-9))}/s)')
    count, total = write_manifest(client, bucket)
    print(f'{MANIFEST} 갱신: 버킷 전체 {count}개, {human(total)}')
    for key, err in failed:
        print(f'  실패: {key} ({err})')
    return 1 if failed else 0


def pull(client, bucket, prefix, dry_run):
    remote = remote_objects(client, bucket, prefix)
    todo = []
    for key, obj in remote.items():
        target = DATA / key
        if target.is_file() and target.stat().st_size == obj.size and sha256_of(target) == remote_sha(obj):
            continue
        todo.append(key)
    size = sum(remote[k].size for k in todo)
    print(f'받을 파일 {len(todo)}개 ({human(size)}), 이미 같은 파일 {len(remote) - len(todo)}개')
    if dry_run or not todo:
        return 0
    start = time.time()

    def download(key):
        expected = remote_sha(remote[key])
        target = DATA / key
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix='.pull-', dir=target.parent)
        os.close(fd)
        try:
            client.fget_object(bucket, key, temp, version_id=remote[key].version_id)
            actual = sha256_of(Path(temp))
            if expected and actual != expected:
                raise ValueError('SHA-256 불일치, 저장하지 않음')
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    failed = run_parallel([(k, (lambda k=k: download(k))) for k in todo], '다운로드')
    elapsed = time.time() - start
    print(f'다운로드 {len(todo) - len(failed)}개, {human(size)}, {elapsed:.0f}초')
    for key, err in failed:
        print(f'  실패: {key} ({err})')
    return 1 if failed else 0


def verify(client, bucket, prefix):
    """Compare what the server stored with local files without downloading.

    For single-part uploads the server's ETag is the MD5 of the stored bytes; multipart
    ETags (with '-') are not content hashes, so those objects are checked by size only.
    """
    local = local_files(prefix)
    remote = remote_objects(client, bucket, prefix)

    def check(key):
        obj, path = remote.get(key), local.get(key)
        if obj is None or path is None:
            return key, 'missing_remote' if obj is None else 'missing_local'
        if obj.size != path.stat().st_size:
            return key, 'size_differs'
        etag = (obj.etag or '').strip('"')
        if '-' in etag:
            return key, 'size_only'
        h = hashlib.md5()
        with path.open('rb') as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
        return key, 'ok' if h.hexdigest() == etag else 'content_differs'

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(check, sorted(set(local) | set(remote))))
    counts = {}
    for key, state in results:
        counts[state] = counts.get(state, 0) + 1
        if state not in ('ok', 'size_only'):
            print(f'  {state}: {key}')
    print('검증:', ', '.join(f'{k} {v}' for k, v in sorted(counts.items())))
    return 0 if set(counts) <= {'ok', 'size_only'} else 1


def remove(client, bucket, paths):
    """Hide exact keys. With bucket versioning the data stays as an older version."""
    if not paths:
        print('지울 경로를 하나 이상 지정해주세요. 접두어나 와일드카드는 받지 않습니다.')
        return 2
    removed = 0
    for key in paths:
        key = unicodedata.normalize('NFC', key)
        try:
            client.stat_object(bucket, key)
        except Exception:  # noqa: BLE001 - missing or not visible
            print(f'  없음: {key}')
            continue
        client.remove_object(bucket, key)
        removed += 1
        print(f'  지움: {key}')
    count, total = write_manifest(client, bucket)
    print(f'{removed}개 지움 (버전 관리로 이전 버전은 남음). {MANIFEST} 갱신: 버킷 전체 {count}개, {human(total)}')
    return 0


def summary(client, bucket, prefix):
    remote = remote_objects(client, bucket, prefix)
    groups = {}
    for key, obj in remote.items():
        top = '/'.join(key.split('/')[:2])
        count, size = groups.get(top, (0, 0))
        groups[top] = (count + 1, size + obj.size)
    for top, (count, size) in sorted(groups.items()):
        print(f'  {top:70s} {count:6d}개 {human(size):>10s}')
    missing = sum(1 for o in remote.values() if not remote_sha(o))
    print(f'합계 {len(remote)}개, {human(sum(o.size for o in remote.values()))}, SHA-256 없는 객체 {missing}개')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['push', 'pull', 'list', 'verify', 'remove'])
    parser.add_argument('paths', nargs='*', help='remove: 지울 버킷 경로 (정확한 경로만)')
    parser.add_argument('--prefix', default='', help='이 경로로 시작하는 파일만 (예: runs/simasset-env-v4.2/)')
    parser.add_argument('--dry-run', action='store_true', help='무엇을 옮길지 세기만 합니다')
    args = parser.parse_args()
    settings = read_minio_settings(SETTINGS)
    os.environ.update(settings)
    host, secure = endpoint()
    client = Minio(host, settings['MINIO_ACCESS_KEY'], settings['MINIO_SECRET_KEY'], secure=secure)
    bucket = settings['MINIO_BUCKET']
    print(f'버킷 {bucket} · 로컬 {DATA}' + (f' · 접두어 {args.prefix}' if args.prefix else ''), flush=True)
    action = {'push': lambda: push(client, bucket, args.prefix, args.dry_run),
              'pull': lambda: pull(client, bucket, args.prefix, args.dry_run),
              'list': lambda: summary(client, bucket, args.prefix),
              'verify': lambda: verify(client, bucket, args.prefix),
              'remove': lambda: remove(client, bucket, args.paths)}[args.command]
    sys.exit(action())


if __name__ == '__main__':
    main()
