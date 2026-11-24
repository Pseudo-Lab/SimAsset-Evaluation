import hashlib
import json
import shutil
import sys

import pytest

from simasset_review.batch import audit, discover
from simasset_review.bundle import InvalidBundle
from simasset_review.cli import main
from conftest import edit_csv


def expected(path, names):
    path.write_text(json.dumps({'schema_version': 1, 'runs': [
        {'path': n, 'asset_id': 'cube', 'test': 'incline', 'seed': 0, 'condition': 'ramp45deg'}
        for n in names]}))
    return path


def test_audit_checks_expected_missing_run_and_summary_without_changing_sources(bundle, tmp_path):
    root = tmp_path/'batch'; root.mkdir()
    shutil.copytree(bundle, root/'complete')
    shutil.copytree(bundle, root/'partial')
    (root/'partial'/'summary.csv').unlink()
    plan = expected(tmp_path/'expected.json', ['complete', 'partial', 'absent'])
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    report = audit(root, plan)
    rows = {r['path']: r for r in report['records']}
    assert report['valid_count'] == 1 and report['invalid_count'] == 2
    assert report['ready_for_import'] is False and report['expected_coverage_verified'] is False
    assert rows['partial']['code'] == 'missing_file'
    assert rows['absent']['code'] == 'missing_result'
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    assert root/'partial' in discover([root], True)


def test_audit_without_expected_plan_does_not_claim_submission_completeness(bundle):
    report = audit(bundle)
    assert report['ready_for_import'] is True
    assert report['expected_coverage_verified'] is False
    assert report['expected_count'] is None


def test_audit_expected_identity_artifacts_and_unknown_folders(bundle, tmp_path):
    root = tmp_path/'batch'; root.mkdir(); shutil.copytree(bundle, root/'one')
    plan = expected(tmp_path/'plan.json', ['one'])
    assert audit(root, plan)['expected_coverage_verified'] is True
    data = json.loads(plan.read_text()); data['runs'][0]['required_artifacts'] = ['clip_visual.mp4']
    plan.write_text(json.dumps(data))
    assert audit(root, plan)['records'][0]['code'] == 'missing_artifact'
    data['runs'][0]['required_artifacts'] = []; data['runs'][0]['asset_id'] = 'different'
    plan.write_text(json.dumps(data))
    assert audit(root, plan)['records'][0]['code'] == 'expected_identity'
    expected(plan, ['one']); shutil.copytree(bundle, root/'two')
    assert audit(root, plan)['records'][1]['code'] == 'unexpected_result'


def test_audit_surfaces_duplicate_and_conflicting_source_ids(bundle, tmp_path):
    root = tmp_path/'batch'; root.mkdir()
    shutil.copytree(bundle, root/'one'); shutil.copytree(bundle, root/'two')
    assert audit(root)['records'][1]['code'] == 'duplicate_run'
    edit_csv(root/'two'/'summary.csv', lambda r: r[1].update(value='9'))
    assert audit(root)['records'][1]['code'] == 'conflicting_run'


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'one/../two', 'one\\two', '.'])
def test_expected_plan_rejects_paths_outside_result_folder(tmp_path, name):
    plan = expected(tmp_path/'plan.json', [name])
    with pytest.raises(InvalidBundle, match='경로'):
        audit(tmp_path/'batch', plan)


def test_audit_rejects_symlink_directory_without_traversal(bundle, tmp_path):
    root=tmp_path/'batch'; root.mkdir(); (root/'linked').symlink_to(bundle, target_is_directory=True)
    report=audit(root)
    assert report['records'][0]['code']=='symlink'


def test_audit_cli_does_not_require_a_database(bundle, monkeypatch, capsys):
    monkeypatch.setattr('simasset_review.cli.Settings.load', lambda: pytest.fail('audit must not open the DB'))
    monkeypatch.setattr(sys, 'argv', ['simasset-review', 'audit', str(bundle)])
    main()
    assert json.loads(capsys.readouterr().out)['ready_for_import'] is True


def test_recursive_import_reports_incomplete_results(database, bundle, tmp_path, namespace, monkeypatch, capsys):
    root=tmp_path/'batch'; root.mkdir()
    shutil.copytree(bundle, root/'one'); shutil.copytree(bundle, root/'two')
    (root/'two'/'summary.csv').unlink()
    monkeypatch.setattr('simasset_review.cli.Settings.load',lambda:database)
    monkeypatch.setattr(sys,'argv',['simasset-review','import',str(root),'--recursive',
                                  '--namespace',namespace,'--origin','fixture'])
    with pytest.raises(SystemExit) as error: main()
    assert error.value.code == 2
    rows=json.loads(capsys.readouterr().out)
    assert [r['status'] for r in rows] == ['imported','invalid']
