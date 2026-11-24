import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from simasset_review.batch import audit


def test_predeclared_plan_survives_first_run_crash(tmp_path, monkeypatch):
    source, output = tmp_path/'source', tmp_path/'output'
    for asset in ('mug_cad', 'bowl_cad', 'solid_cyl'):
        folder = source/'assets/probe_samples'/asset
        folder.mkdir(parents=True)
        (folder/'meta_asset.json').write_text(json.dumps({'cavity': None if asset == 'solid_cyl' else {}}))
    script = Path(__file__).parents[1]/'scripts/probe_check.py'
    spec = importlib.util.spec_from_file_location('probe_runner_check', script)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    def interrupted(*args, **kwargs):
        plan = json.loads((output/'expected.json').read_text())
        assert len(plan['runs']) == 6
        assert len([r for r in plan['runs'] if r['required_artifacts']]) == 4
        raise RuntimeError('simulated interruption before first result')

    monkeypatch.setitem(sys.modules, 'common.config', SimpleNamespace(load_config=lambda _: {}, load_materials=lambda: {}))
    monkeypatch.setitem(sys.modules, 'tests.probe', SimpleNamespace(run=interrupted))
    monkeypatch.setitem(sys.modules, 'mujoco', SimpleNamespace(__version__='test'))
    monkeypatch.setattr(sys, 'argv', ['probe_check', '--source', str(source), '--output', str(output), '--video'])
    monkeypatch.setattr(sys, 'path', sys.path.copy())
    monkeypatch.setattr(sys, 'dont_write_bytecode', sys.dont_write_bytecode)
    original_cwd = Path.cwd()
    with pytest.raises(RuntimeError, match='simulated interruption'):
        runner.main()
    assert Path.cwd() == original_cwd
    result = audit(output/'results', output/'expected.json')
    assert result['expected_count'] == result['invalid_count'] == 6
    assert all(r['code'] == 'missing_result' for r in result['records'])
    assert result['expected_coverage_verified'] is False
