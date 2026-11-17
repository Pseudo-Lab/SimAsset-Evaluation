"""Reproduce a shared probe bundle without changing or redistributing its source."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
import unicodedata


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seeds', type=int, default=1)
    parser.add_argument('--video', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.seeds <= 10:
        parser.error('--seeds는 1~10입니다.')
    source = args.source.resolve()
    output = Path(unicodedata.normalize('NFC', str(args.output.absolute()))).resolve()
    if output.is_relative_to(source):
        parser.error('원본 밖의 새 출력 폴더를 사용해주세요.')
    before = hashes(source)
    output.mkdir(parents=True, exist_ok=False)
    cases = [(asset, condition, seed)
             for asset in ('mug_cad', 'bowl_cad', 'solid_cyl')
             for condition in ('decomposed', 'single_hull')
             for seed in range(args.seeds)]
    expected = []
    for asset, condition, seed in cases:
        cavity = json.loads((source/'assets/probe_samples'/asset/'meta_asset.json').read_text()).get('cavity')
        expected.append({'path': f'probe/{asset}/file_{condition}_seed{seed}',
                         'asset_id': asset, 'test': 'probe', 'condition': condition, 'seed': seed,
                         'required_artifacts': ['clip_visual.mp4', 'clip_collision.mp4']
                         if args.video and seed == 0 and cavity is not None else []})
    # Persist the complete plan before invoking the harness, so a crashed or
    # missing run remains visible to audit rather than disappearing from the plan.
    (output/'expected.json').write_text(json.dumps({'schema_version': 1, 'runs': expected}, ensure_ascii=False, indent=2)+'\n')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source))
    from common.config import load_config, load_materials
    from tests.probe import run
    import mujoco
    records = []
    previous = Path.cwd()
    try:
        # env_meta() must not claim this review repository is the shared harness commit.
        with tempfile.TemporaryDirectory(prefix='simasset-probe-cwd-') as neutral:
            os.chdir(neutral)
            for asset, condition, seed in cases:
                start = time.perf_counter()
                result = run(source/'assets/probe_samples'/asset, load_config('probe'),
                             seed, condition, materials=load_materials(), out_root=output/'results',
                             video=args.video and seed == 0)
                record = asdict(result)
                record.update(wall_s=time.perf_counter()-start)
                records.append(record)
                print(json.dumps({'asset': asset, 'condition': condition, 'seed': seed,
                                  'status': result.status, 'wall_s': record['wall_s']}, ensure_ascii=False), flush=True)
    finally:
        os.chdir(previous)
    assert hashes(source) == before, 'shared source was changed'
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'origin': 'local_reproduction',
              'environment': {'mujoco': mujoco.__version__, 'python': platform.python_version(),
                              'os': platform.platform()}, 'source_files': before, 'source_unchanged': True,
              'records': records, 'note': '공유 코드의 샘플 재현이며 팀 50개 에셋 결과가 아닙니다.'}
    # Summary metrics may contain NaN. Source CSV retains it; report uses null.
    def clean(v):
        import math
        if isinstance(v, float) and not math.isfinite(v): return None
        if isinstance(v, dict): return {k: clean(x) for k, x in v.items()}
        if isinstance(v, list): return [clean(x) for x in v]
        return v
    (output/'reproduction.json').write_text(json.dumps(clean(report), ensure_ascii=False, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
