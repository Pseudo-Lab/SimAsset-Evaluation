from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .db import Settings, list_runs, get_run, add_judgment


class Judgment(BaseModel):
    outcome: Literal['pass','fail','inconclusive']
    reviewer: str = Field(min_length=1,max_length=100)
    criterion_key: str = Field(default='physical_behavior',min_length=1,max_length=100)
    protocol_version: str = Field(default='review-draft-1',min_length=1,max_length=100)
    rationale: str = Field(min_length=1,max_length=5000)
    evidence_ids: list[UUID] = Field(default_factory=list,max_length=20)
    supersedes_judgment_id: UUID | None = None

    @field_validator('reviewer','criterion_key','protocol_version','rationale')
    @classmethod
    def not_blank(cls,v):
        if not v.strip(): raise ValueError('빈 값은 저장할 수 없습니다.')
        return v.strip()


def create_app(settings: Settings | None = None):
    settings = settings or Settings.load()
    app = FastAPI(title='SimAsset Review',version='0.1.0')
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','::1','testserver'])

    @app.middleware('http')
    async def same_origin(request:Request, call_next):
        origin=request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin:
            if urlsplit(origin).netloc != request.headers.get('host'):
                return JSONResponse({'detail':'같은 화면에서 요청해주세요.'},status_code=403)
        result=await call_next(request)
        result.headers['X-Content-Type-Options']='nosniff'
        result.headers['Referrer-Policy']='same-origin'
        return result

    def artifact(artifact_id):
        with settings.connect() as conn:
            ar=conn.execute('SELECT * FROM run_artifacts WHERE artifact_id=%s',(artifact_id,)).fetchone()
        if not ar: raise HTTPException(404,'근거 파일이 없습니다.')
        path=Path(ar['storage_uri']).resolve()
        if not path.is_relative_to((settings.state/'objects').resolve()) or not path.is_file():
            raise HTTPException(409,'보관 파일을 찾을 수 없습니다.')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=ar['sha256']:
            raise HTTPException(409,'보관 파일이 변경됐습니다. 원본과 대조해야 합니다.')
        return ar,path

    @app.get('/api/runs')
    def runs(asset:str='',test:str='',version:str='',origin:str='',offset:int=Query(default=0,ge=0)):
        return list_runs(settings,asset,test,version,origin,offset)

    @app.get('/api/runs/{run_id}')
    def detail(run_id:UUID):
        row=get_run(settings,run_id)
        if not row: raise HTTPException(404,'실행이 없습니다.')
        return row

    @app.get('/api/artifacts/{artifact_id}')
    def media(artifact_id:UUID):
        ar,path=artifact(artifact_id)
        inline=ar['mime_type'] in ('video/mp4','video/webm','image/png','image/jpeg')
        return FileResponse(path,media_type=ar['mime_type'],filename=Path(ar['filename']).name,
                            content_disposition_type='inline' if inline else 'attachment')

    @app.get('/api/runs/{run_id}/series')
    def series(run_id:UUID, channel:Literal['asset','probe']='asset'):
        filename = 'timeseries_probe.csv' if channel=='probe' else 'timeseries.csv'
        units = ({'t':'s','depth_mm':'mm','ball_z_mm':'mm','inside_opening':'bool'}
                 if channel=='probe' else {'t':'s','z':'mm','max_pen':'mm'})
        with settings.connect() as conn:
            row=conn.execute('SELECT artifact_id FROM run_artifacts WHERE run_id=%s AND filename=%s',
                             (run_id,filename)).fetchone()
        if not row: return {'points':[],'units':units}
        _,path=artifact(row['artifact_id'])
        with path.open(encoding='utf-8-sig',newline='') as f:
            rows=[{key:float(x[key]) if x[key].strip() else None for key in units} for x in csv.DictReader(f)]
        # Return all validated samples: decimation must not hide brief penetration peaks.
        return {'points':rows,'units':units}

    @app.post('/api/runs/{run_id}/judgments',status_code=201)
    def judge(run_id:UUID,data:Judgment):
        try: return add_judgment(settings,run_id,data.model_dump())
        except KeyError as e: raise HTTPException(404,str(e)) from e
        except ValueError as e: raise HTTPException(409,str(e)) from e

    @app.get('/api/imports')
    def imports():
        with settings.connect() as conn:
            return conn.execute('''SELECT attempt_id,source_namespace,bundle_sha256,run_id,status,
               diagnostics,created_at FROM import_attempts ORDER BY created_at DESC LIMIT 100''').fetchall()

    @app.get('/api/health')
    def health():
        with settings.connect() as conn: conn.execute('SELECT 1')
        return {'status':'ok','scope':'local-prototype'}

    static=Path(__file__).with_name('static')
    app.mount('/static',StaticFiles(directory=static),name='static')

    @app.get('/')
    def index(): return FileResponse(static/'index.html')
    return app
