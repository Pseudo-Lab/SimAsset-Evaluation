"""Measure what a fixed video cadence omits from saved per-step physics metrics.

Frame times are reconstructed from the verified ClipRecorder algorithm and CSV,
not inferred from pixels. The MP4s do not contain simulation-time sidecars.
"""
import argparse
import csv
import json
from pathlib import Path
import unicodedata

import numpy as np

from audit_render_quality import expected_capture_times, read, sha


def analyze(times, penetration_mm, fps):
    times = np.asarray(times, dtype=float)
    pen = np.asarray(penetration_mm, dtype=float)
    if (times.shape != pen.shape or not len(times) or not np.isfinite(times).all()
            or not np.isfinite(pen).all() or (np.diff(times) <= 0).any() or fps <= 0):
        raise ValueError('Finite, increasing time samples and matching metrics are required')
    capture_times = expected_capture_times(times, fps)
    indices = np.searchsorted(times, capture_times)
    if not len(indices):
        raise ValueError('No captured sample times')
    peak = int(np.argmax(pen))
    video_peak = int(indices[np.argmax(pen[indices])])
    nearest = int(np.argmin(np.abs(capture_times - times[peak])))
    return {
        'physics_samples': len(times), 'video_samples': len(indices),
        'peak_penetration_mm': float(pen[peak]), 'peak_time_s': float(times[peak]),
        'max_penetration_at_video_sample_times_mm': float(pen[video_peak]),
        'video_sample_peak_time_s': float(times[video_peak]),
        'nearest_frame_index': nearest, 'nearest_frame_sim_time_s': float(capture_times[nearest]),
        'nearest_frame_pts_s': nearest / fps,
        'peak_underrepresentation_pct': float(100 * (1 - pen[video_peak] / pen[peak])) if pen[peak] > 0 else None,
        'max_pts_to_sim_time_offset_s': float(np.max(np.abs(capture_times - np.arange(len(indices)) / fps))),
        'interpretation': 'Metrics at reconstructed video sample times, not values measured from the video image.',
    }


def batch(root, source):
    benchmark = read(root / 'e3-sw/benchmark.json')
    for name, expected in benchmark['source_files'].items():
        if sha(source / name) != expected:
            raise ValueError('Upstream source differs from experiment: ' + name)
    rows = []
    for record in benchmark['records']:
        folder = root / 'e3-sw' / record['output']
        meta = read(folder / 'meta.json')
        if meta['timeseries_units']['max_pen'] != 'mm (max penetration depth)':
            raise ValueError('Unexpected penetration unit')
        path = folder / 'timeseries.csv'
        if sha(path) != record['timeseries_sha256']:
            raise ValueError('Timeseries changed after measurement')
        with path.open() as f:
            data = list(csv.DictReader(f))
        config = read(root / f'{record["asset"]}-cpu/physics.json')['config']
        result = analyze([r['t'] for r in data], [r['max_pen'] for r in data], config['video']['fps'])
        rows.append({'asset': record['asset'], 'repeat': record['repeat'],
                     'timeseries': str(path), 'timeseries_sha256': sha(path), **result})
    return {'script_sha256': sha(Path(__file__)),
            'recorder_sha256': sha(source / 'common/recorder.py'), 'runs': rows,
            'scope': 'Existing E3 open-loop incline results only. No new simulation or paid GPU run.'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('results', type=Path)
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    output = Path(unicodedata.normalize('NFC', str(args.output)))
    result = batch(args.results.resolve(), args.source.resolve())
    with output.open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
    assert output.name == unicodedata.normalize('NFC', output.name)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
