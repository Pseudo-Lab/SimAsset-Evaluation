"""Compare every decoded frame without resizing, frame dropping, or time alignment.

Diagnostics measure disagreement, not physical correctness or human/AI verdict parity.
The batch command accepts the immutable cloud_benchmark.py result directory.
Requires FFmpeg/ffprobe on PATH and the project's benchmark dependencies.
"""
from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unicodedata

import numpy as np
from PIL import Image


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def probe(path):
    data = json.loads(command([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_streams',
        '-show_frames', '-show_entries',
        'stream=width,height,codec_name,pix_fmt,avg_frame_rate,r_frame_rate,time_base,duration,nb_frames,color_range,color_space,color_transfer,color_primaries:frame=best_effort_timestamp_time',
        '-of', 'json', str(path),
    ]))
    stream, = data['streams']
    pts = np.array([float(f['best_effort_timestamp_time']) for f in data['frames']])
    if not len(pts) or not np.isfinite(pts).all() or (np.diff(pts) <= 0).any():
        raise ValueError('Missing or non-monotonic frame timestamps')
    if 'nb_frames' in stream and int(stream['nb_frames']) != len(pts):
        raise ValueError('Container frame count disagrees with decoded timestamps')
    return stream, pts


def require_alignment(a, b, ta, tb):
    for key in ('width', 'height', 'pix_fmt', 'color_range', 'color_space',
                'color_transfer', 'color_primaries'):
        if a.get(key) != b.get(key):
            raise ValueError(f'Video metadata differs: {key}')
    for key in ('avg_frame_rate', 'r_frame_rate'):
        if Fraction(a[key]) <= 0 or Fraction(a[key]) != Fraction(b[key]):
            raise ValueError(f'Video rate differs: {key}')
    if ta.shape != tb.shape or not np.allclose(ta, tb, rtol=0, atol=1e-6):
        raise ValueError('Frame counts or timestamps differ; refusing implicit alignment')
    # Reject a matching pair that shares gaps or variable frame timing as well.
    expected = ta[0] + np.arange(len(ta)) / float(Fraction(a['avg_frame_rate']))
    if not np.allclose(ta, expected, rtol=0, atol=1e-6):
        raise ValueError('Frame timestamps have gaps or variable cadence')


@contextmanager
def decoded(path, width, height):
    # Temporary stderr avoids a pipe deadlock on corrupted media; only two frames
    # are held in memory. -fps_mode passthrough prevents implicit frame duplication.
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen([
            'ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-threads', '1',
            '-i', str(path), '-map', '0:v:0', '-an', '-sn', '-dn',
            '-fps_mode', 'passthrough', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-',
        ], stdout=subprocess.PIPE, stderr=errors)

        def frames():
            nbytes = width * height * 3
            while True:
                buf = proc.stdout.read(nbytes)
                if not buf:
                    break
                if len(buf) != nbytes:
                    raise ValueError('Partial decoded frame')
                yield np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 3)
            if proc.wait() != 0:
                errors.seek(0)
                raise ValueError('Video decode failed: ' + errors.read().decode(errors='replace')[-1000:])

        try:
            yield frames()
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


def pixel_metrics(a, b, tile=64):
    if a.shape != b.shape or a.ndim != 3 or a.shape[2] != 3:
        raise ValueError('Expected matching RGB frames')
    delta = a.astype(np.float32) - b.astype(np.float32)
    squared = np.mean(delta * delta, axis=2)
    worst = {'rmse': -1.0}
    for y in range(0, a.shape[0], tile):
        for x in range(0, a.shape[1], tile):
            part = squared[y:y + tile, x:x + tile]
            rmse = float(np.sqrt(np.mean(part)))
            if rmse > worst['rmse']:
                worst = {'rmse': rmse, 'x': x, 'y': y,
                         'width': part.shape[1], 'height': part.shape[0]}
    return {
        'rgb_rmse': float(np.sqrt(np.mean(squared))),
        'rgb_mae': float(np.mean(np.abs(delta))),
        'max_channel_difference': int(np.max(np.abs(delta))),
        'pixel_fraction_any_channel_gt_10': float(np.mean(np.max(np.abs(delta), axis=2) > 10)),
        'worst_tile': worst,
    }


def expected_capture_times(times, fps):
    """Mirror the documented simulation-time cadence, not the decoded video."""
    next_t, captured = 0.0, []
    for time in times:
        if time + 1e-9 >= next_t:
            captured.append(time)
            next_t += 1.0 / fps
    return np.array(captured)


def ssim(left, right, count):
    # Inputs have already passed metadata and full PTS alignment checks. No
    # setpts/scale/fps correction is permitted here; reject any count mismatch.
    output = command([
        'ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-threads', '1',
        '-i', str(left), '-threads', '1', '-i', str(right),
        '-filter_complex', '[0:v][1:v]ssim=stats_file=-:shortest=1:repeatlast=0',
        '-an', '-f', 'null', '-',
    ])
    values = []
    for line in output.splitlines():
        row = dict(item.split(':', 1) for item in line.split() if ':' in item)
        if 'All' in row:
            values.append(float(row['All']))
    if len(values) != count or not np.isfinite(values).all():
        raise ValueError('SSIM did not compare exactly the expected frame count')
    return {'all_mean': float(np.mean(values)), 'all_min': min(values),
            'frame_count': count, 'pixel_format': 'native matching format'}


def compare_video(left, right, out, expected_frames=None):
    a, ta = probe(left)
    b, tb = probe(right)
    require_alignment(a, b, ta, tb)
    count = len(ta)
    if expected_frames is not None and count != expected_frames:
        raise ValueError('Video frame count differs from render record')
    out.mkdir(parents=True, exist_ok=False)
    rows, worst_frames = [], None
    worst_score = -1
    with decoded(left, a['width'], a['height']) as fa, decoded(right, b['width'], b['height']) as fb:
        for i in range(count):
            x, y = next(fa, None), next(fb, None)
            if x is None or y is None:
                raise ValueError('Video ended before all timestamped frames were decoded')
            row = {'index': i, 'pts_s': float(ta[i]), **pixel_metrics(x, y)}
            rows.append(row)
            if row['worst_tile']['rmse'] > worst_score:
                worst_score = row['worst_tile']['rmse']
                worst_frames = x.copy(), y.copy(), i
        if next(fa, None) is not None or next(fb, None) is not None:
            raise ValueError('Unexpected extra decoded frames')
    x, y, index = worst_frames
    Image.fromarray(x).save(out / 'worst-local-left.png')
    Image.fromarray(y).save(out / 'worst-local-right.png')
    summary = {
        'left': str(left), 'right': str(right),
        'sha256': [sha(left), sha(right)], 'streams': [a, b],
        'frames': count, 'pts_first_s': float(ta[0]), 'pts_last_s': float(ta[-1]),
        'aligned': True,
        'rgb_rmse_all_frames': float(np.sqrt(np.mean([r['rgb_rmse'] ** 2 for r in rows]))),
        'rgb_rmse_max_frame': max(r['rgb_rmse'] for r in rows),
        'pixel_fraction_gt_10_mean': float(np.mean([r['pixel_fraction_any_channel_gt_10'] for r in rows])),
        'worst_local_frame': rows[index],
        'ssim': ssim(left, right, count),
    }
    (out / 'frames.json').write_text(json.dumps(rows, indent=2, allow_nan=False) + '\n')
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
    return summary


def batch(root, out):
    from compare_benchmarks import compare_source

    out.mkdir(parents=True, exist_ok=False)
    comparisons, pairs, capture_timing = [], [], []
    source = compare_source(root / 'e3-sw', root / 'e3-gpu')
    for row in source['runs']:
        if not row['status_equal'] or not row['timeseries_exact_equal'] or row['metric_differences']:
            raise ValueError('E3 physics differs; visual comparison alone cannot isolate rendering')
    for cpu in sorted(root.glob('*-cpu/physics.json')):
        asset = cpu.parent.name.removesuffix('-cpu')
        physics = read(cpu)
        left, right = root / f'{asset}-sw', root / f'{asset}-gpu'
        a, b = read(left / 'render.json'), read(right / 'render.json')
        for filename, key in [('states.npz', 'states_sha256'), ('model.mjb', 'model_sha256')]:
            actual = sha(cpu.parent / filename)
            if not (actual == physics[key] == a[key] == b[key]):
                raise ValueError(f'E2 input hash mismatch: {asset}/{filename}')
        if a['physics_steps'] or b['physics_steps']:
            raise ValueError('E2 unexpectedly advances physics')
        if a['environment']['mujoco'] != b['environment']['mujoco']:
            raise ValueError('E2 MuJoCo versions differ')
        ar = {r['repeat']: r for r in a['records']}
        br = {r['repeat']: r for r in b['records']}
        if not ar or ar.keys() != br.keys():
            raise ValueError('E2 repeats differ')
        for rep, record in ar.items():
            if record['frames'] != br[rep]['frames']:
                raise ValueError('E2 recorded frame counts differ')
            pairs.append((f'E2-{asset}-{rep}', left / f'replay-{rep}.mp4',
                          right / f'replay-{rep}.mp4', record['frames']))
    records = read(root / 'e3-sw/benchmark.json')['records']
    for record in records:
        relative = Path(record['output'])
        for side in ('sw', 'gpu'):
            actual = sha(root / f'e3-{side}' / relative / 'timeseries.csv')
            if actual != record['timeseries_sha256']:
                raise ValueError('E3 stored timeseries changed after experiment')
        with (root / 'e3-sw' / relative / 'timeseries.csv').open() as f:
            times = np.array([float(r['t']) for r in csv.DictReader(f)])
        config = read(root / f'{record["asset"]}-cpu/physics.json')['config']
        fps = config['video']['fps']
        captured = expected_capture_times(times, fps)
        offsets = captured - np.arange(len(captured)) / fps
        capture_timing.append({
            'asset': record['asset'], 'repeat': record['repeat'],
            'physics_rows': len(times), 'expected_video_frames': len(captured),
            'video_rate_hz': fps, 'physics_rate_hz': 1.0 / config['timestep'],
            'max_simulation_time_offset_s': float(np.max(np.abs(offsets))),
            'note': 'Reconstructed from immutable CSV times and verified recorder logic; original MP4 has no per-frame simulation timestamp sidecar.',
        })
        for kind in ('visual', 'collision'):
            filename = f'clip_{kind}.mp4'
            pairs.append((f'E3-{record["asset"]}-{record["repeat"]}-{kind}',
                          root / 'e3-sw' / relative / filename,
                          root / 'e3-gpu' / relative / filename, len(captured)))
    observed = {p.resolve() for _, left, right, _ in pairs for p in (left, right)}
    if not pairs or observed != {p.resolve() for p in root.rglob('*.mp4')}:
        raise ValueError('Unpaired or missing videos in the input result folder')
    for name, left, right, expected in pairs:
        result = compare_video(left, right, out / name, expected)
        comparisons.append({'name': name, **result})
        print(f'{name}: {result["frames"]} frames; RMSE={result["rgb_rmse_all_frames"]:.4f}; SSIM={result["ssim"]["all_mean"]:.6f}', flush=True)
    result = {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source_root': str(root), 'script_sha256': sha(Path(__file__)),
        'ffmpeg_version': command(['ffmpeg', '-version']).splitlines()[0],
        'pairs': len(comparisons), 'videos': len(observed),
        'compared_frame_pairs': sum(c['frames'] for c in comparisons),
        'e3_physics_comparison': source, 'capture_timing': capture_timing, 'comparisons': comparisons,
        'interpretation': 'Pixel and SSIM disagreement diagnostics, not a ground-truth image quality score or an asset verdict. No rescaling or temporal realignment.',
    }
    (out / 'audit.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('results', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    output = Path(unicodedata.normalize('NFC', str(args.output))).resolve()
    result = batch(args.results.resolve(), output)
    if any(unicodedata.normalize('NFC', p.name) != p.name for p in output.rglob('*')):
        raise ValueError('A generated output filename is not NFC')
    print(json.dumps({k: result[k] for k in ('pairs', 'videos', 'compared_frame_pairs')}))


if __name__ == '__main__':
    main()
