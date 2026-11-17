import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[1]


def script(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


compare=script('compare_benchmarks');guard=script('azure_guard')


def physics_folder(path,delta=0,asset='a'):
    path.mkdir();states=np.zeros((3,14));states[:,0]=[0,.034,.066];states[:,4]=1
    initial=states[0].copy();states[1:,1]+=delta
    np.savez(path/'states.npz',states=states,initial=initial,frame_times=states[:,0])
    meta={'asset_sha256':asset,'seed':0,'steps':4000,'config':{'timestep':.002},
          'state_enum':8223,'state_size':14,'nq':7,'environment':{'mujoco':'3.17.0'},
          'source_files':{'a.py':'hash'},'states_sha256':hashlib.sha256((path/'states.npz').read_bytes()).hexdigest(),
          'records':[{'final_qpos':states[-1,1:8].tolist()}]}
    (path/'physics.json').write_text(json.dumps(meta));return path


def test_physics_tolerance_is_not_a_verdict(tmp_path):
    a=physics_folder(tmp_path/'a');b=physics_folder(tmp_path/'b',delta=2e-6)
    r=compare.compare_physics(a,b)
    assert not r['within_numerical_tolerance'] and r['asset_acceptance']=='not_evaluated'
    assert r['position_max_abs_m']==pytest.approx(2e-6)


def test_incompatible_and_modified_trajectories_are_rejected(tmp_path):
    a=physics_folder(tmp_path/'a');b=physics_folder(tmp_path/'b',asset='other')
    with pytest.raises(ValueError,match='asset'): compare.compare_physics(a,b)
    with (a/'states.npz').open('ab') as f: f.write(b'tampered')
    with pytest.raises(ValueError,match='changed'): compare.compare_physics(a,a)


def test_render_compares_same_inputs_and_reports_pixel_difference(tmp_path):
    a,b=tmp_path/'a',tmp_path/'b'
    for path,value in [(a,0),(b,3)]:
        path.mkdir();(path/'render.json').write_text(json.dumps({'states_sha256':'s','model_sha256':'m',
              'physics_steps':0,'records':[],'renderer':path.name}))
        Image.fromarray(np.full((4,4,3),value,dtype=np.uint8)).save(path/'frame-0.png')
    result=compare.compare_render(a,b)
    assert result['sampled_frames'][0]['rgb_rmse_0_255']==3
    assert not result['physical_failure_from_pixels']
    (b/'render.json').write_text((b/'render.json').read_text().replace('"s"','"different"'))
    with pytest.raises(ValueError,match='inputs differ'): compare.compare_render(a,b)


def test_azure_budget_gate_and_explicit_identity():
    c=json.loads((ROOT/'azure-lab.example.json').read_text())
    with pytest.raises(ValueError,match='authorization'): guard.validate_config(c,paid=True)
    c['approval']={'approved':True,'human_reference':'test fixture, never real approval','max_hours':1,
                   'cap_usd':2,'vm_hourly_usd':.526,'reserved_non_compute_usd':1}
    guard.validate_config(c,paid=True)
    c['approval']['cap_usd']=1
    with pytest.raises(ValueError,match='budget'): guard.validate_config(c,paid=True)
    vm={'id':guard.expected_vm(c),'tags':{'purpose':guard.OWNER},'location':c['location'],
        'hardwareProfile':{'vmSize':c['vm_size']}}
    guard.verify_vm(c,vm)
    vm['id']=vm['id'].replace('00000000-0000-0000-0000-000000000000','11111111-1111-1111-1111-111111111111')
    with pytest.raises(ValueError,match='identity'): guard.verify_vm(c,vm)


def test_azure_cli_never_uses_global_subscription(monkeypatch):
    calls=[]
    class Result: stdout='{"ok":true}'
    def fake(argv,**kwargs): calls.append(argv);return Result()
    monkeypatch.setattr(guard.subprocess,'run',fake)
    c=json.loads((ROOT/'azure-lab.example.json').read_text())
    assert guard.az(c,'account','show')=={'ok':True}
    assert calls[0][calls[0].index('--subscription')+1]==c['subscription_id']


@pytest.mark.parametrize('inventory_failure',[False,True])
def test_azure_command_failure_still_deallocates_only_owned_vm(tmp_path,monkeypatch,inventory_failure):
    c=json.loads((ROOT/'azure-lab.example.json').read_text())
    c['approval']={'approved':True,'human_reference':'isolated test fixture','max_hours':1,
                   'cap_usd':2,'vm_hourly_usd':.526,'reserved_non_compute_usd':1}
    config=tmp_path/'config.json';config.write_text(json.dumps(c));evidence=tmp_path/'result.json';calls=[]
    def fake_az(config,*args):
        calls.append(args)
        if inventory_failure and args[:2]==('resource','list') and sum(x[:2]==('resource','list') for x in calls)>1:
            raise RuntimeError('network unavailable during retained-resource check')
        if args[:2]==('account','show'): return {'id':c['subscription_id'],'tenantId':c['tenant_id'],'state':'Enabled'}
        if args[:2]==('group','exists'): return True
        if args[:2]==('vm','show'):
            return {'id':guard.expected_vm(c),'tags':{'purpose':guard.OWNER},'location':c['location'],
                    'hardwareProfile':{'vmSize':c['vm_size']}}
        if args[:2]==('vm','get-instance-view'):return {'instanceView':{'statuses':[{'code':'PowerState/deallocated'}]}}
        return []
    def failure(*args,**kwargs): raise guard.subprocess.TimeoutExpired('test',1)
    monkeypatch.setattr(guard,'az',fake_az);monkeypatch.setattr(guard.subprocess,'run',failure)
    monkeypatch.setattr('sys.argv',['azure_guard','run','--config',str(config),'--evidence',str(evidence),'--command','never-executed'])
    with pytest.raises(RuntimeError if inventory_failure else guard.subprocess.TimeoutExpired): guard.main()
    assert ('vm','deallocate','--ids',guard.expected_vm(c)) in calls
    result=json.loads(evidence.read_text());assert result['deallocated']
    assert 'TimeoutExpired' in result['command_error']
    assert ('remaining_resources_error' if inventory_failure else 'remaining_resources') in result


def test_gpu_driver_preflight_failure_is_recorded(tmp_path,monkeypatch):
    runner=script('cloud_benchmark')
    def missing(*args,**kwargs): raise FileNotFoundError('nvidia-smi unavailable')
    monkeypatch.setattr(runner.subprocess,'run',missing)
    with (tmp_path/'samples.csv').open('w') as log:
        with pytest.raises(FileNotFoundError): runner.start_gpu_monitor(tmp_path,{'status':'running'},log)
    result=json.loads((tmp_path/'manifest.json').read_text())
    assert result['status']=='failed' and 'GPU preflight' in result['error']


def test_source_comparison_keeps_missing_and_zero_distinct(tmp_path):
    folders=[]
    for name,value in [('a','nan'),('b','0')]:
        folder=tmp_path/name;folder.mkdir();(folder/'out').mkdir()
        (folder/'out/summary.csv').write_text('metric,value,unit\npeak_pen,'+value+',mm\n')
        (folder/'benchmark.json').write_text(json.dumps({'source_files':{},'seed':0,'video':True,'repeats':1,
          'environment':{'mujoco':'3.17.0'},'records':[{'asset':'cube','repeat':0,'seed':0,'output':'out',
          'status':'ok','timeseries_sha256':'same','wall_s':1}]}));folders.append(folder)
    r=compare.compare_source(*folders)
    assert r['runs'][0]['metric_differences']['peak_pen']==[('nan','mm'),('0','mm')]
    assert r['asset_acceptance']=='not_evaluated'
