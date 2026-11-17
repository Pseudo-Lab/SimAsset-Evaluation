"""Run E1, E2-SW/GPU, E3-SW/GPU on one pre-provisioned Linux GPU machine.

No cloud resources, drivers or packages are installed by this runner. uv sync
--locked --extra benchmark and the approved driver setup are prerequisites.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def start_gpu_monitor(out,record,gpu_log):
    try:
        smi=subprocess.run(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv'],
                           text=True,capture_output=True,check=True,timeout=15)
        (out/'gpu-inventory.csv').write_text(smi.stdout)
        return subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,name,utilization.gpu,memory.used',
                                 '--format=csv','-l','1'],stdout=gpu_log,stderr=subprocess.DEVNULL)
    except (OSError,subprocess.SubprocessError) as e:
        record.update(status='failed',error=f'GPU preflight: {type(e).__name__}: {e}',
                      finished_at=datetime.now(timezone.utc).isoformat())
        (out/'manifest.json').write_text(json.dumps(record,indent=2))
        raise


def run(args,backend,log,timeout):
    env=os.environ.copy();env['MUJOCO_GL']=backend
    if backend=='osmesa': env['LIBGL_ALWAYS_SOFTWARE']='1'
    else: env.pop('LIBGL_ALWAYS_SOFTWARE',None)
    with log.open('x') as f:
        subprocess.run([sys.executable,*map(str,args)],env=env,stdout=f,stderr=subprocess.STDOUT,
                       check=True,timeout=timeout)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--assets',nargs='+',default=['block_mu03','tall_box','blob_mesh'])
    ap.add_argument('--baseline',type=Path,help='Local baseline folders named <asset>-cpu')
    ap.add_argument('--max-minutes',type=int,default=30)
    args=ap.parse_args()
    if platform.system()!='Linux': raise SystemExit('Linux GPU 비교용입니다. Mac은 benchmark.py를 사용합니다.')
    if not 1<=args.max_minutes<=180: ap.error('max-minutes: 1..180')
    args.source=args.source.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    start=time.monotonic();deadline=start+args.max_minutes*60
    record={'started_at':datetime.now(timezone.utc).isoformat(),'assets':args.assets,'completed':[],
            'status':'running','repeats':3,'seed':0,'tolerances':{'position_m':1e-6,'quaternion_component':1e-6},
            'notes':['Personal numerical tolerances, not team verdicts','E2 reuses E1 states; no mj_step',
                     'With a baseline, E1 reuses its verified initial state and preserves native settling differences']}
    (out/'manifest.json').write_text(json.dumps(record,indent=2))
    with (out/'gpu-samples.csv').open('x') as gpu_log:
        monitor=start_gpu_monitor(out,record,gpu_log)
        try:
            for asset in args.assets:
                states=out/(asset+'-cpu')
                initial_args=['--initial-from',args.baseline.resolve()/(asset+'-cpu')] if args.baseline else []
                jobs=[('cpu','osmesa',['physics','--source',args.source,'--asset',asset,'--output',states,*initial_args]),
                      ('sw','osmesa',['render','--states',states,'--require-renderer','llvmpipe','--output',out/(asset+'-sw')]),
                      ('gpu','egl',['render','--states',states,'--require-renderer','NVIDIA','--output',out/(asset+'-gpu')])]
                for label,backend,cmd in jobs:
                    run([ROOT/'scripts/benchmark.py',*cmd],backend,out/(asset+'-'+label+'.log'),max(1,deadline-time.monotonic()))
                    record['completed'].append(asset+'-'+label)
                    (out/'manifest.json').write_text(json.dumps(record,indent=2))
                run([ROOT/'scripts/compare_benchmarks.py','render',out/(asset+'-sw'),out/(asset+'-gpu'),
                     '--output',out/(asset+'-render-comparison.json')],'egl',out/(asset+'-comparison.log'),30)
                if args.baseline:
                    run([ROOT/'scripts/compare_benchmarks.py','physics',args.baseline.resolve()/(asset+'-cpu'),states,
                         '--output',out/(asset+'-physics-comparison.json')],'egl',out/(asset+'-physics-comparison.log'),30)
            for label,backend in [('sw','osmesa'),('gpu','egl')]:
                run([ROOT/'scripts/benchmark.py','source','--source',args.source,'--assets',*args.assets,
                     '--repeats','3','--video','--profile','--output',out/('e3-'+label)],backend,out/('e3-'+label+'.log'),
                    max(1,deadline-time.monotonic()))
                record['completed'].append('e3-'+label)
                report=json.loads((out/('e3-'+label)/'benchmark.json').read_text())
                expected='llvmpipe' if label=='sw' else 'nvidia'
                if not all(x['renderers'] and all(expected in name.lower() for name in x['renderers']) for x in report['records']):
                    raise ValueError(f'E3 {label} used an unexpected renderer')
            run([ROOT/'scripts/compare_benchmarks.py','source',out/'e3-sw',out/'e3-gpu',
                 '--output',out/'e3-comparison.json'],'egl',out/'e3-comparison.log',30)
            record['status']='complete'
        except BaseException as e:
            record['status']='failed';record['error']=f'{type(e).__name__}: {e}'
            raise
        finally:
            monitor.terminate()
            try: monitor.wait(timeout=5)
            except subprocess.TimeoutExpired: monitor.kill();monitor.wait()
            record['finished_at']=datetime.now(timezone.utc).isoformat()
            record['wall_s']=time.monotonic()-start
            (out/'manifest.json').write_text(json.dumps(record,indent=2))


if __name__=='__main__': main()
