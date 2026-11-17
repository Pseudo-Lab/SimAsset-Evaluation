"""Read versioned shared outputs without altering units, IDs or source files."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import mimetypes
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid5

NAMESPACE = UUID('10b114b1-2aa4-4bcf-bd6e-424c54878f69')
PROFILE = 'incline-env-v3-adapter-1'
PROBE_PROFILE = 'probe-env-v3-adapter-1'
STATUSES = {'ok': 'completed', 'unsettled': 'completed', 'diverged': 'completed',
            'missing_inertial': 'error', 'missing_inertia': 'error', 'error': 'error',
            'not_applicable': 'skipped'}
FIELDS = ['run_id', 'asset_id', 'asset_sha256', 'test', 'material', 'condition',
          'seed', 'status', 'metric', 'value', 'unit']
TS_FIELDS = ['t', 'x', 'y', 'z', 'qw', 'qx', 'qy', 'qz', 'vx', 'vy', 'vz',
             'wx', 'wy', 'wz', 'ncon', 'max_pen']
TS_UNITS = {'t': 's', 'x': 'mm', 'y': 'mm', 'z': 'mm', 'q*': 'unit quaternion (world)',
            'v*': 'mm/s (center of mass, world)', 'w*': 'deg/s (world)',
            'ncon': 'count (asset contacts)', 'max_pen': 'mm (max penetration depth)'}
# Source output units are checked per metric, then numeric values are stored in SI.
METRICS = {
 'rest_settle_time_s': 's', 'mass_kg': 'kg', 'mu_applied': '', 'bbox_diag_mm': 'mm',
 'theta_slide_pred_deg': 'deg', 'theta_tip_pred_deg': 'deg', 'mode_pred': '',
 'energy_increase_pct': '%', 'motion_mode': '', 'slip_ratio': '', 'mode_match': 'bool',
 'left_ramp': 'bool', 'accel_m_s2': 'm/s2', 'accel_fit_r2': '', 'accel_pred_m_s2': 'm/s2',
 'accel_err_pct': '%', 'mu_k_eff': '', 'mu_k_err_pct': '%', 'max_lift_mm': 'mm',
 'ramp_fit_duration_s': 's', 'ramp_exit_speed_mm_s': 'mm/s', 'runout_mm': 'mm',
 'floor_motion_mode': '', 'floor_slip_ratio': '', 'floor_speed_after_landing_mm_s': 'mm/s',
 'landing_speed_loss_pct': '%', 'settle_time_s': 's', 'rest_pen': 'mm',
 'lateral_drift_mm': 'mm', 'lateral_drift_pct_diag': '%', 'max_tilt_on_ramp_deg': 'deg',
 'peak_pen': 'mm', 'runout_pct_diag': '%', 'max_lift_pct_diag': '%',
 'peak_pen_pct_diag': '%', 'rest_pen_pct_diag': '%', 'note': '', 'none': '',
}
TEXT_METRICS = {'mode_pred', 'motion_mode', 'floor_motion_mode', 'note'}
PROBE_METRICS = {
 'bbox_diag_mm': 'mm', 'mass_kg': 'kg', 'ball_radius': 'mm',
 'asset_presettle_time_s': 's', 'probe_pass': 'bool', 'probe_depth': 'mm',
 'probe_depth_ratio': '%', 'probe_floor_gap': 'mm', 'probe_max_depth': 'mm',
 'probe_center_offset': 'mm', 'ball_settle_time': 's', 'asset_moved': 'mm',
 'asset_tilt_end': 'deg', 'peak_pen': 'mm', 'note': '', 'none': '',
 **{name + '_pct_diag': '%' for name in (
     'probe_depth', 'probe_floor_gap', 'probe_max_depth', 'probe_center_offset',
     'asset_moved', 'peak_pen')},
}
PROBE_FIELDS = ['t', 'ball_x_mm', 'ball_y_mm', 'ball_z_mm', 'ball_local_x_mm',
                'ball_local_y_mm', 'ball_local_z_mm', 'depth_mm', 'inside_opening',
                'ball_speed_mm_s']
PROFILES = {'incline': (PROFILE, METRICS), 'probe': (PROBE_PROFILE, PROBE_METRICS)}
UNITS = {'mm': ('m', .001), 'mm/s': ('m/s', .001), 'deg': ('rad', math.pi/180),
         '%': ('1', .01), 'bool': ('bool', 1), '': ('1', 1),
         's': ('s', 1), 'kg': ('kg', 1), 'm/s2': ('m/s2', 1)}


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def uid(*parts) -> UUID:
    return uuid5(NAMESPACE, canonical([str(x) if isinstance(x, UUID) else x for x in parts]))


class InvalidBundle(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def fail(code, message):
    raise InvalidBundle(code, message)


def finite(value, field):
    try:
        v = float(value)
    except (TypeError, ValueError):
        fail('invalid_number', f'{field}: 수치가 필요합니다.')
    if not math.isfinite(v):
        fail('invalid_number', f'{field}: 유한한 수치가 필요합니다.')
    return v


def integer(value, field):
    if isinstance(value, bool) or not re.fullmatch(r'-?\d+', str(value)):
        fail('invalid_integer', f'{field}: 정수가 필요합니다.')
    v = int(value)
    if not -(2**63) <= v < 2**63:
        fail('invalid_integer', f'{field}: bigint 범위를 벗어났습니다.')
    return v


def read_json(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'),
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (ValueError, UnicodeError, OSError) as e:
        fail('invalid_json', f'{path.name}: {e}')
    if not isinstance(data, dict):
        fail('invalid_json', f'{path.name}: 객체가 필요합니다.')
    return data


def csv_rows(path, required):
    if path.stat().st_size > 32 * 1024 * 1024:
        fail('file_too_large', f'{path.name}: CSV 32 MiB 제한을 넘었습니다.')
    try:
        with path.open(encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != required:
                fail('csv_columns', f'{path.name}: 열 순서가 {required}와 달라 다른 출력 버전일 수 있습니다.')
            rows = list(reader)
    except (UnicodeError, csv.Error) as e:
        fail('invalid_csv', f'{path.name}: {e}')
    if not rows:
        fail('empty_csv', f'{path.name}: 데이터가 없습니다.')
    if any(None in r or any(v is None for v in r.values()) for r in rows):
        fail('csv_columns', f'{path.name}: 행마다 열 수가 다릅니다.')
    return rows


def snapshot(source: Path, store: Path) -> tuple[Path, str, list]:
    """Copy once, hash the copied bytes, and validate only that immutable snapshot."""
    if source.is_symlink() or not source.is_dir():
        fail('invalid_path', '일반 결과 폴더를 지정해주세요. 심볼릭 링크는 받지 않습니다.')
    store.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.incoming-', dir=store))
    manifest = []
    total = 0
    try:
        for p in sorted(source.rglob('*')):
            if p.is_symlink():
                fail('symlink', f'심볼릭 링크가 포함되어 있습니다: {p.name}')
            if not p.is_file():
                continue
            original_rel = p.relative_to(source).as_posix()
            rel = unicodedata.normalize('NFC', original_rel)
            if p.name == '.DS_Store':
                continue
            total += p.stat().st_size
            if len(manifest) >= 100 or total > 256 * 1024 * 1024:
                fail('bundle_too_large', '한 결과는 최대 100개 파일, 256 MiB까지 받습니다.')
            if any(item['path'] == rel for item in manifest):
                fail('filename_collision', 'NFC로 정규화하면 같은 이름이 되는 파일이 있습니다.')
            target = temp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            size = 0
            with p.open('rb') as src, target.open('xb') as dst:
                while chunk := src.read(1024 * 1024):
                    size += len(chunk)
                    if size > 256 * 1024 * 1024:
                        fail('bundle_too_large', '복사 중 파일이 크기 제한을 넘었습니다.')
                    h.update(chunk)
                    dst.write(chunk)
            item = {'path': rel, 'sha256': h.hexdigest(), 'bytes': size}
            if original_rel != rel:
                item['original_path'] = original_rel
            manifest.append(item)
        if sum(x['bytes'] for x in manifest) > 256 * 1024 * 1024:
            fail('bundle_too_large', '파일 합계가 256 MiB를 넘었습니다.')
        key = digest(manifest)
        destination = store / key
        # The digest directory is append-only. Concurrent identical imports reuse it.
        try:
            temp.rename(destination)
        except OSError:
            if not destination.is_dir():
                raise
            for item in manifest:
                existing = destination / item['path']
                if not existing.is_file() or hashlib.sha256(existing.read_bytes()).hexdigest() != item['sha256']:
                    fail('store_corrupt', '보관본 해시가 다릅니다. 덮어쓰지 않았습니다.')
        return destination, key, manifest
    finally:
        if temp.exists():
            shutil.rmtree(temp)


@dataclass
class Bundle:
    path: Path
    sha256: str
    manifest: list
    source_id: str
    asset_id: str
    asset_hash: str | None
    seed: int
    test: str
    status: str
    meta: dict
    config: dict
    metrics: list
    warnings: list
    condition: str
    profile: str
    metric_rules: dict


def validate_probe_series(path: Path, common_rows: list):
    """Pre-release blanks are unavailable observations, never zero depth."""
    if not path.is_file():
        fail('missing_file', '홈 검사에 timeseries_probe.csv가 없습니다.')
    rows = csv_rows(path, PROBE_FIELDS)
    if len(rows) != len(common_rows):
        fail('probe_alignment', '공과 에셋 시계열의 관측 개수가 다릅니다.')
    released = False
    for i, (row, common) in enumerate(zip(rows, common_rows)):
        if finite(row['t'], f'probe.t[{i}]') != finite(common['t'], f'timeseries.t[{i}]'):
            fail('probe_alignment', '공과 에셋 시계열의 시각이 다릅니다.')
        blanks = [row[k].strip() == '' for k in PROBE_FIELDS[1:]]
        if all(blanks) and not released:
            continue
        if any(blanks):
            fail('probe_observation', '공을 놓기 전의 연속된 빈 구간 이외에는 관측값이 필요합니다.')
        released = True
        values = {k: finite(row[k], f'probe.{k}[{i}]') for k in PROBE_FIELDS[1:]}
        if values['inside_opening'] not in (0, 1) or values['ball_speed_mm_s'] < 0:
            fail('probe_observation', '입구 포함 여부는 0/1, 공 속력은 0 이상이어야 합니다.')
    return released


def parse(path: Path, sha256: str, manifest: list) -> Bundle:
    for name in ('meta.json', 'summary.csv'):
        if not (path/name).is_file():
            fail('missing_file', f'{name}이 없습니다. 해당 실행의 파일을 다시 받아주세요.')
    meta = read_json(path/'meta.json')
    rows = csv_rows(path/'summary.csv', FIELDS)
    base = rows[0]
    if any(any(r[k] != base[k] for k in FIELDS[:8]) for r in rows):
        fail('mixed_run', '하나의 summary.csv에 다른 실행·에셋·조건·상태가 섞였습니다.')
    if base['test'] not in PROFILES:
        fail('unsupported_profile', f"{base['test']}: 검사별 지표 명세가 필요한 출력입니다. 현재 검증 프로필은 incline, probe입니다.")
    profile, metric_rules = PROFILES[base['test']]
    if not base['asset_id'] or base['status'] not in STATUSES:
        fail('identity_or_status', '에셋 ID가 비었거나 알 수 없는 실행 상태입니다.')
    seed = integer(base['seed'], 'summary.seed')
    for key in ('run_id', 'test', 'condition'):
        if key in meta and str(meta[key]) != base[key]:
            fail('metadata_mismatch', f'meta.json의 {key}가 summary.csv와 다릅니다.')
    if integer(meta.get('seed'), 'meta.seed') != seed:
        fail('metadata_mismatch', 'meta.seed가 다릅니다.')
    dt = finite(meta.get('timestep'), 'meta.timestep')
    if dt <= 0 or not isinstance(meta.get('mujoco'), str) or not meta['mujoco']:
        fail('missing_environment', '양수 timestep과 MuJoCo 버전이 필요합니다.')
    ah = base['asset_sha256']
    # The shared probe writer exits before hashing when there is no cavity or
    # the source cannot be loaded. Preserve that fact; do not invent an asset hash.
    missing_hash_allowed = base['test'] == 'probe' and STATUSES[base['status']] in ('skipped', 'error')
    if not re.fullmatch('[0-9a-fA-F]{64}', ah) and not (missing_hash_allowed and ah == ''):
        fail('asset_hash', '에셋 SHA-256이 없거나 잘못되었습니다.')
    warnings = []
    if not ah:
        warnings.append('원본 에셋 해시가 미기록되어 있습니다. 이 결과는 동일 에셋 버전으로 합치지 않습니다.')
    if not base['run_id']:
        warnings.append('원본 실행 ID가 없어 가져오기 ID를 부여했습니다. 같은 실행의 수정본 여부는 별도 확인해야 합니다.')
    if not meta.get('git_commit'):
        warnings.append('하네스 commit이 없습니다. 보관된 출력과 어댑터 버전으로 추적합니다.')
    warnings.append('원본에 명시적인 규약 버전·반복 번호·실행 시작/종료 시각이 없습니다. 가져온 시각을 실행 시각으로 대체하지 않습니다.')
    metrics, seen = [], set()
    for row in rows:
        name, raw, unit = row['metric'], row['value'], row['unit']
        if name in seen:
            fail('duplicate_metric', f'{name}: 같은 실행에서 같은 지표가 두 번 나옵니다.')
        seen.add(name)
        if name not in metric_rules or metric_rules[name] != unit:
            fail('metric_or_unit', f'{name}: 단위 {unit!r}를 승인된 지표 명세와 대조해주세요.')
        si_unit, factor = UNITS[unit]
        value, text, valid, reason = None, None, True, None
        if raw.strip().lower() in ('nan', '') or name == 'none':
            valid, reason = False, 'source_missing_or_undefined'
        elif name in TEXT_METRICS or (name == 'mu_applied' and raw == 'mixed'):
            text = raw
        else:
            value = finite(raw, name) * factor
            if unit == 'bool' and value not in (0, 1):
                fail('invalid_boolean', f'{name}: 0 또는 1이어야 합니다.')
        metrics.append({'name': name, 'unit': si_unit, 'value': value, 'text': text,
                        'valid': valid, 'reason': reason, 'raw_value': raw, 'raw_unit': unit})
    if base['status'] in ('ok', 'unsettled', 'diverged'):
        if not (path/'timeseries.csv').is_file():
            fail('missing_file', '시뮬레이션 결과에 timeseries.csv가 없습니다.')
        ts = csv_rows(path/'timeseries.csv', TS_FIELDS)
        if meta.get('timeseries_units') != TS_UNITS:
            fail('timeseries_units', '시계열의 단위 또는 좌표계가 현재 출력 프로필과 다릅니다.')
        prev = -math.inf
        for i, row in enumerate(ts):
            values = [finite(row[k], f'timeseries.{k}[{i}]') for k in TS_FIELDS]
            if values[0] < 0 or values[0] <= prev:
                fail('time_order', '시계열 시간은 0 이상이며 엄격히 증가해야 합니다.')
            prev = values[0]
        if not any(x['path'].endswith('.mp4') for x in manifest):
            warnings.append('영상이 없는 수치 결과입니다. 화면 관찰이 필요한 판정에는 추가 근거가 필요합니다.')
        if base['test'] == 'probe':
            released = validate_probe_series(path/'timeseries_probe.csv', ts)
            if not released:
                warnings.append('공을 놓은 이후의 관측값이 없습니다. 홈 통과 여부를 확인할 수 없습니다.')
    elif base['test'] == 'probe' and any((path/name).exists() for name in ('timeseries.csv', 'timeseries_probe.csv')):
        fail('unexpected_trajectory', '실행 전 중단된 홈 검사에 시계열이 있습니다. 이전 실행 파일이 섞였는지 확인해주세요.')
    asset = meta.get('asset', {})
    if not isinstance(asset, dict):
        fail('invalid_metadata', 'asset은 객체여야 합니다.')
    # The perturbation specification identifies the case; realized poses and predictions
    # belong to the run. Preserve both in raw_meta, never substitute import time for run time.
    excluded = {'run_id', 'seed', 'mujoco', 'python', 'os', 'git_commit', 'error',
                'perturb', 'rest_pose_quat', 'rest_settled', 'prediction'}
    config = {k: v for k, v in meta.items() if k not in excluded}
    config['asset'] = {k:v for k,v in asset.items() if k != 'path'}
    return Bundle(path, sha256, manifest, base['run_id'] or 'import:'+sha256,
                  base['asset_id'], ah.lower() or None, seed, base['test'], base['status'],
                  meta, config, metrics, warnings, base['condition'], profile, metric_rules)


def media_type(name):
    suffix = Path(name).suffix.lower()
    kind = {'.mp4':'video', '.webm':'video', '.png':'screenshot', '.jpg':'screenshot',
            '.csv':'trajectory', '.json':'config_snapshot'}.get(suffix, 'log')
    return kind, mimetypes.guess_type(name)[0] or 'application/octet-stream'
