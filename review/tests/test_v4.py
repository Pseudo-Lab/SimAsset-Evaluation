import csv
import math
from uuid import UUID

import pytest

from simasset_review.bundle import (DROP_PROFILE, FIELDS, INCLINE_V4_PROFILE, PROFILE,
                                    SETTLE_PROFILE, SPIN_PROFILE)
from simasset_review.db import get_run, import_bundle
from conftest import edit_meta


def write_summary(path, test, condition, status, metrics, asset_hash='a'*64):
    run_id = f'{test}-cube-file-{condition}-s0'
    with (path/'summary.csv').open('w', newline='') as f:
        writer = csv.writer(f); writer.writerow(FIELDS)
        for name, value, unit in metrics:
            writer.writerow([run_id, 'cube', asset_hash, test, 'file', condition, 0, status, name, value, unit])
    edit_meta(path/'meta.json', lambda m: m.update(run_id=run_id, test=test, condition=condition,
                                                   git_commit='', git_dirty=None))
    return path


def metrics_of(database, result):
    assert result['status'] == 'imported', result
    detail = get_run(database, UUID(result['run_id']))
    return detail, {m['metric_name']: m for m in detail['metrics']}


def test_v4_incline_uses_its_own_profile_and_new_units(database, bundle, namespace):
    write_summary(bundle, 'incline', 'yaw90', 'ok', [
        ('yaw_deg', '90', 'deg'), ('travel_m', '1.53461', 'm'), ('body_len_slope_mm', '306.9', 'mm'),
        ('travel_body_lengths', '5', ''), ('travel_clamped', '0', 'bool'),
        ('runout_body_lengths', '1.43', ''), ('mu_applied', 'mixed', ''), ('motion_mode', 'sliding', '')])
    detail, metrics = metrics_of(database, import_bundle(database, bundle, namespace, 'fixture'))
    assert detail['protocol_version'] == INCLINE_V4_PROFILE
    assert metrics['yaw_deg']['metric_value'] == pytest.approx(math.pi/2)
    assert metrics['travel_m']['metric_value'] == pytest.approx(1.53461) and metrics['travel_m']['unit'] == 'm'
    assert metrics['body_len_slope_mm']['metric_value'] == pytest.approx(.3069)
    assert metrics['mu_applied']['metric_text'] == 'mixed'
    assert detail['config']['condition'] == 'yaw90' and 'git_dirty' not in detail['config']
    assert detail['raw_meta']['git_dirty'] is None


def test_v3_incline_rules_are_unchanged(database, bundle, namespace):
    # Unique bytes: other tests deliberately corrupt the stored copy of the pristine fixture.
    edit_meta(bundle/'meta.json', lambda m: m.update(fixture_case=namespace))
    result = import_bundle(database, bundle, namespace, 'fixture')
    assert get_run(database, UUID(result['run_id']))['protocol_version'] == PROFILE
    # A v4 metric in an output without the v4 marker is still an unknown field.
    with (bundle/'summary.csv').open('a', newline='') as f:
        csv.writer(f).writerow(['incline-cube-file-ramp45deg-s0', 'cube', 'a'*64, 'incline',
                                'file', 'ramp45deg', 0, 'ok', 'travel_m', '1.5', 'm'])
    assert import_bundle(database, bundle, namespace+'-b', 'fixture')['code'] == 'metric_or_unit'


@pytest.mark.parametrize('test', ['settle', 'drop', 'spin'])
def test_v4_only_tests_require_the_v4_marker(database, bundle, namespace, test):
    write_summary(bundle, test, 'base', 'ok', [('mass_kg', '0.1', 'kg')])
    edit_meta(bundle/'meta.json', lambda m: m.pop('git_dirty'))
    assert import_bundle(database, bundle, namespace, 'fixture')['code'] == 'unsupported_profile'


def test_settle_text_classes_and_rates(database, bundle, namespace):
    write_summary(bundle, 'settle', 'base', 'ok', [
        ('jitter', '2.9e-07', 'mm/s'), ('amplitude', '5.6e-09', 'mm'), ('settle_class', 'still', ''),
        ('settle_class_ko', '정지', ''), ('horizontal_disp_pct_diag', '1.39', '%'), ('tilt_final_deg', '180', 'deg')])
    detail, metrics = metrics_of(database, import_bundle(database, bundle, namespace, 'fixture'))
    assert detail['protocol_version'] == SETTLE_PROFILE
    assert metrics['jitter']['metric_value'] == pytest.approx(2.9e-10) and metrics['jitter']['unit'] == 'm/s'
    assert metrics['settle_class']['metric_text'] == 'still'
    assert metrics['settle_class_ko']['metric_text'] == '정지'
    assert metrics['tilt_final_deg']['metric_value'] == pytest.approx(math.pi)


def test_drop_counts_and_booleans(database, bundle, namespace):
    write_summary(bundle, 'drop', 'tilt30', 'ok', [
        ('drop_height_mm', '1000', 'mm'), ('n_impacts', '5', 'count'), ('toppled', '1', 'bool'),
        ('bounce_height_pct_diag', '0.95', '%'), ('note', 'no floor contact', '')])
    detail, metrics = metrics_of(database, import_bundle(database, bundle, namespace, 'fixture'))
    assert detail['protocol_version'] == DROP_PROFILE
    assert metrics['n_impacts']['metric_value'] == 5 and metrics['n_impacts']['unit'] == 'count'
    assert metrics['drop_height_mm']['metric_value'] == pytest.approx(1)
    assert metrics['toppled']['metric_value'] == 1


def test_spin_undefined_stability_is_not_a_number(database, bundle, namespace):
    write_summary(bundle, 'spin', 'geom_axis_mid', 'ok', [
        ('omega_rev_s', '2', 'rev/s'), ('axis_role', 'mid=max', ''), ('expected_stable', 'undefined', 'bool'),
        ('t_dev_10deg_s', 'nan', 's'), ('momentum_drift_pct', '0.018', '%')])
    detail, metrics = metrics_of(database, import_bundle(database, bundle, namespace, 'fixture'))
    assert detail['protocol_version'] == SPIN_PROFILE
    assert metrics['omega_rev_s']['metric_value'] == pytest.approx(4*math.pi)
    assert metrics['omega_rev_s']['unit'] == 'rad/s'
    assert metrics['axis_role']['metric_text'] == 'mid=max'
    stable = metrics['expected_stable']
    assert stable['valid'] is False and stable['metric_value'] is None and stable['raw_value'] == 'undefined'
    assert metrics['t_dev_10deg_s']['valid'] is False


def test_v3_undefined_value_is_still_rejected(database, bundle, namespace):
    with (bundle/'summary.csv').open('a', newline='') as f:
        csv.writer(f).writerow(['incline-cube-file-ramp45deg-s0', 'cube', 'a'*64, 'incline',
                                'file', 'ramp45deg', 0, 'ok', 'mode_match', 'undefined', 'bool'])
    assert import_bundle(database, bundle, namespace, 'fixture')['code'] == 'invalid_number'


@pytest.mark.parametrize('status,execution', [('not_applicable', 'skipped'), ('missing_inertial', 'error'),
                                              ('error', 'error')])
def test_v4_stopped_runs_keep_status_and_reject_stale_trajectories(database, bundle, namespace, status, execution):
    write_summary(bundle, 'spin', 'geom_axis_min', status, [('note', 'stopped before simulation', '')],
                  asset_hash='' if status == 'error' else 'a'*64)
    stale = import_bundle(database, bundle, namespace, 'fixture')
    assert stale['code'] == 'unexpected_trajectory'
    (bundle/'timeseries.csv').unlink()
    detail, _ = metrics_of(database, import_bundle(database, bundle, namespace, 'fixture'))
    assert detail['execution_status'] == execution and detail['source_status'] == status
    assert detail['asset_version'] == (None if status == 'error' else 'a'*64)


def test_v4_completed_run_still_requires_a_hash(database, bundle, namespace):
    write_summary(bundle, 'drop', 'base', 'ok', [('mass_kg', '0.1', 'kg')], asset_hash='')
    assert import_bundle(database, bundle, namespace, 'fixture')['code'] == 'asset_hash'


def test_v4_dirty_harness_is_warned(database, bundle, namespace):
    write_summary(bundle, 'settle', 'base', 'ok', [('mass_kg', '0.1', 'kg')])
    edit_meta(bundle/'meta.json', lambda m: m.update(git_commit='abc1234', git_dirty=True))
    result = import_bundle(database, bundle, namespace, 'fixture')
    assert result['status'] == 'imported'
    assert any('commit하지 않은 수정' in w for w in result['warnings'])
