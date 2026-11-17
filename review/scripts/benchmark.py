"""Repeatable source harness, CPU physics, saved-state rendering and end-to-end timing.

MUJOCO_GL must be set before starting this process. E2 never calls mj_step.
The user-shared harness is supplied separately; it is not redistributed here.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import time


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))
def env():
    import mujoco
    return {'at':datetime.now(timezone.utc).isoformat(),'os':platform.platform(),
            'machine':platform.machine(),'python':platform.python_version(),'mujoco':mujoco.__version__,
            'logical_cpus':os.cpu_count(),'MUJOCO_GL':os.getenv('MUJOCO_GL','platform-default')}
def source_manifest(root):
    return {p.relative_to(root).as_posix():sha(p) for p in root.rglob('*')
            if p.is_file() and p.suffix in ('.py','.xml','.yaml') and '__pycache__' not in p.parts}
def source_modules(root):
    root=Path(root).resolve();sys.path.insert(0,str(root))
    from common.config import load_config,load_materials
    from common.load_asset import build_model
    from tests.incline import run,ramp_hook,settle_flat,place_on_ramp,_perturb
    return root,load_config,load_materials,build_model,run,ramp_hook,settle_flat,place_on_ramp,_perturb


@contextmanager
def profile_source(enabled):
    """Instrument external call boundaries only; never edit the shared source."""
    timings={};renderers=[];replaced=[]
    def wrap(owner,name,label):
        original=getattr(owner,name)
        def measured(*args,**kwargs):
            start=time.perf_counter()
            try: return original(*args,**kwargs)
            finally: timings[label]=timings.get(label,0)+time.perf_counter()-start
        replaced.append((owner,name,original));setattr(owner,name,measured)
    if enabled:
        import mujoco
        import tests.incline as incline
        import tests.incline_plot as plots
        from common.recorder import ClipRecorder
        wrap(mujoco,'mj_step','cpu_step_s')
        wrap(incline,'build_model','model_build_s')
        wrap(plots,'plot_run','plot_s')
        wrap(ClipRecorder,'maybe_capture','capture_render_encode_s')
        wrap(ClipRecorder,'close','recorder_finalize_s')
        original=ClipRecorder.__init__
        def created(self,*args,**kwargs):
            start=time.perf_counter();original(self,*args,**kwargs)
            timings['recorder_init_s']=timings.get('recorder_init_s',0)+time.perf_counter()-start
            from OpenGL import GL
            name=(GL.glGetString(GL.GL_RENDERER) or b'unknown').decode()
            if name not in renderers: renderers.append(name)
        replaced.append((ClipRecorder,'__init__',original));ClipRecorder.__init__=created
    try: yield timings,renderers
    finally:
        for owner,name,original in reversed(replaced): setattr(owner,name,original)


def source_batch(args):
    root,load,materials,_,run,*_=source_modules(args.source)
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    settings=None
    if args.import_results:
        from simasset_review.db import Settings,import_bundle
        settings=Settings.load()
    records=[]
    source_hashes=source_manifest(root)
    manifest={'kind':'local_reproduction','environment':env(),'source_files':source_hashes,
              'timing_scope':'harness: model load + CPU physics + metrics + file write; video/plot only when requested',
              'repeats':args.repeats,'seed':args.seed,'video':args.video,'records':records}
    original=Path.cwd()
    # Avoid stamping our unrelated review commit into upstream env_meta().
    with tempfile.TemporaryDirectory(prefix='simasset-harness-cwd-') as neutral:
        try:
            os.chdir(neutral)
            for repeat in range(args.repeats):
                for asset in args.assets:
                    asset_path=root/'assets/samples'/f'{asset}.xml'
                    if not asset_path.is_file(): raise ValueError(f'No sample: {asset}')
                    start=time.perf_counter(); cpu=time.process_time()
                    with profile_source(args.profile) as (phases,renderers):
                        result=run(asset_path,load('incline'),args.seed,materials=materials(),
                                   out_root=out/f'repeat-{repeat}',video=args.video,plot=args.video)
                    elapsed=time.perf_counter()-start
                    record={'asset':asset,'repeat':repeat,'seed':args.seed,'source_run_id':result.run_id,
                            'status':result.status,'wall_s':elapsed,'process_cpu_s':time.process_time()-cpu,
                            'output':str(Path(result.out_dir).relative_to(out)),
                            'output_bytes':sum(p.stat().st_size for p in Path(result.out_dir).rglob('*') if p.is_file()),
                            'timeseries_sha256':sha(Path(result.out_dir)/'timeseries.csv') if (Path(result.out_dir)/'timeseries.csv').exists() else None,
                            'error':result.error,'phase_times':phases,'renderers':renderers,
                            'instrumented':args.profile}
                    if settings:
                        namespace=f'{args.namespace}-repeat-{repeat}'
                        record['import']=import_bundle(settings,Path(result.out_dir),namespace,'local_reproduction')
                    records.append(record);write(out/'benchmark.json',manifest)
                    print(json.dumps(record,ensure_ascii=False),flush=True)
        finally: os.chdir(original)


def physics(args):
    import mujoco
    import numpy as np
    root,load,materials,build,_,hook,settle,place,perturb=source_modules(args.source)
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    cfg=load('incline');asset=root/'assets/samples'/f'{args.asset}.xml'
    model,info,scene_hash=build(asset,cfg,'file',materials(),scene_hook=hook(cfg))
    data=mujoco.MjData(model)
    rest,support,settled=settle(model,data,info,cfg)
    q,dpos,pert=perturb(np.random.default_rng(args.seed),cfg)
    place(model,data,info,cfg,rest,q,dpos)
    spec=mujoco.mjtState.mjSTATE_FULLPHYSICS
    initial=np.empty(mujoco.mj_stateSize(model,spec));mujoco.mj_getState(model,data,initial,spec)
    duration=cfg['max_time_s'];steps=round(duration/model.opt.timestep)
    records=[]
    for repeat in range(args.repeats):
        mujoco.mj_setState(model,data,initial,spec);mujoco.mj_forward(model,data)
        start=time.perf_counter();cpu=time.process_time()
        mujoco.mj_step(model,data,nstep=steps)
        record={'repeat':repeat,'physics_wall_s':time.perf_counter()-start,
                'process_cpu_s':time.process_time()-cpu,'final_qpos':data.qpos.tolist(),
                'finite':bool(np.isfinite(data.qpos).all()),'warning_count':int(sum(data.warning.number))}
        records.append(record)
    # A separate, untimed trajectory capture: same starting state, camera and frame times.
    mujoco.mj_setState(model,data,initial,spec);mujoco.mj_forward(model,data)
    states=[];frame_times=[];previous_step=0;fps=cfg['video']['fps']
    for target in np.arange(0,duration,1/fps):
        target_step=round(target/model.opt.timestep)
        if target_step>previous_step: mujoco.mj_step(model,data,nstep=target_step-previous_step)
        state=np.empty(len(initial));mujoco.mj_getState(model,data,state,spec)
        states.append(state);frame_times.append(float(data.time));previous_step=target_step
    np.savez_compressed(out/'states.npz',states=np.array(states),frame_times=np.array(frame_times),initial=initial)
    mujoco.mj_saveModel(model,str(out/'model.mjb'))
    meta={'experiment':'E0/E1-fixed-duration-CPU','environment':env(),'asset':args.asset,
          'asset_sha256':sha(asset),'source_files':source_manifest(root),
          'scene_sha256':scene_hash,'seed':args.seed,'steps':steps,'nq':model.nq,'nv':model.nv,
          'simulated_duration_s':duration,'state_enum':int(spec),'state_size':len(initial),'config':cfg,
          'perturb':pert,'rest_settled':settled is not None,'records':records,
          'states_sha256':sha(out/'states.npz'),'model_sha256':sha(out/'model.mjb'),
          'note':'Fixed duration CPU timing; distinct from the upstream early-stop harness. Capture time is excluded.'}
    write(out/'physics.json',meta);print(json.dumps(meta,ensure_ascii=False),flush=True)


def render(args):
    import mujoco
    import numpy as np
    import imageio.v2 as imageio
    from OpenGL import GL
    src=args.states.resolve();meta=json.loads((src/'physics.json').read_text())
    for file,key in [('states.npz','states_sha256'),('model.mjb','model_sha256')]:
        if sha(src/file)!=meta[key]: raise ValueError(f'Saved-state hash mismatch: {file}')
    if mujoco.__version__!=meta['environment']['mujoco']: raise ValueError('Use the exact recorded MuJoCo version')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    model=mujoco.MjModel.from_binary_path(str(src/'model.mjb'));data=mujoco.MjData(model)
    frames=np.load(src/'states.npz',allow_pickle=False);cfg=meta['config']['video']
    camera=mujoco.MjvCamera();camera.type=mujoco.mjtCamera.mjCAMERA_FREE
    camera.lookat[:]=cfg['cam_fixed_target'];camera.distance=cfg['cam_fixed_dist_m']
    camera.azimuth=90;camera.elevation=-cfg['cam_elevation_deg']
    opt=mujoco.MjvOption();opt.geomgroup[:]=0;opt.geomgroup[0]=1;opt.geomgroup[1]=1
    renderer=mujoco.Renderer(model,cfg['height'],cfg['width'])
    render_name=(GL.glGetString(GL.GL_RENDERER) or b'unknown').decode()
    vendor=(GL.glGetString(GL.GL_VENDOR) or b'unknown').decode()
    if args.require_renderer and args.require_renderer.lower() not in render_name.lower():
        renderer.close();raise ValueError(f'Renderer {render_name!r} does not match requested {args.require_renderer!r}')
    records=[]
    try:
        for repeat in range(args.repeats):
            clip=out/f'replay-{repeat}.mp4';total=time.perf_counter();render_s=encode_feed_s=0
            writer=imageio.get_writer(str(clip),fps=cfg['fps'],codec='libx264',pixelformat='yuv420p',
                                     macro_block_size=8,ffmpeg_params=['-preset','veryfast','-crf','23'])
            try:
                for index,state in enumerate(frames['states']):
                    t=time.perf_counter()
                    mujoco.mj_setState(model,data,state,meta['state_enum']);mujoco.mj_forward(model,data)
                    renderer.update_scene(data,camera=camera,scene_option=opt);img=renderer.render()
                    render_s+=time.perf_counter()-t
                    t=time.perf_counter();writer.append_data(img);encode_feed_s+=time.perf_counter()-t
                    if repeat==0 and index in (0,len(frames['states'])//2):
                        imageio.imwrite(out/f'frame-{index}.png',img)
            finally:
                t=time.perf_counter();writer.close();close_s=time.perf_counter()-t
            records.append({'repeat':repeat,'wall_s':time.perf_counter()-total,'state_forward_render_s':render_s,
                            'encoder_feed_s':encode_feed_s,'encoder_finalize_s':close_s,
                            'frames':len(frames['states']),'bytes':clip.stat().st_size})
    finally: renderer.close()
    report={'experiment':'E2-saved-state-render','environment':env(),'renderer':render_name,'vendor':vendor,
            'states_sha256':meta['states_sha256'],'model_sha256':meta['model_sha256'],'records':records,
            'physics_steps':0,'max_rss_platform_units':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'note':'Render includes state restore and mj_forward, never mj_step. Encoder feed/finalize overlap the external ffmpeg process.'}
    write(out/'render.json',report);print(json.dumps(report,ensure_ascii=False),flush=True)


def main():
    ap=argparse.ArgumentParser();subs=ap.add_subparsers(dest='mode',required=True)
    s=subs.add_parser('source');s.add_argument('--source',required=True,type=Path)
    s.add_argument('--assets',nargs='+',default=['block_mu03','tall_box','blob_mesh'])
    s.add_argument('--namespace',default='local-benchmark');s.add_argument('--import-results',action='store_true')
    s.add_argument('--profile',action='store_true',help='Time source function boundaries; adds instrumentation overhead')
    s.add_argument('--video',action='store_true');s.set_defaults(fn=source_batch)
    p=subs.add_parser('physics');p.add_argument('--source',required=True,type=Path)
    p.add_argument('--asset',default='block_mu03');p.set_defaults(fn=physics)
    r=subs.add_parser('render');r.add_argument('--states',required=True,type=Path)
    r.add_argument('--require-renderer');r.set_defaults(fn=render)
    for parser in (s,p,r):
        parser.add_argument('--output',required=True,type=Path);parser.add_argument('--repeats',type=int,default=3)
        parser.add_argument('--seed',type=int,default=0)
    args=ap.parse_args()
    if not 1<=args.repeats<=20: ap.error('repeats must be 1..20')
    args.fn(args)


if __name__=='__main__': main()
