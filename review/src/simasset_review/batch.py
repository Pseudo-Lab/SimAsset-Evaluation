"""Audit expected result folders before importing, including missing summaries."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import tempfile
import unicodedata

from .bundle import InvalidBundle, fail, read_json, snapshot, parse

MARKERS = {'summary.csv', 'meta.json', 'timeseries.csv', 'timeseries_probe.csv'}


def discover(roots: list[Path], recursive: bool) -> list[Path]:
    paths = set()
    for root in roots:
        if not recursive or not root.is_dir() or root.is_symlink():
            paths.add(root)
            continue
        found = {p.parent for p in root.rglob('*') if p.name in MARKERS}
        # A directory link cannot be silently treated as absent by rglob.
        found.update(p for p in root.rglob('*') if p.is_symlink() and p.is_dir())
        paths.update(found or {root})
    return sorted(paths)


def relative_path(value):
    if not isinstance(value, str) or not value or '\\' in value:
        fail('expected_plan', '결과 경로는 비어 있지 않은 상대 경로여야 합니다.')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or str(p) != value or value == '.':
        fail('expected_plan', f'안전한 하위 결과 경로가 아닙니다: {value}')
    return unicodedata.normalize('NFC', value)


def load_expected(path: Path | None) -> dict:
    if path is None:
        return {}
    plan = read_json(path)
    if plan.get('schema_version') != 1 or not isinstance(plan.get('runs'), list) or not plan['runs']:
        fail('expected_plan', 'schema_version=1과 비어 있지 않은 runs 목록이 필요합니다.')
    expected = {}
    for run in plan['runs']:
        if not isinstance(run, dict):
            fail('expected_plan', 'runs의 각 항목은 객체여야 합니다.')
        name = relative_path(run.get('path'))
        if name in expected:
            fail('expected_plan', f'중복된 예상 경로입니다: {name}')
        for field in ('asset_id', 'test', 'condition'):
            if not isinstance(run.get(field), str) or not run[field].strip():
                fail('expected_plan', f'{name}: {field}가 필요합니다.')
        if not isinstance(run.get('seed'), int) or isinstance(run['seed'], bool):
            fail('expected_plan', f'{name}: seed는 정수여야 합니다.')
        artifacts = run.get('required_artifacts', [])
        if not isinstance(artifacts, list):
            fail('expected_plan', f'{name}: required_artifacts는 배열이어야 합니다.')
        expected[name] = {**run, 'path': name,
                          'required_artifacts': [relative_path(x) for x in artifacts]}
    names = set(expected)
    if any(str(parent) in names for n in names for parent in PurePosixPath(n).parents):
        fail('expected_plan', '한 실행 폴더 안에 다른 예상 실행 폴더를 넣을 수 없습니다.')
    return expected


def audit(root: Path, expected_path: Path | None = None) -> dict:
    expected = load_expected(expected_path)
    root = root.absolute()
    candidates = discover([root], True)
    if (expected and candidates == [root] and (not root.exists() or root.is_dir())
            and not root.is_symlink() and not any((root/n).exists() for n in MARKERS)):
        candidates = []
    by_name = {}
    for candidate in candidates:
        name = unicodedata.normalize('NFC', candidate.relative_to(root).as_posix())
        if name in by_name and by_name[name] != candidate:
            fail('filename_collision', 'NFC로 정규화하면 같은 이름이 되는 결과 폴더가 있습니다.')
        by_name[name] = candidate
    for name in expected:
        by_name.setdefault(name, root/name)
    records = []
    identities = {}
    # Temporary snapshots are removed per batch; no DB or original is changed.
    with tempfile.TemporaryDirectory(prefix='simasset-audit-') as temp:
        for name, source in sorted(by_name.items()):
            record = {'path': name, 'status': 'invalid', 'expected': name in expected}
            try:
                if not source.exists():
                    fail('missing_result', '예상 실행 폴더가 없습니다.')
                if any(p.is_symlink() for p in [source, *source.parents] if p == root or p.is_relative_to(root)):
                    fail('symlink', '결과 경로에 심볼릭 링크가 있습니다.')
                # Each result gets a bounded temporary copy, rather than retaining the whole batch.
                with tempfile.TemporaryDirectory(dir=temp) as one:
                    stored, sha, manifest = snapshot(source, Path(one))
                    b = parse(stored, sha, manifest)
                    identity = {'asset_id': b.asset_id, 'test': b.test, 'seed': b.seed,
                                'condition': b.condition}
                    record.update(identity, source_run_id=b.source_id, asset_sha256=b.asset_hash,
                                  bundle_sha256=sha, profile=b.profile, warnings=b.warnings,
                                  source_status=b.status, metrics=len(b.metrics))
                    wanted = expected.get(name)
                    if expected and wanted is None:
                        fail('unexpected_result', '예상 목록에 없는 결과입니다. 다른 배치가 섞였는지 확인해주세요.')
                    if wanted:
                        mismatches = [key for key in identity if wanted[key] != identity[key]]
                        if mismatches:
                            fail('expected_identity', '예상 실행과 다릅니다: '+', '.join(mismatches))
                        missing = set(wanted['required_artifacts']) - {x['path'] for x in manifest}
                        if missing:
                            fail('missing_artifact', '예상 근거 파일이 없습니다: '+', '.join(sorted(missing)))
                    old = identities.get(b.source_id)
                    if old:
                        code = 'duplicate_run' if old['bundle_sha256'] == sha else 'conflicting_run'
                        record['other_path'] = old['path']
                        fail(code, '같은 namespace로 가져오면 원본 실행 ID가 겹칩니다. 반복 실행을 구분해주세요.')
                    identities[b.source_id] = record
                    record['status'] = 'valid'
            except (InvalidBundle, OSError) as error:
                record.update(code=error.code if isinstance(error, InvalidBundle) else 'file_io',
                              message=str(error))
            records.append(record)
    valid = [r for r in records if r['status'] == 'valid']
    return {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'root': str(root), 'expected_count': len(expected) if expected_path else None,
            'checked_count': len(records), 'valid_count': len(valid),
            'invalid_count': len(records)-len(valid),
            'expected_coverage_verified': bool(expected) and len(valid) == len(expected) == len(records),
            'ready_for_import': bool(records) and len(valid) == len(records),
            'asset_names': sorted({r['asset_id'] for r in valid}),
            'source_status_counts': dict(Counter(r['source_status'] for r in valid)),
            'records': records,
            'note': '원본과 DB는 변경하지 않았습니다. 예상 목록이 없으면 전체 제출 수량은 검증하지 않습니다. '
                    'valid는 파일 형식 검증이며 에셋 품질의 통과 판정이 아닙니다.'}
