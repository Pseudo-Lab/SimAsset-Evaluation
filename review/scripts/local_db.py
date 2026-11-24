"""Start/stop only this prototype's isolated Homebrew PostgreSQL cluster."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
STATE=Path(os.environ.get('SIMASSET_STATE_DIR',ROOT/'.state')).resolve()
PORT=55438


def run(*cmd,check=True):
    return subprocess.run(cmd,text=True,capture_output=True,check=check)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('action',choices=['start','stop','status'])
    args=ap.parse_args(); pg=STATE/'postgres'; marker=STATE/'local-db-owner.json'
    if args.action!='start':
        if not marker.exists(): raise SystemExit('이 시제품이 만든 클러스터가 아닙니다.')
        result=run('pg_ctl','-D',str(pg), 'stop' if args.action=='stop' else 'status',
                   *(['-m','fast'] if args.action=='stop' else []),check=False)
        print(result.stdout or result.stderr); raise SystemExit(result.returncode)
    for tool in ('initdb','pg_ctl','createdb','psql'):
        if not shutil.which(tool): raise SystemExit(f'PostgreSQL 16+의 {tool}을 설치해주세요.')
    STATE.mkdir(parents=True,exist_ok=True); os.chmod(STATE,0o700)
    if not pg.exists():
        password=secrets.token_urlsafe(24)
        pw=STATE/'db.password'; pw.write_text(password); os.chmod(pw,0o600)
        result=run('initdb','-D',str(pg),'--username=simasset_dev','--encoding=UTF8',
                   '--locale=C','--auth-local=trust','--auth-host=scram-sha-256','--pwfile='+str(pw))
        marker.write_text(json.dumps({'project':'simasset-review','cluster':str(pg),'port':PORT}))
        with (pg/'postgresql.conf').open('a') as f:
            f.write(f"\nlisten_addresses='127.0.0.1'\nport={PORT}\nshared_buffers='32MB'\nmax_connections=25\nunix_socket_directories='{STATE}'\n")
    elif not marker.exists():
        raise SystemExit('소유 표식이 없는 기존 DB 폴더는 변경하지 않습니다.')
    status=run('pg_ctl','-D',str(pg),'status',check=False)
    if status.returncode:
        result=run('pg_ctl','-D',str(pg),'-l',str(STATE/'postgres.log'),'-w','start',check=False)
        if result.returncode: raise SystemExit(result.stderr+'\n'+(STATE/'postgres.log').read_text()[-2000:])
    exists=run('psql','-h',str(STATE),'-p',str(PORT),'-U','simasset_dev','-d','postgres','-tAc',
               "SELECT 1 FROM pg_database WHERE datname='simasset_review'").stdout.strip()
    if not exists:
        run('createdb','-h',str(STATE),'-p',str(PORT),'-U','simasset_dev','simasset_review')
    password=(STATE/'db.password').read_text()
    config=STATE/'config.json'
    config.write_text(json.dumps({'database_url':f'postgresql://simasset_dev:{quote(password)}@127.0.0.1:{PORT}/simasset_review'}))
    os.chmod(config,0o600)
    print(f'전용 PostgreSQL 실행 중: 127.0.0.1:{PORT}/simasset_review')


if __name__=='__main__': main()
