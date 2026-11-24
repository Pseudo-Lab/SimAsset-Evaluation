"""Compare equivalent experiments; numerical agreement is not an asset verdict."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np


def read(path):
    return json.loads(Path(path).read_text())


def checked_states(folder, meta):
    path=folder/'states.npz'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=meta['states_sha256']:
        raise ValueError('State file changed after measurement')
    return np.load(path,allow_pickle=False)


def compare_physics(left, right, position_m=1e-6, quaternion=1e-6):
    a,b=read(left/'physics.json'),read(right/'physics.json')
    for key in ('asset_sha256','seed','steps','config','state_enum','state_size'):
        if a[key]!=b[key]: raise ValueError(f'Cannot compare different {key}')
    if a['environment']['mujoco']!=b['environment']['mujoco']:
        raise ValueError('MuJoCo versions differ')
    if a.get('source_files')!=b.get('source_files'):
        raise ValueError('Source manifests differ; rerun baseline using the same wrapper')
    x,y=checked_states(left,a),checked_states(right,b)
    if x['states'].shape!=y['states'].shape or not np.array_equal(x['frame_times'],y['frame_times']):
        raise ValueError('Sampling times or state shape differ')
    if not np.allclose(x['initial'],y['initial'],rtol=0,atol=1e-12):
        raise ValueError('Initial states differ: report this separately before comparing trajectories')
    # This first adapter is one free body: time, xyz, quaternion, velocities.
    if a.get('nq',7)!=7: raise ValueError('Add a joint-specific unit adapter before comparing another model')
    px=x['states'][:,1:4];py=y['states'][:,1:4]
    qx=x['states'][:,4:8];qy=y['states'][:,4:8]
    if not all(np.isfinite(z).all() for z in (px,py,qx,qy)):
        raise ValueError('Non-finite trajectory')
    # q and -q represent the same orientation.
    qdiff=np.minimum(np.max(np.abs(qx-qy),axis=1),np.max(np.abs(qx+qy),axis=1))
    pmax=float(np.max(np.abs(px-py)));qmax=float(np.max(qdiff))
    final_a=np.asarray(a['records'][0]['final_qpos']);final_b=np.asarray(b['records'][0]['final_qpos'])
    return {'same_conditions':True,'frames':len(px),'position_max_abs_m':pmax,
            'quaternion_max_component_difference':qmax,
            'final_qpos_raw_max_abs':float(np.max(np.abs(final_a-final_b))),
            'tolerance':{'position_m':position_m,'quaternion_component':quaternion},
            'within_numerical_tolerance':pmax<=position_m and qmax<=quaternion,
            'asset_acceptance':'not_evaluated',
            'note':'Diagnostic tolerances are a personal comparison draft, not team acceptance thresholds.'}


def compare_render(left,right):
    from PIL import Image
    a,b=read(left/'render.json'),read(right/'render.json')
    for key in ('states_sha256','model_sha256'):
        if a[key]!=b[key]: raise ValueError(f'Render inputs differ: {key}')
    if a['physics_steps'] or b['physics_steps']: raise ValueError('E2 must not advance physics')
    rows=[]
    afiles={p.name for p in left.glob('frame-*.png')};bfiles={p.name for p in right.glob('frame-*.png')}
    if not afiles or afiles!=bfiles: raise ValueError('Matching sampled frames are required')
    for name in sorted(afiles):
        x=np.asarray(Image.open(left/name).convert('RGB'),dtype=float)
        y=np.asarray(Image.open(right/name).convert('RGB'),dtype=float)
        if x.shape!=y.shape: raise ValueError('Image dimensions differ')
        rows.append({'frame':name,'rgb_rmse_0_255':float(np.sqrt(np.mean((x-y)**2))),
                     'rgb_max_abs_0_255':float(np.max(np.abs(x-y)))})
    return {'same_saved_states':True,'renderers':[a['renderer'],b['renderer']],
            'sampled_frames':rows,'physical_failure_from_pixels':False,
            'timing_records':[a['records'],b['records']],
            'note':'Pixel differences are visual diagnostics. Review the complete clips separately.'}


def compare_source(left,right):
    a,b=read(left/'benchmark.json'),read(right/'benchmark.json')
    for key in ('source_files','seed','video','repeats'):
        if a[key]!=b[key]: raise ValueError(f'Source batch conditions differ: {key}')
    if a['environment']['mujoco']!=b['environment']['mujoco']: raise ValueError('MuJoCo versions differ')
    key=lambda x:(x['asset'],x['repeat'],x['seed'])
    aa={key(x):x for x in a['records']};bb={key(x):x for x in b['records']}
    if aa.keys()!=bb.keys(): raise ValueError('Batch members differ')
    rows=[]
    def metrics(path):
        with path.open(newline='') as f:
            return {x['metric']:(x['value'],x['unit']) for x in csv.DictReader(f)}
    for k,x in aa.items():
        y=bb[k];mx=metrics(left/x['output']/'summary.csv');my=metrics(right/y['output']/'summary.csv')
        rows.append({'asset':k[0],'repeat':k[1],'status':[x['status'],y['status']],
                     'status_equal':x['status']==y['status'],
                     'timeseries_exact_equal':x['timeseries_sha256']==y['timeseries_sha256'],
                     'metric_differences':{name:[mx.get(name),my.get(name)] for name in mx.keys()|my.keys()
                                           if mx.get(name)!=my.get(name)},
                     'wall_s':[x['wall_s'],y['wall_s']]})
    return {'same_conditions':True,'runs':rows,'asset_acceptance':'not_evaluated',
            'note':'Raw numeric/text differences remain visible; source execution status is not a human verdict.'}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('kind',choices=['physics','render','source'])
    ap.add_argument('left',type=Path);ap.add_argument('right',type=Path);ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args();result={'physics':compare_physics,'render':compare_render,'source':compare_source}[args.kind](args.left,args.right)
    with args.output.open('x') as f: json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__': main()
