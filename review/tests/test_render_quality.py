"""Guard against visually reassuring comparisons of incomparable media."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location('render_quality', Path(__file__).parents[1] / 'scripts/audit_render_quality.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def metadata():
    return dict(width=64, height=64, pix_fmt='yuv420p', avg_frame_rate='30/1', r_frame_rate='30/1')


@pytest.mark.parametrize('change', ['size', 'count', 'shift', 'rate', 'color', 'both_missing_frame'])
def test_refuses_silent_media_alignment(change):
    a, b = metadata(), metadata()
    ta = np.arange(5) / 30
    tb = ta.copy()
    if change == 'size':
        b['width'] = 128
    elif change == 'count':
        tb = tb[:-1]
    elif change == 'shift':
        tb += 1 / 30
    elif change == 'rate':
        b['avg_frame_rate'] = '25/1'
    elif change == 'color':
        b['color_range'] = 'pc'
    else:
        ta[3:] += 1 / 30
        tb = ta.copy()
    with pytest.raises(ValueError):
        audit.require_alignment(a, b, ta, tb)


def test_small_damaged_region_is_not_hidden_by_whole_frame_average():
    a = np.zeros((480, 640, 3), dtype=np.uint8)
    b = a.copy()
    b[64:128, 64:128] = 255
    result = audit.pixel_metrics(a, b)
    assert result['rgb_rmse'] < 31
    assert result['worst_tile'] == dict(rmse=255, x=64, y=64, width=64, height=64)


def test_simulation_time_sampling_not_wall_clock():
    captured = audit.expected_capture_times(np.arange(0, .1, .002), 30)
    np.testing.assert_allclose(captured, [0, .034, .068])


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg required')
def test_actual_decode_and_ssim_counts_every_frame(tmp_path):
    clip = tmp_path / 'clip.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=64x64:rate=30:duration=0.2',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(clip)], check=True)
    result = audit.compare_video(clip, clip, tmp_path / 'match', expected_frames=6)
    assert result['frames'] == result['ssim']['frame_count'] == 6
    assert result['ssim']['all_mean'] == 1
    assert result['rgb_rmse_all_frames'] == 0
    with pytest.raises(ValueError, match='frame count'):
        audit.compare_video(clip, clip, tmp_path / 'wrong', expected_frames=7)
