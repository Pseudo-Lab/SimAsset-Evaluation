import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from audit_capture_sampling import analyze


def test_transient_penetration_between_video_frames_is_visible_in_audit():
    t = np.arange(0, .1, .002)
    pen = np.zeros_like(t)
    pen[5], pen[17] = 4, 1  # .010 s peak is omitted; .034 s is recorded.
    result = analyze(t, pen, 30)
    assert result['peak_penetration_mm'] == 4
    assert result['max_penetration_at_video_sample_times_mm'] == 1
    assert result['peak_underrepresentation_pct'] == 75


def test_zero_penetration_does_not_become_nan_or_infinite_ratio():
    result = analyze([0, .002, .004], [0, 0, 0], 30)
    assert result['peak_underrepresentation_pct'] is None


@pytest.mark.parametrize('times,pen', [([0, .1], [0, float('nan')]), ([0, 0], [1, 2]), ([], [])])
def test_missing_or_ambiguous_physics_samples_are_rejected(times, pen):
    with pytest.raises(ValueError):
        analyze(times, pen, 30)
